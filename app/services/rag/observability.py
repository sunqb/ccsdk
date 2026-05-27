"""RAG observability helpers for tool-call and retrieval tracking."""
from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import uuid4

from .tools import RagToolService
from .vector_store import SearchResult


class RecordingRagToolService(RagToolService):
    """Wrap RagToolService to capture hybrid_search results for post-hoc citations."""

    def __init__(self, inner: RagToolService) -> None:
        super().__init__(retriever=inner.retriever)
        self.inner = inner
        self.tool_calls: list[dict[str, Any]] = []
        self.search_results: list[SearchResult] = []

    async def hybrid_search(self, **kwargs: Any) -> list[SearchResult]:
        started = perf_counter()
        results = await self.inner.hybrid_search(**kwargs)
        latency_ms = int((perf_counter() - started) * 1000)
        self.search_results = results
        self.tool_calls.append(
            {
                "toolCallId": f"toolcall_{uuid4().hex}",
                "name": "rag_hybrid_search",
                "query": kwargs.get("query"),
                "resultCount": len(results),
                "latencyMs": latency_ms,
            }
        )
        return results

    async def read_chunk(self, **kwargs: Any) -> list[Any]:
        started = perf_counter()
        chunks = await self.inner.read_chunk(**kwargs)
        latency_ms = int((perf_counter() - started) * 1000)
        self.tool_calls.append(
            {
                "toolCallId": f"toolcall_{uuid4().hex}",
                "name": "rag_read_chunk",
                "chunkId": kwargs.get("chunk_id"),
                "resultCount": len(chunks),
                "latencyMs": latency_ms,
            }
        )
        return chunks

    async def list_sources(self, context: Any) -> list[dict[str, Any]]:
        started = perf_counter()
        sources = await self.inner.list_sources(context)
        self.tool_calls.append(
            {
                "toolCallId": f"toolcall_{uuid4().hex}",
                "name": "rag_list_sources",
                "resultCount": len(sources),
                "latencyMs": int((perf_counter() - started) * 1000),
            }
        )
        return sources

    async def get_file_outline(self, **kwargs: Any) -> dict[str, Any]:
        started = perf_counter()
        outline = await self.inner.get_file_outline(**kwargs)
        self.tool_calls.append(
            {
                "toolCallId": f"toolcall_{uuid4().hex}",
                "name": "rag_get_file_outline",
                "sourceFileId": kwargs.get("source_file_id"),
                "resultCount": int(outline.get("chunkCount") or 0),
                "latencyMs": int((perf_counter() - started) * 1000),
            }
        )
        return outline
