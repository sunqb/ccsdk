"""Execute provider-native RAG tool calls against RagToolService."""
from __future__ import annotations

from typing import Any

from ...models.rag import RagRequestContext
from .tools import RagToolService, rag_tool_service
from .vector_store import SearchResult


def search_result_payload(results: list[SearchResult]) -> list[dict[str, Any]]:
    """Serialize search results for LLM tool results."""
    payload: list[dict[str, Any]] = []
    for result in results:
        payload.append(
            {
                "chunkId": result.chunk_id,
                "sourceFileId": result.source_file_id,
                "chunkIndex": result.chunk_index,
                "text": result.text,
                "score": result.score,
                "searchType": result.search_type,
                "metadata": result.metadata,
            }
        )
    return payload


class RagToolExecutor:
    """Execute a fixed set of request-scoped RAG tools."""

    def __init__(self, tool_service: RagToolService | None = None) -> None:
        self.tool_service = tool_service or rag_tool_service

    async def execute(
        self,
        *,
        name: str,
        tool_input: dict[str, Any],
        context: RagRequestContext,
    ) -> Any:
        """Execute one RAG tool call and return JSON-serializable output."""
        if name == "rag_hybrid_search":
            top_k = tool_input.get("top_k")
            bounded_top_k = int(top_k) if isinstance(top_k, int | float) else context.top_k
            results = await self.tool_service.hybrid_search(
                query=str(tool_input.get("query") or ""),
                context=context,
                top_k=bounded_top_k,
            )
            return search_result_payload(results)

        if name == "rag_read_chunk":
            window = tool_input.get("window", 0)
            bounded_window = int(window) if isinstance(window, int | float) else 0
            chunks = await self.tool_service.read_chunk(
                chunk_id=str(tool_input.get("chunk_id") or ""),
                context=context,
                window=max(0, bounded_window),
            )
            return [
                {
                    "chunkId": chunk.chunk_id,
                    "sourceFileId": chunk.source_file_id,
                    "chunkIndex": chunk.chunk_index,
                    "text": chunk.text,
                    "tokenCount": chunk.token_count,
                    "metadata": chunk.metadata,
                }
                for chunk in chunks
            ]

        if name == "rag_list_sources":
            return await self.tool_service.list_sources(context)

        if name == "rag_get_file_outline":
            return await self.tool_service.get_file_outline(
                source_file_id=str(tool_input.get("source_file_id") or ""),
                context=context,
            )

        return {"error": f"Unknown RAG tool: {name}"}


rag_tool_executor = RagToolExecutor()
