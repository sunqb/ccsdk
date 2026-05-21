"""Shared RAG request pipeline helpers for routers and agent runners."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from ...config import settings
from ...models.rag import RagRequestContext, RagStreamRequest
from .retriever import RetrievalTrace


def build_request_context(request: RagStreamRequest, *, request_id: str | None = None) -> RagRequestContext:
    """Build request-scoped context with retrieval and verification permissions."""
    final_top_k = request.options.final_top_k or request.options.top_k or settings.rag_final_top_k
    return RagRequestContext(
        requestId=request_id or f"req_{uuid4().hex}",
        conversationId=request.conversation_id,
        sources=request.get_sources(),
        activeFileSetId=request.file_set_id,
        topK=final_top_k,
        permissions={
            "retrieveTopK": request.options.retrieve_top_k or settings.rag_retrieve_top_k,
            "finalTopK": final_top_k,
            "hybrid": request.options.hybrid,
            "queryRewrite": request.options.query_rewrite,
            "multiQuery": request.options.multi_query if request.options.multi_query is not None else settings.rag_enable_multi_query,
            "rerank": request.options.rerank,
            "rerankProvider": request.options.rerank_provider or settings.rag_rerank_provider,
            "contextWindow": request.options.context_window,
            "verificationMode": request.options.verification_mode or settings.rag_verification_mode,
            "abstentionMode": request.options.abstention_mode,
            "minConfidence": request.options.min_confidence,
        },
    )


def new_retrieval_trace(request: RagStreamRequest, *, query: str | None = None) -> RetrievalTrace:
    """Create a retrieval trace aligned with request options."""
    final_top_k = request.options.final_top_k or request.options.top_k or settings.rag_final_top_k
    return RetrievalTrace(
        query=query or request.message,
        variants=[],
        retrieve_top_k=request.options.retrieve_top_k or settings.rag_retrieve_top_k,
        final_top_k=final_top_k,
    )


def structured_abstention_answer(reasons: list[str]) -> str:
    """Return a user-facing abstention message with explicit reasons."""
    if not reasons:
        return "当前知识库中没有找到足够依据回答该问题。请补充相关资料后重试。"
    joined = "；".join(reasons)
    return f"当前知识库中没有找到足够依据回答该问题（{joined}）。请补充相关资料后重试。"


def abstention_reason_labels(reason_codes: list[str]) -> list[str]:
    """Map internal reason codes to user-facing labels."""
    labels = {
        "no_retrieval_results": "未检索到相关资料",
        "weak_retrieval_match": "检索匹配度偏低",
        "citation_alignment_below_threshold": "引用无法支撑答案",
        "answer_not_supported_by_evidence": "回答缺少证据支撑",
    }
    return [labels.get(code, code) for code in reason_codes]
