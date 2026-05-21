"""RAG observability helpers for tool-call and retrieval tracking."""
from __future__ import annotations

from typing import Any

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
        results = await self.inner.hybrid_search(**kwargs)
        self.search_results = results
        self.tool_calls.append(
            {
                "name": "rag_hybrid_search",
                "query": kwargs.get("query"),
                "resultCount": len(results),
            }
        )
        return results

    async def read_chunk(self, **kwargs: Any) -> list[Any]:
        chunks = await self.inner.read_chunk(**kwargs)
        self.tool_calls.append(
            {
                "name": "rag_read_chunk",
                "chunkId": kwargs.get("chunk_id"),
                "resultCount": len(chunks),
            }
        )
        return chunks

    async def list_sources(self, context: Any) -> list[dict[str, Any]]:
        self.tool_calls.append({"name": "rag_list_sources"})
        return await self.inner.list_sources(context)

    async def get_file_outline(self, **kwargs: Any) -> dict[str, Any]:
        self.tool_calls.append(
            {
                "name": "rag_get_file_outline",
                "sourceFileId": kwargs.get("source_file_id"),
            }
        )
        return await self.inner.get_file_outline(**kwargs)
