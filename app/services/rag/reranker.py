"""Reranker providers for RAG candidate reordering."""
from __future__ import annotations

from typing import Protocol

import httpx

from ...config import settings
from .vector_store import SearchResult, TOKEN_RE


class RerankerProvider(Protocol):
    """Reorder retrieved candidates for final answer grounding."""

    async def rerank(
        self,
        *,
        query: str,
        results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Return reranked search results."""


class LocalLexicalReranker:
    """Deterministic lexical reranker used as a no-dependency fallback."""

    async def rerank(
        self,
        *,
        query: str,
        results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return results[:top_k]

        reranked: list[SearchResult] = []
        for result in results:
            text_tokens = set(_tokenize(result.text))
            overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
            metadata_text = " ".join(
                str(value)
                for key, value in (result.metadata or {}).items()
                if key in {"filename", "heading_path", "headingPath", "sourceName", "sectionTitle"}
            )
            metadata_overlap = len(query_tokens & set(_tokenize(metadata_text))) / max(
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
        return reranked[:top_k]


class CrossEncoderHttpReranker:
    """HTTP adapter for external cross-encoder rerank services."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.rag_rerank_base_url or "").rstrip("/")
        self.model = settings.rag_rerank_model or "bge-reranker-v2-m3"
        self.api_key = settings.rag_rerank_api_key or ""

    async def rerank(
        self,
        *,
        query: str,
        results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        if not self.base_url or not results:
            return await LocalLexicalReranker().rerank(query=query, results=results, top_k=top_k)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": [result.text for result in results],
                    "top_k": top_k,
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

        ranked = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(ranked, list):
            return await LocalLexicalReranker().rerank(query=query, results=results, top_k=top_k)

        output: list[SearchResult] = []
        used_indexes: set[int] = set()
        for item in ranked:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(results):
                continue
            result = results[index]
            score = float(item.get("relevance_score", item.get("score", result.score)))
            used_indexes.add(index)
            output.append(
                SearchResult(
                    chunk_id=result.chunk_id,
                    source_file_id=result.source_file_id,
                    chunk_index=result.chunk_index,
                    text=result.text,
                    score=score,
                    metadata={
                        **(result.metadata or {}),
                        "rerankScore": score,
                        "rerankProvider": "cross_encoder_http",
                        "rerankModel": self.model,
                    },
                    chunk=result.chunk,
                    search_type="rerank" if result.search_type != "context" else "context",
                )
            )

        if len(output) < top_k:
            for index, result in enumerate(results):
                if index in used_indexes:
                    continue
                output.append(result)
                if len(output) >= top_k:
                    break

        return output[:top_k] or await LocalLexicalReranker().rerank(
            query=query,
            results=results,
            top_k=top_k,
        )


def build_reranker(provider: str | None = None) -> RerankerProvider:
    """Create a reranker provider by configuration name."""
    resolved = (provider or settings.rag_rerank_provider or "local_lexical").strip().lower()
    if resolved == "cross_encoder_http":
        return CrossEncoderHttpReranker()
    return LocalLexicalReranker()


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]
