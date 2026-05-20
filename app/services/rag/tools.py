"""Request-scoped RAG helper tools for the MVP.

These helpers mirror the future Claude Agent SDK tool contract, but are plain
Python functions for now. The `/rag/stream` MVP uses them server-side before
calling the Agent, which keeps source-scope enforcement outside the prompt.
"""
from __future__ import annotations

from typing import Any

from ...models.rag import RagCitation, RagRequestContext
from .chunker import RagChunk
from .retriever import RagRetriever, rag_retriever
from .vector_store import SearchResult


class RagToolService:
    """Request-scoped RAG tool facade."""

    def __init__(self, retriever: RagRetriever | None = None) -> None:
        self.retriever = retriever or rag_retriever

    async def hybrid_search(
        self,
        *,
        query: str,
        context: RagRequestContext,
        top_k: int | None = None,
        query_rewrite: bool = False,
        rerank: bool = False,
        context_window: int = 0,
    ) -> list[SearchResult]:
        """Search within the sources allowed by the request context."""
        bounded_top_k = min(top_k or context.top_k, context.top_k)
        return await self.retriever.search(
            query,
            sources=context.sources,
            top_k=bounded_top_k,
            query_rewrite=query_rewrite,
            rerank=rerank,
            context_window=context_window,
        )

    async def read_chunk(
        self,
        *,
        chunk_id: str,
        context: RagRequestContext,
        window: int = 0,
    ) -> list[RagChunk]:
        """Read a chunk only if it belongs to the current request scope."""
        scoped_chunks = await self.retriever.vector_store.list_chunks(context.sources)
        allowed_chunk_ids = {chunk.chunk_id for chunk in scoped_chunks}
        if chunk_id not in allowed_chunk_ids:
            return []

        chunks = await self.retriever.read_chunk(chunk_id, window=window)
        return [chunk for chunk in chunks if chunk.chunk_id in allowed_chunk_ids]

    async def list_sources(self, context: RagRequestContext) -> list[dict[str, Any]]:
        """Return request-scoped source descriptors."""
        return [source.model_dump(by_alias=True) for source in context.sources]

    async def get_file_outline(
        self,
        *,
        source_file_id: str,
        context: RagRequestContext,
    ) -> dict[str, Any]:
        """Return a lightweight chunk outline for one scoped source file."""
        scoped_chunks = await self.retriever.vector_store.list_chunks(context.sources)
        file_chunks = [chunk for chunk in scoped_chunks if chunk.source_file_id == source_file_id]
        if not file_chunks:
            return {
                "sourceFileId": source_file_id,
                "found": False,
                "chunkCount": 0,
                "sections": [],
            }

        file_chunks.sort(key=lambda chunk: chunk.chunk_index if chunk.chunk_index is not None else -1)
        metadata = file_chunks[0].metadata or {}
        sections = []
        for chunk in file_chunks:
            first_line = next((line.strip() for line in chunk.text.splitlines() if line.strip()), "")
            sections.append(
                {
                    "chunkId": chunk.chunk_id,
                    "chunkIndex": chunk.chunk_index,
                    "title": first_line[:120] or f"Chunk {chunk.chunk_index}",
                    "tokenCount": chunk.token_count,
                    "metadata": chunk.metadata,
                }
            )

        return {
            "sourceFileId": source_file_id,
            "sourceName": metadata.get("filename") or metadata.get("sourceName") or source_file_id,
            "found": True,
            "chunkCount": len(file_chunks),
            "sections": sections,
            "metadata": metadata,
        }

    def build_citations(self, results: list[SearchResult]) -> list[RagCitation]:
        """Build public citation objects from search results."""
        return self.retriever.build_citations(results)


rag_tool_service = RagToolService()
