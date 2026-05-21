"""In-memory vector store for the RAG MVP."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from .chunker import RagChunk

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*|[\u4e00-\u9fff]")


@dataclass(slots=True)
class SearchResult:
    """Search result with the matched chunk, score, and retrieval provenance."""

    chunk_id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    source_file_id: str | None = None
    chunk_index: int | None = None
    chunk: RagChunk | None = None
    search_type: str = "vector"


class VectorStore(Protocol):
    """Storage contract implemented by local and future external vector stores."""

    async def upsert_chunks(
        self,
        chunks: list[RagChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or replace chunks and embeddings."""

    async def vector_search(
        self,
        query_embedding: list[float],
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Search chunks by vector similarity."""

    async def keyword_search(
        self,
        query: str,
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Search chunks lexically when the backend supports it."""

    async def delete_file_set(self, file_set_id: str) -> None:
        """Delete chunks associated with a file set."""

    async def tag_file_set_as_knowledge_base(
        self,
        *,
        file_set_id: str,
        knowledge_base_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Attach file-set chunks to a knowledge base."""

    async def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        """Delete chunks associated with a knowledge base."""

    async def get_chunk(self, chunk_id: str) -> RagChunk | None:
        """Return a chunk by ID."""

    async def list_chunks(self, sources: list[Any] | None = None) -> list[RagChunk]:
        """List chunks, optionally scoped by sources."""


class LocalVectorStore:
    """Simple in-memory vector store for MVP development and tests."""

    def __init__(self) -> None:
        self._chunks: dict[str, RagChunk] = {}
        self._embeddings: dict[str, list[float]] = {}

    async def upsert_chunks(
        self,
        chunks: list[RagChunk],
        embeddings: list[list[float]],
    ) -> None:
        """Insert or replace chunks and their embeddings."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")

        for chunk, embedding in zip(chunks, embeddings):
            self._chunks[chunk.chunk_id] = chunk
            self._embeddings[chunk.chunk_id] = embedding

    async def vector_search(
        self,
        query_embedding: list[float],
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Search chunks by cosine similarity."""
        if top_k <= 0:
            return []

        results: list[SearchResult] = []
        for chunk_id, chunk in self._chunks.items():
            if sources and not self._matches_sources(chunk, sources):
                continue

            embedding = self._embeddings.get(chunk_id)
            if embedding is None:
                continue

            score = self._cosine_similarity(query_embedding, embedding)
            results.append(self._result_from_chunk(chunk, score=score, search_type="vector"))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    async def keyword_search(
        self,
        query: str,
        sources: list[Any] | None = None,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Search chunks using a local BM25-style lexical scorer."""
        if top_k <= 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        candidates = [
            chunk
            for chunk in self._chunks.values()
            if not sources or self._matches_sources(chunk, sources)
        ]
        if not candidates:
            return []

        tokenized_chunks = {chunk.chunk_id: self._tokenize(chunk.text) for chunk in candidates}
        avg_len = sum(len(tokens) for tokens in tokenized_chunks.values()) / max(
            1,
            len(tokenized_chunks),
        )
        doc_freqs = self._document_frequencies(tokenized_chunks.values())
        total_docs = len(candidates)

        results: list[SearchResult] = []
        for chunk in candidates:
            score = self._keyword_score(
                query_tokens=query_tokens,
                chunk_tokens=tokenized_chunks[chunk.chunk_id],
                average_length=avg_len,
                total_docs=total_docs,
                doc_freqs=doc_freqs,
            )
            if score <= 0:
                continue
            normalized_score = score / (score + 1.0)
            results.append(
                self._result_from_chunk(
                    chunk,
                    score=normalized_score,
                    search_type="keyword",
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]

    async def delete_file_set(self, file_set_id: str) -> None:
        """Delete chunks associated with a file set."""
        delete_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if self._chunk_file_set_id(chunk) == file_set_id
        ]
        for chunk_id in delete_ids:
            self._chunks.pop(chunk_id, None)
            self._embeddings.pop(chunk_id, None)

    async def tag_file_set_as_knowledge_base(
        self,
        *,
        file_set_id: str,
        knowledge_base_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Attach file-set chunks to a persistent knowledge base."""
        tagged = 0
        tag_metadata = metadata or {}
        for chunk in self._chunks.values():
            if self._chunk_file_set_id(chunk) != file_set_id:
                continue
            chunk.metadata.update(
                {
                    **tag_metadata,
                    "knowledge_base_id": knowledge_base_id,
                    "knowledgeBaseId": knowledge_base_id,
                }
            )
            tagged += 1
        return tagged

    async def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        """Delete chunks associated with a knowledge base."""
        delete_ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if self._chunk_knowledge_base_id(chunk) == knowledge_base_id
        ]
        for chunk_id in delete_ids:
            self._chunks.pop(chunk_id, None)
            self._embeddings.pop(chunk_id, None)

    async def get_chunk(self, chunk_id: str) -> RagChunk | None:
        """Return a chunk by ID."""
        return self._chunks.get(chunk_id)

    async def list_chunks(self, sources: list[Any] | None = None) -> list[RagChunk]:
        """List chunks, optionally scoped by sources."""
        chunks = list(self._chunks.values())
        if not sources:
            return chunks
        return [chunk for chunk in chunks if self._matches_sources(chunk, sources)]

    def dump_records(self) -> list[dict[str, Any]]:
        """Serialize local chunks and embeddings for durable metadata snapshots."""
        records: list[dict[str, Any]] = []
        for chunk_id, chunk in self._chunks.items():
            records.append(
                {
                    "chunkId": chunk_id,
                    "chunkIndex": chunk.chunk_index,
                    "text": chunk.text,
                    "tokenCount": chunk.token_count,
                    "metadata": chunk.metadata,
                    "sourceFileId": chunk.source_file_id,
                    "embedding": self._embeddings.get(chunk_id),
                }
            )
        return records

    def load_records(self, records: list[dict[str, Any]]) -> None:
        """Restore local chunks and embeddings from a durable snapshot."""
        self._chunks.clear()
        self._embeddings.clear()
        for record in records:
            chunk_id = str(record["chunkId"])
            chunk = RagChunk(
                chunk_id=chunk_id,
                chunk_index=int(record.get("chunkIndex") or 0),
                text=str(record.get("text") or ""),
                token_count=int(record.get("tokenCount") or 0),
                metadata=dict(record.get("metadata") or {}),
                source_file_id=record.get("sourceFileId"),
            )
            self._chunks[chunk_id] = chunk
            embedding = record.get("embedding")
            if isinstance(embedding, list):
                self._embeddings[chunk_id] = [float(value) for value in embedding]

    @staticmethod
    def _result_from_chunk(chunk: RagChunk, *, score: float, search_type: str) -> SearchResult:
        return SearchResult(
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            score=score,
            metadata=chunk.metadata,
            chunk=chunk,
            search_type=search_type,
        )

    @classmethod
    def _matches_sources(cls, chunk: RagChunk, sources: list[Any]) -> bool:
        for source in sources:
            source_type = cls._source_value(source, "type")
            source_id = cls._source_value(source, "id")
            if not source_type or not source_id:
                continue

            if not cls._matches_source_permissions(chunk, source):
                continue

            if source_type == "file_set" and cls._chunk_file_set_id(chunk) == source_id:
                return True
            if source_type == "knowledge_base" and cls._chunk_knowledge_base_id(chunk) == source_id:
                return True
            if source_type == "external_retriever" and cls._chunk_source_id(chunk) == source_id:
                return True

        return False

    @staticmethod
    def _source_value(source: Any, key: str) -> Any:
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    @classmethod
    def _matches_source_permissions(cls, chunk: RagChunk, source: Any) -> bool:
        metadata = cls._source_value(source, "metadata") or {}
        if not isinstance(metadata, dict):
            return True

        permission_keys = [
            ("tenant_id", "tenantId"),
            ("owner_id", "ownerId"),
            ("api_key_id", "apiKeyId"),
        ]
        for snake_key, camel_key in permission_keys:
            expected = metadata.get(snake_key) or metadata.get(camel_key)
            if expected is None:
                continue
            actual = chunk.metadata.get(snake_key) or chunk.metadata.get(camel_key)
            if str(actual) != str(expected):
                return False
        return True

    @classmethod
    def _chunk_file_set_id(cls, chunk: RagChunk) -> str | None:
        value = chunk.metadata.get("file_set_id") or chunk.metadata.get("fileSetId")
        if value:
            return str(value)
        return chunk.source_file_id

    @staticmethod
    def _chunk_knowledge_base_id(chunk: RagChunk) -> str | None:
        value = chunk.metadata.get("knowledge_base_id") or chunk.metadata.get("knowledgeBaseId")
        return str(value) if value else None

    @staticmethod
    def _chunk_source_id(chunk: RagChunk) -> str | None:
        value = chunk.metadata.get("source_id") or chunk.metadata.get("sourceId")
        if value:
            return str(value)
        return chunk.source_file_id

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0

        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]

    @staticmethod
    def _document_frequencies(token_lists: Any) -> Counter[str]:
        frequencies: Counter[str] = Counter()
        for tokens in token_lists:
            frequencies.update(set(tokens))
        return frequencies

    @staticmethod
    def _keyword_score(
        *,
        query_tokens: list[str],
        chunk_tokens: list[str],
        average_length: float,
        total_docs: int,
        doc_freqs: Counter[str],
    ) -> float:
        if not query_tokens or not chunk_tokens:
            return 0.0

        term_counts = Counter(chunk_tokens)
        chunk_len = len(chunk_tokens)
        k1 = 1.5
        b = 0.75
        score = 0.0
        for term in set(query_tokens):
            tf = term_counts.get(term, 0)
            if tf <= 0:
                continue
            df = doc_freqs.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denominator = tf + k1 * (1 - b + b * chunk_len / max(1.0, average_length))
            score += idf * ((tf * (k1 + 1)) / denominator)
        return score
