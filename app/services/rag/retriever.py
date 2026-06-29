"""RAG retrieval service for the MVP."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...config import settings
from ...models.rag import RagCitation, RagRequestContext, RagSource
from .answer_verifier import rag_answer_verifier
from .chunker import RagChunk
from .embeddings import EmbeddingProvider
from .ingestion import rag_ingestion_service
from .reranker import build_reranker
from .vector_store import SearchResult, TOKEN_RE, VectorStore

QUERY_EXPANSIONS = {
    "refund": ["return", "reimburse", "rma"],
    "refunds": ["return", "reimburse", "rma"],
    "return": ["refund", "refunds", "reimburse"],
    "reimburse": ["refund", "refunds"],
    "warranty": ["guarantee", "coverage"],
    "payment": ["pay", "invoice", "billing"],
    "退款": ["退货", "返款", "退款政策"],
    "付款": ["支付", "账期", "发票"],
}


@dataclass(slots=True)
class RetrievalTrace:
    """Trace one retrieval request for tuning and observability."""

    query: str
    variants: list[str]
    retrieve_top_k: int
    final_top_k: int
    stages: list[dict[str, Any]] = field(default_factory=list)

    def add(self, stage: str, **payload: Any) -> None:
        self.stages.append({"stage": stage, **payload})

    def model_dump(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "variants": self.variants,
            "retrieveTopK": self.retrieve_top_k,
            "finalTopK": self.final_top_k,
            "stages": self.stages,
        }


class RagRetriever:
    """Query embedded chunks and build citation-ready retrieval results."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.embedder = embedder or rag_ingestion_service.embedder
        self.vector_store = vector_store or rag_ingestion_service.get_vector_store()

    async def search(
        self,
        query: str,
        *,
        sources: list[RagSource | dict[str, Any]] | None = None,
        top_k: int = 8,
        retrieve_top_k: int | None = None,
        final_top_k: int | None = None,
        hybrid: bool = True,
        query_rewrite: bool = False,
        multi_query: bool = False,
        rerank: bool = False,
        rerank_provider: str | None = None,
        context_window: int = 0,
        trace: RetrievalTrace | None = None,
    ) -> list[SearchResult]:
        """Search indexed chunks with hybrid vector and keyword retrieval."""
        return await self.hybrid_search(
            query,
            sources=sources,
            top_k=top_k,
            retrieve_top_k=retrieve_top_k,
            final_top_k=final_top_k,
            hybrid=hybrid,
            query_rewrite=query_rewrite,
            multi_query=multi_query,
            rerank=rerank,
            rerank_provider=rerank_provider,
            context_window=context_window,
            trace=trace,
        )

    async def hybrid_search(
        self,
        query: str,
        *,
        sources: list[RagSource | dict[str, Any]] | None = None,
        top_k: int = 8,
        retrieve_top_k: int | None = None,
        final_top_k: int | None = None,
        hybrid: bool = True,
        query_rewrite: bool = False,
        multi_query: bool = False,
        rerank: bool = False,
        rerank_provider: str | None = None,
        context_window: int = 0,
        trace: RetrievalTrace | None = None,
    ) -> list[SearchResult]:
        """Combine vector and keyword search results with deduplication."""
        final_k = final_top_k or top_k
        if final_k <= 0:
            return []

        candidate_k = max(retrieve_top_k or settings.rag_retrieve_top_k, final_k)
        variants = self.build_query_variants(
            query,
            query_rewrite=query_rewrite,
            multi_query=multi_query,
        )
        if trace is not None:
            trace.variants[:] = variants
            trace.retrieve_top_k = candidate_k
            trace.final_top_k = final_k
        vector_results: list[SearchResult] = []
        keyword_results: list[SearchResult] = []
        for variant in variants:
            query_embedding = await self.embedder.embed_query(variant)
            current_vector_results = await self.vector_store.vector_search(
                query_embedding=query_embedding,
                sources=sources,
                top_k=candidate_k,
            )
            vector_results.extend(
                self._with_trace_metadata(
                    current_vector_results,
                    query_variant=variant,
                    route="vector",
                )
            )
            if hybrid:
                current_keyword_results = await self.vector_store.keyword_search(
                    query=variant,
                    sources=sources,
                    top_k=candidate_k,
                )
                keyword_results.extend(
                    self._with_trace_metadata(
                        current_keyword_results,
                        query_variant=variant,
                        route="keyword",
                    )
                )
            if trace is not None:
                trace.add(
                    "variant_retrieval",
                    queryVariant=variant,
                    vectorResults=len(current_vector_results),
                    keywordResults=len(current_keyword_results) if hybrid else 0,
                )
        results = self._merge_results(vector_results, keyword_results, top_k=candidate_k)
        if trace is not None:
            trace.add("merge", candidates=len(results))
        if rerank:
            results = await build_reranker(rerank_provider).rerank(
                query=query,
                results=results,
                top_k=candidate_k,
            )
            if trace is not None:
                trace.add("rerank", provider=rerank_provider or settings.rag_rerank_provider)
        if context_window > 0:
            results = await self.expand_results_with_context(
                results,
                sources=sources,
                window=context_window,
                top_k=candidate_k,
            )
            if trace is not None:
                trace.add("context_expansion", window=context_window, candidates=len(results))
        results = results[:final_k]
        if trace is not None:
            trace.add(
                "final",
                results=[
                    {
                        "chunkId": result.chunk_id,
                        "score": result.score,
                        "searchType": result.search_type,
                    }
                    for result in results
                ],
            )
        return results

    async def search_with_context(
        self,
        query: str,
        context: RagRequestContext,
    ) -> list[SearchResult]:
        """Search using request-scoped RAG context."""
        return await self.search(query, sources=context.sources, top_k=context.top_k)

    async def expand_results_with_context(
        self,
        results: list[SearchResult],
        *,
        sources: list[RagSource | dict[str, Any]] | None = None,
        window: int = 1,
        top_k: int = 8,
    ) -> list[SearchResult]:
        """Add neighboring chunks around ranked anchors while preserving source scope."""
        if window <= 0:
            return results[:top_k]

        scoped_chunks = await self.vector_store.list_chunks(sources)
        allowed_chunk_ids = {chunk.chunk_id for chunk in scoped_chunks}
        expanded: dict[str, SearchResult] = {result.chunk_id: result for result in results}
        for result in results:
            for chunk in await self.read_chunk(result.chunk_id, window=window):
                if chunk.chunk_id not in allowed_chunk_ids or chunk.chunk_id in expanded:
                    continue
                metadata = {
                    **chunk.metadata,
                    "contextAnchorChunkId": result.chunk_id,
                }
                expanded[chunk.chunk_id] = SearchResult(
                    chunk_id=chunk.chunk_id,
                    source_file_id=chunk.source_file_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    score=max(0.0, result.score * 0.5),
                    metadata=metadata,
                    chunk=chunk,
                    search_type="context",
                )

        output = list(expanded.values())
        output.sort(key=lambda item: item.score, reverse=True)
        return output[:top_k]

    @classmethod
    def rewrite_query(cls, query: str) -> list[str]:
        """Return deterministic local query expansions for exact-domain terms."""
        normalized = query.strip()
        if not normalized:
            return []

        tokens = cls._tokenize(normalized)
        expanded_terms: list[str] = []
        for token in tokens:
            expanded_terms.extend(QUERY_EXPANSIONS.get(token, []))

        variants = [normalized]
        if expanded_terms:
            variants.append(f"{normalized} {' '.join(dict.fromkeys(expanded_terms))}")
        return list(dict.fromkeys(variants))

    @classmethod
    def build_query_variants(
        cls,
        query: str,
        *,
        query_rewrite: bool,
        multi_query: bool,
    ) -> list[str]:
        """Build deterministic multi-query variants for broad recall."""
        variants = cls.rewrite_query(query) if query_rewrite else [query.strip()]
        normalized = query.strip()
        tokens = cls._tokenize(normalized)
        if multi_query and tokens:
            variants.append(" ".join(tokens))
            variants.extend(tokens[:5])
            if len(tokens) > 2:
                variants.append(" ".join(tokens[: max(2, len(tokens) // 2)]))
        return [variant for variant in dict.fromkeys(variant.strip() for variant in variants) if variant]

    @classmethod
    def rerank_results(cls, query: str, results: list[SearchResult]) -> list[SearchResult]:
        """Apply a lightweight lexical reranker over retrieved chunks."""
        query_tokens = set(cls._tokenize(query))
        if not query_tokens:
            return results

        reranked: list[SearchResult] = []
        for result in results:
            text_tokens = set(cls._tokenize(result.text))
            overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
            metadata_text = " ".join(
                str(value)
                for key, value in (result.metadata or {}).items()
                if key in {"filename", "heading_path", "sourceName"}
            )
            metadata_overlap = len(query_tokens & set(cls._tokenize(metadata_text))) / max(
                1,
                len(query_tokens),
            )
            exact_phrase_boost = 0.15 if query.lower() in result.text.lower() else 0.0
            score = result.score + overlap * 0.8 + metadata_overlap * 0.2 + exact_phrase_boost
            reranked.append(
                SearchResult(
                    chunk_id=result.chunk_id,
                    source_file_id=result.source_file_id,
                    chunk_index=result.chunk_index,
                    text=result.text,
                    score=score,
                    metadata={**(result.metadata or {}), "rerankScore": score},
                    chunk=result.chunk,
                    search_type="rerank" if result.search_type != "context" else "context",
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked

    @classmethod
    def assess_confidence(cls, query: str, results: list[SearchResult]) -> float:
        """Estimate whether retrieved evidence is strong enough to answer."""
        return rag_answer_verifier.retrieval_confidence(query, results)

    @classmethod
    def evaluate_retrieval(
        cls,
        cases: list[dict[str, Any]],
        results_by_case: dict[str, list[SearchResult]],
    ) -> dict[str, Any]:
        """Evaluate top-k retrieval against expected chunk/file identifiers."""
        total = len(cases)
        if total == 0:
            return {"total": 0, "top1HitRate": 0.0, "topKHitRate": 0.0}
        top1_hits = 0
        topk_hits = 0
        for case in cases:
            case_id = str(case["id"])
            expected_chunk_id = case.get("expectedChunkId")
            expected_file_id = case.get("expectedSourceFileId")
            results = results_by_case.get(case_id, [])
            top1 = results[:1]
            top1_hits += int(cls._case_matches(top1, expected_chunk_id, expected_file_id))
            topk_hits += int(cls._case_matches(results, expected_chunk_id, expected_file_id))
        return {
            "total": total,
            "top1HitRate": top1_hits / total,
            "topKHitRate": topk_hits / total,
        }

    @staticmethod
    def _case_matches(
        results: list[SearchResult],
        expected_chunk_id: str | None,
        expected_file_id: str | None,
    ) -> bool:
        for result in results:
            if expected_chunk_id and result.chunk_id == expected_chunk_id:
                return True
            if expected_file_id and result.source_file_id == expected_file_id:
                return True
        return False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        from .text_processing import tokenize

        return tokenize(text)

    async def read_chunk(self, chunk_id: str, window: int = 0) -> list[RagChunk]:
        """Read a chunk and optional neighbors from the same source file."""
        if window < 0:
            raise ValueError("window must be greater than or equal to 0")

        target = await self.vector_store.get_chunk(chunk_id)
        if target is None:
            return []
        if window == 0 or target.chunk_index is None:
            return [target]

        chunks = await self.vector_store.list_chunks()
        same_source = [
            chunk
            for chunk in chunks
            if chunk.source_file_id == target.source_file_id and chunk.chunk_index is not None
        ]
        min_index = target.chunk_index - window
        max_index = target.chunk_index + window
        neighbors = [
            chunk for chunk in same_source if min_index <= chunk.chunk_index <= max_index
        ]
        return sorted(neighbors, key=lambda chunk: chunk.chunk_index)

    @staticmethod
    def build_citations(
        results: list[SearchResult],
        *,
        quote_max_chars: int = 240,
    ) -> list[RagCitation]:
        """Build API citation models from retrieval results."""
        citations: list[RagCitation] = []
        for result in results:
            metadata = result.metadata or {}
            citation_metadata = {
                **metadata,
                "sourceFileId": result.source_file_id,
                "chunkIndex": result.chunk_index,
                "searchType": result.search_type,
            }
            quote = result.text[:quote_max_chars]
            citations.append(
                RagCitation(
                    sourceId=str(
                        metadata.get("source_file_id")
                        or metadata.get("sourceFileId")
                        or result.source_file_id
                        or result.chunk_id
                    ),
                    sourceName=str(
                        metadata.get("filename")
                        or metadata.get("source_name")
                        or metadata.get("sourceName")
                        or "unknown"
                    ),
                    chunkId=result.chunk_id,
                    page=metadata.get("page"),
                    quote=quote,
                    score=result.score,
                    metadata=citation_metadata,
                )
            )
        return citations

    @staticmethod
    def _merge_results(
        vector_results: list[SearchResult],
        keyword_results: list[SearchResult],
        *,
        top_k: int,
    ) -> list[SearchResult]:
        merged: dict[str, SearchResult] = {}
        scores: dict[str, float] = {}
        search_types: dict[str, set[str]] = {}

        def add(results: list[SearchResult], result_type: str, weight: float) -> None:
            for rank, result in enumerate(results, start=1):
                reciprocal_rank = 1.0 / (rank + 60)
                combined_score = weight * (max(0.0, float(result.score)) + reciprocal_rank)
                if result.chunk_id not in merged:
                    merged[result.chunk_id] = SearchResult(
                        chunk_id=result.chunk_id,
                        source_file_id=result.source_file_id,
                        chunk_index=result.chunk_index,
                        text=result.text,
                        score=0.0,
                        metadata=result.metadata,
                        chunk=result.chunk,
                        search_type=result_type,
                    )
                    scores[result.chunk_id] = 0.0
                    search_types[result.chunk_id] = set()

                scores[result.chunk_id] += combined_score
                search_types[result.chunk_id].add(result_type)

        add(vector_results, "vector", 0.55)
        add(keyword_results, "keyword", 0.45)

        output: list[SearchResult] = []
        for chunk_id, result in merged.items():
            result.score = scores[chunk_id]
            result.search_type = (
                "hybrid" if len(search_types[chunk_id]) > 1 else next(iter(search_types[chunk_id]))
            )
            output.append(result)

        output.sort(key=lambda item: item.score, reverse=True)
        return output[:top_k]

    @staticmethod
    def _with_trace_metadata(
        results: list[SearchResult],
        *,
        query_variant: str,
        route: str,
    ) -> list[SearchResult]:
        traced: list[SearchResult] = []
        for result in results:
            metadata = {
                **(result.metadata or {}),
                "retrievalTrace": [
                    *((result.metadata or {}).get("retrievalTrace") or []),
                    {"route": route, "queryVariant": query_variant},
                ],
            }
            traced.append(
                SearchResult(
                    chunk_id=result.chunk_id,
                    source_file_id=result.source_file_id,
                    chunk_index=result.chunk_index,
                    text=result.text,
                    score=result.score,
                    metadata=metadata,
                    chunk=result.chunk,
                    search_type=result.search_type,
                )
            )
        return traced


rag_retriever = RagRetriever()
