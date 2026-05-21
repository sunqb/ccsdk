"""Claude Agent SDK in-process MCP tools for request-scoped RAG."""
from __future__ import annotations

import json
from typing import Any

from ...models.rag import RagRequestContext
from .tools import RagToolService, rag_tool_service

RAG_MIN_RELEVANCE_SCORE = 0.3
RAG_EMPTY_PROMPT_HINT = "当前知识库中未找到相关信息。请明确说明资料不足，不要猜测或编造事实。"
RAG_LOW_RELEVANCE_PROMPT_HINT = (
    "知识库匹配度较低。回答必须保守，说明依据不足，并只在必要时引用低相关片段。"
)


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    return {
        "chunkId": chunk.chunk_id,
        "sourceFileId": chunk.source_file_id,
        "chunkIndex": chunk.chunk_index,
        "text": chunk.text,
        "tokenCount": chunk.token_count,
        "metadata": chunk.metadata,
    }


def _search_result_payload(result: Any) -> dict[str, Any]:
    return {
        "chunkId": result.chunk_id,
        "sourceFileId": result.source_file_id,
        "chunkIndex": result.chunk_index,
        "text": result.text,
        "score": result.score,
        "searchType": getattr(result, "search_type", None),
        "metadata": result.metadata,
    }


def _tool_text(payload: Any) -> dict[str, list[dict[str, str]]]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def build_rag_search_response(
    query: str,
    results: list[Any],
    *,
    min_score: float = RAG_MIN_RELEVANCE_SCORE,
) -> dict[str, Any]:
    """Build a structured MCP response that makes insufficient context explicit."""
    payload_results = [_search_result_payload(result) for result in results]
    max_score = max((float(result.score) for result in results), default=None)
    high_relevance_results = [
        payload for payload in payload_results if float(payload.get("score") or 0.0) >= min_score
    ]

    meta: dict[str, Any] = {
        "query": query,
        "total": len(results),
        "minScore": min_score,
        "maxScore": max_score,
        "aboveThreshold": len(high_relevance_results),
    }
    if not results:
        meta.update(
            {
                "status": "empty",
                "promptHint": RAG_EMPTY_PROMPT_HINT,
            }
        )
        return {"results": [], "meta": meta}

    if not high_relevance_results:
        meta.update(
            {
                "status": "low_relevance",
                "warning": f"最高相关分 {max_score:.4f} 低于阈值 {min_score:.4f}。",
                "promptHint": RAG_LOW_RELEVANCE_PROMPT_HINT,
            }
        )
        return {"results": payload_results, "meta": meta}

    meta["status"] = "ok"
    return {"results": high_relevance_results, "meta": meta}


def create_rag_mcp_server(
    context: RagRequestContext,
    *,
    tool_service: RagToolService | None = None,
) -> Any:
    """Create request-scoped RAG MCP tools for Claude Agent SDK."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    service = tool_service or rag_tool_service

    @tool(
        "rag_hybrid_search",
        "Search request-scoped RAG sources and return citation-ready chunks.",
        {
            "query": str,
            "top_k": int,
            "retrieve_top_k": int,
            "final_top_k": int,
            "query_rewrite": bool,
            "multi_query": bool,
            "rerank": bool,
            "context_window": int,
        },
    )
    async def rag_hybrid_search(args: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        query = str(args.get("query") or "")
        top_k = args.get("top_k")
        bounded_top_k = int(top_k) if isinstance(top_k, int | float) else context.top_k
        permissions = context.permissions or {}
        results = await service.hybrid_search(
            query=query,
            context=context,
            top_k=bounded_top_k,
            retrieve_top_k=(
                int(args["retrieve_top_k"])
                if isinstance(args.get("retrieve_top_k"), int | float)
                else permissions.get("retrieveTopK")
            ),
            final_top_k=(
                int(args["final_top_k"])
                if isinstance(args.get("final_top_k"), int | float)
                else permissions.get("finalTopK")
            ),
            hybrid=bool(permissions.get("hybrid", True)),
            query_rewrite=bool(args.get("query_rewrite", permissions.get("queryRewrite", True))),
            multi_query=bool(args.get("multi_query", permissions.get("multiQuery", True))),
            rerank=bool(args.get("rerank", permissions.get("rerank", False))),
            rerank_provider=(
                str(args.get("rerank_provider"))
                if args.get("rerank_provider") is not None
                else permissions.get("rerankProvider")
            ),
            context_window=max(
                0,
                int(args.get("context_window", permissions.get("contextWindow", 0)) or 0),
            ),
        )
        return _tool_text(build_rag_search_response(query, results))

    @tool(
        "rag_read_chunk",
        "Read a chunk and optional neighboring chunks within the request scope.",
        {"chunk_id": str, "window": int},
    )
    async def rag_read_chunk(args: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        chunk_id = str(args.get("chunk_id") or "")
        window = args.get("window", 0)
        bounded_window = int(window) if isinstance(window, int | float) else 0
        chunks = await service.read_chunk(
            chunk_id=chunk_id,
            context=context,
            window=max(0, bounded_window),
        )
        return _tool_text([_chunk_payload(chunk) for chunk in chunks])

    @tool(
        "rag_list_sources",
        "List the RAG sources available to the current request.",
        {},
    )
    async def rag_list_sources(args: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        return _tool_text(await service.list_sources(context))

    @tool(
        "rag_get_file_outline",
        "Return a lightweight outline for one source file within the request scope.",
        {"source_file_id": str},
    )
    async def rag_get_file_outline(args: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
        source_file_id = str(args.get("source_file_id") or "")
        outline = await service.get_file_outline(source_file_id=source_file_id, context=context)
        return _tool_text(outline)

    return create_sdk_mcp_server(
        name="rag-tools",
        version="1.0.0",
        tools=[rag_hybrid_search, rag_read_chunk, rag_list_sources, rag_get_file_outline],
    )


RAG_MCP_ALLOWED_TOOLS = [
    "mcp__rag__rag_hybrid_search",
    "mcp__rag__rag_read_chunk",
    "mcp__rag__rag_list_sources",
    "mcp__rag__rag_get_file_outline",
]
