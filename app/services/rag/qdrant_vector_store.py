"""Qdrant-backed vector store for production RAG deployments."""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from .chunker import RagChunk
from .vector_store import LocalVectorStore, SearchResult, VectorStore


class QdrantVectorStore(VectorStore):
    """VectorStore implementation backed by one Qdrant collection.

    The collection is shared across tenants, file sets, and knowledge bases;
    request-scoped source isolation is enforced through Qdrant payload filters.
    """

    def __init__(
        self,
        *,
        url: str,
        collection: str,
        vector_size: int,
        api_key: str | None = None,
        timeout_seconds: float = 30,
        create_collection: bool = True,
        distance: str = "Cosine",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not url:
            raise ValueError("Qdrant URL is required")
        if vector_size <= 0:
            raise ValueError("Qdrant vector_size must be greater than 0")

        self.url = url.rstrip("/")
        self.collection = collection
        self.vector_size = vector_size
        self.create_collection = create_collection
        self.distance = distance
        self._owns_client = client is None
        headers = {"api-key": api_key} if api_key else None
        self._client = client or httpx.AsyncClient(
            base_url=self.url,
            timeout=timeout_seconds,
            headers=headers,
        )
        self._initialized = False

    async def upsert_chunks(
        self,
        chunks: list[RagChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or replace chunks and dense vectors in Qdrant."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        await self._ensure_collection()

        points = []
        for chunk, embedding in zip(chunks, embeddings):
            if len(embedding) != self.vector_size:
                raise ValueError(
                    f"Embedding dimension mismatch: collection expects {self.vector_size}-dim, "
                    f"new vector is {len(embedding)}-dim. Chunk: {chunk.chunk_id}"
                )
            points.append(
                {
                    "id": self._point_id(chunk.chunk_id),
                    "vector": [float(value) for value in embedding],
                    "payload": self._payload_from_chunk(chunk),
                }
            )

        if not points:
            return
        response = await self._client.put(
            f"/collections/{self.collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )
        self._raise_for_status(response)

    async def vector_search(
        self,
        query_embedding: list[float],
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Search chunks by Qdrant dense vector similarity."""
        if top_k <= 0:
            return []
        if len(query_embedding) != self.vector_size:
            raise ValueError(
                f"Query embedding dimension mismatch: collection expects {self.vector_size}-dim, "
                f"query vector is {len(query_embedding)}-dim"
            )
        await self._ensure_collection()

        payload: dict[str, Any] = {
            "vector": [float(value) for value in query_embedding],
            "limit": top_k,
            "with_payload": True,
            "with_vector": False,
        }
        qdrant_filter = self._filter_from_sources(sources)
        if qdrant_filter:
            payload["filter"] = qdrant_filter

        response = await self._client.post(
            f"/collections/{self.collection}/points/search",
            json=payload,
        )
        self._raise_for_status(response)
        points = response.json().get("result") or []
        return [self._result_from_point(point, search_type="vector") for point in points]

    async def keyword_search(
        self,
        query: str,
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Run a simple lexical scorer over scoped Qdrant payload text."""
        if top_k <= 0:
            return []
        query_tokens = LocalVectorStore._tokenize(query)
        if not query_tokens:
            return []

        chunks = await self.list_chunks(sources)
        if not chunks:
            return []

        tokenized_chunks = {chunk.chunk_id: LocalVectorStore._tokenize(chunk.text) for chunk in chunks}
        average_length = sum(len(tokens) for tokens in tokenized_chunks.values()) / max(
            1,
            len(tokenized_chunks),
        )
        doc_freqs = LocalVectorStore._document_frequencies(tokenized_chunks.values())
        results: list[SearchResult] = []
        for chunk in chunks:
            score = LocalVectorStore._keyword_score(
                query_tokens=query_tokens,
                chunk_tokens=tokenized_chunks[chunk.chunk_id],
                average_length=average_length,
                total_docs=len(chunks),
                doc_freqs=doc_freqs,
            )
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    source_file_id=chunk.source_file_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    score=score / (score + 1.0),
                    metadata=chunk.metadata,
                    chunk=chunk,
                    search_type="keyword",
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    async def delete_file_set(self, file_set_id: str) -> None:
        """Delete chunks associated with a temporary file set."""
        await self._delete_by_filter(self._match_any_key("file_set_id", "fileSetId", file_set_id))

    async def tag_file_set_as_knowledge_base(
        self,
        *,
        file_set_id: str,
        knowledge_base_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Attach file-set chunks to a persistent knowledge base."""
        await self._ensure_collection()
        qdrant_filter = self._match_any_key("file_set_id", "fileSetId", file_set_id)
        count = await self._count(qdrant_filter)
        if count <= 0:
            return 0
        payload = {
            **(metadata or {}),
            "knowledge_base_id": knowledge_base_id,
            "knowledgeBaseId": knowledge_base_id,
        }
        response = await self._client.post(
            f"/collections/{self.collection}/points/payload",
            params={"wait": "true"},
            json={"payload": payload, "filter": qdrant_filter},
        )
        self._raise_for_status(response)
        return count

    async def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        """Delete chunks associated with a persistent knowledge base."""
        await self._delete_by_filter(
            self._match_any_key("knowledge_base_id", "knowledgeBaseId", knowledge_base_id)
        )

    async def get_chunk(self, chunk_id: str) -> RagChunk | None:
        """Return a chunk by ID."""
        await self._ensure_collection()
        response = await self._client.post(
            f"/collections/{self.collection}/points",
            json={"ids": [self._point_id(chunk_id)], "with_payload": True, "with_vector": False},
        )
        self._raise_for_status(response)
        points = response.json().get("result") or []
        if not points:
            return None
        return self._chunk_from_payload(points[0].get("payload") or {})

    async def list_chunks(self, sources: list[Any] | None = None) -> list[RagChunk]:
        """List chunks, optionally scoped by request sources."""
        await self._ensure_collection()
        chunks: list[RagChunk] = []
        next_offset: Any = None
        qdrant_filter = self._filter_from_sources(sources)
        while True:
            body: dict[str, Any] = {"limit": 256, "with_payload": True, "with_vector": False}
            if qdrant_filter:
                body["filter"] = qdrant_filter
            if next_offset is not None:
                body["offset"] = next_offset
            response = await self._client.post(
                f"/collections/{self.collection}/points/scroll",
                json=body,
            )
            self._raise_for_status(response)
            result = response.json().get("result") or {}
            chunks.extend(
                self._chunk_from_payload(point.get("payload") or {})
                for point in result.get("points") or []
            )
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                break
        chunks.sort(key=lambda chunk: (chunk.source_file_id or "", chunk.chunk_index or 0))
        return chunks

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this store owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        """Return Qdrant collection health details."""
        await self._ensure_collection()
        response = await self._client.get(f"/collections/{self.collection}")
        self._raise_for_status(response)
        return response.json()

    async def _ensure_collection(self) -> None:
        if self._initialized:
            return

        response = await self._client.get(f"/collections/{self.collection}")
        if response.status_code == 404:
            if not self.create_collection:
                raise RuntimeError(f"Qdrant collection does not exist: {self.collection}")
            create_response = await self._client.put(
                f"/collections/{self.collection}",
                json={"vectors": {"size": self.vector_size, "distance": self.distance}},
            )
            self._raise_for_status(create_response)
        else:
            self._raise_for_status(response)
            self._validate_collection_dimension(response.json())

        self._initialized = True

    def _validate_collection_dimension(self, collection_response: dict[str, Any]) -> None:
        config = ((collection_response.get("result") or {}).get("config") or {}).get("params") or {}
        vectors = config.get("vectors") or {}
        stored_size = vectors.get("size") if isinstance(vectors, dict) else None
        if stored_size is not None and int(stored_size) != self.vector_size:
            raise ValueError(
                f"Qdrant collection vector dimension mismatch: collection has {stored_size}, "
                f"current embedder has {self.vector_size}. Reindex into a compatible collection."
            )

    async def _delete_by_filter(self, qdrant_filter: dict[str, Any]) -> None:
        await self._ensure_collection()
        response = await self._client.post(
            f"/collections/{self.collection}/points/delete",
            params={"wait": "true"},
            json={"filter": qdrant_filter},
        )
        self._raise_for_status(response)

    async def _count(self, qdrant_filter: dict[str, Any]) -> int:
        response = await self._client.post(
            f"/collections/{self.collection}/points/count",
            json={"filter": qdrant_filter, "exact": True},
        )
        self._raise_for_status(response)
        return int((response.json().get("result") or {}).get("count") or 0)

    @classmethod
    def _payload_from_chunk(cls, chunk: RagChunk) -> dict[str, Any]:
        metadata = dict(chunk.metadata or {})
        payload = {
            **metadata,
            "chunk_id": chunk.chunk_id,
            "chunkId": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "chunkIndex": chunk.chunk_index,
            "chunk_text": chunk.text,
            "chunkText": chunk.text,
            "token_count": chunk.token_count,
            "tokenCount": chunk.token_count,
            "source_file_id": chunk.source_file_id,
            "sourceFileId": chunk.source_file_id,
        }
        return {key: value for key, value in payload.items() if value is not None}

    @staticmethod
    def _chunk_from_payload(payload: dict[str, Any]) -> RagChunk:
        chunk_id = str(payload.get("chunk_id") or payload.get("chunkId"))
        metadata = dict(payload)
        text = str(payload.get("chunk_text") or payload.get("chunkText") or "")
        chunk_index = payload.get("chunk_index") or payload.get("chunkIndex")
        return RagChunk(
            chunk_id=chunk_id,
            chunk_index=int(chunk_index) if chunk_index is not None else None,
            text=text,
            token_count=int(payload.get("token_count") or payload.get("tokenCount") or 0),
            metadata=metadata,
            source_file_id=payload.get("source_file_id") or payload.get("sourceFileId"),
        )

    @classmethod
    def _result_from_point(cls, point: dict[str, Any], *, search_type: str) -> SearchResult:
        chunk = cls._chunk_from_payload(point.get("payload") or {})
        return SearchResult(
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            score=float(point.get("score") or 0.0),
            metadata=chunk.metadata,
            chunk=chunk,
            search_type=search_type,
        )

    @classmethod
    def _filter_from_sources(cls, sources: list[Any] | None) -> dict[str, Any] | None:
        if not sources:
            return None

        source_filters = []
        for source in sources:
            source_type = cls._source_value(source, "type")
            source_id = cls._source_value(source, "id")
            if not source_type or not source_id:
                continue

            source_must: list[dict[str, Any]] = []
            if source_type == "file_set":
                source_must.append(cls._match_any_key("file_set_id", "fileSetId", str(source_id)))
            elif source_type == "knowledge_base":
                source_must.append(
                    cls._match_any_key("knowledge_base_id", "knowledgeBaseId", str(source_id))
                )
            elif source_type == "external_retriever":
                source_must.append(cls._match_any_key("source_id", "sourceId", str(source_id)))
            else:
                continue

            metadata = cls._source_value(source, "metadata") or {}
            if isinstance(metadata, dict):
                for snake_key, camel_key in (
                    ("tenant_id", "tenantId"),
                    ("owner_id", "ownerId"),
                    ("api_key_id", "apiKeyId"),
                ):
                    expected = metadata.get(snake_key) or metadata.get(camel_key)
                    if expected is not None:
                        source_must.append(cls._match_any_key(snake_key, camel_key, str(expected)))

            source_filters.append({"must": source_must})

        if not source_filters:
            return None
        return {"should": source_filters}

    @staticmethod
    def _match_any_key(snake_key: str, camel_key: str, value: str) -> dict[str, Any]:
        return {
            "should": [
                {"key": snake_key, "match": {"value": value}},
                {"key": camel_key, "match": {"value": value}},
            ]
        }

    @staticmethod
    def _source_value(source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rag-chunk:{chunk_id}"))

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Qdrant request failed: HTTP {response.status_code} {response.text}"
            ) from exc
