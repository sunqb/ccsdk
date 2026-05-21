"""RAG tool schemas for provider-native tool-use loops."""
from __future__ import annotations

from typing import Any


def rag_direct_tools_schema() -> list[dict[str, Any]]:
    """Return Anthropic-compatible RAG tool definitions."""
    return [
        {
            "name": "rag_hybrid_search",
            "description": "Search request-scoped RAG sources and return citation-ready chunks.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1},
                    "retrieve_top_k": {"type": "integer", "minimum": 1},
                    "final_top_k": {"type": "integer", "minimum": 1},
                    "query_rewrite": {"type": "boolean"},
                    "multi_query": {"type": "boolean"},
                    "rerank": {"type": "boolean"},
                    "rerank_provider": {"type": "string"},
                    "context_window": {"type": "integer", "minimum": 0},
                },
                "required": ["query"],
            },
        },
        {
            "name": "rag_read_chunk",
            "description": "Read a chunk and optional neighboring chunks within the request scope.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string"},
                    "window": {"type": "integer", "minimum": 0},
                },
                "required": ["chunk_id"],
            },
        },
        {
            "name": "rag_list_sources",
            "description": "List the RAG sources available to the current request.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "rag_get_file_outline",
            "description": "Return a lightweight outline for one source file within the request scope.",
            "input_schema": {
                "type": "object",
                "properties": {"source_file_id": {"type": "string"}},
                "required": ["source_file_id"],
            },
        },
    ]
