"""Opt-in RAG Agent smoke tests.

These tests exercise the real Claude Agent SDK path and are skipped by default
so local/CI regression runs do not require network access or an API key.
"""
from __future__ import annotations

import os

import pytest

from app.models.rag import RagStreamRequest
from app.routers import rag as rag_router
from app.services.rag import RagIngestionService, RagRetriever, RagToolService


pytestmark = [
    pytest.mark.integration,
    pytest.mark.rag_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_RAG_AGENT_SMOKE") != "1",
        reason="Set RUN_RAG_AGENT_SMOKE=1 to run real RAG Agent smoke tests.",
    ),
]


@pytest.mark.asyncio
async def test_rag_stream_real_agent_mcp_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test the real Agent path with request-scoped RAG MCP tools.

    This intentionally does not monkeypatch ``agent_service.query_stream``. It
    verifies the stream can be driven through `/rag/stream` without the router
    doing server-side pre-retrieval. Use only when a real Claude Agent SDK setup
    is available.
    """
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        pytest.skip("ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required for smoke test.")

    service = RagIngestionService()
    response = await service.ingest_files(
        [("policy.md", b"# Refund\n\nRefunds are available within 30 days.")],
        conversation_id="conv_rag_smoke",
    )
    retriever = RagRetriever(vector_store=service.get_vector_store(), embedder=service.embedder)
    monkeypatch.setattr(rag_router, "rag_tool_service", RagToolService(retriever=retriever))

    request = RagStreamRequest(
        message=(
            "请使用 RAG 工具查询资料后回答：退款期限是多久？"
            "回答必须包含来源文件名或 chunkId。"
        ),
        conversationId="conv_rag_smoke",
        fileSetId=response.file_set_id,
    )
    stream = [event async for event in rag_router._generate_rag_stream(request)]
    rendered = "".join(stream)

    assert "event: retrieval_start" not in rendered
    assert "event: retrieval_result" not in rendered
    assert "event: error" not in rendered
    assert "event: result" in rendered
    assert "30" in rendered or "三十" in rendered
