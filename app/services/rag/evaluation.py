"""Local RAG evaluation harness for retrieval and abstention metrics."""
from __future__ import annotations

from typing import Any

from .retriever import RagRetriever, RetrievalTrace
from .vector_store import SearchResult


DEFAULT_EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "refund_days",
        "query": "refund within 30 days",
        "expectedAnswerContains": ["30"],
        "mustRetrieve": True,
    },
    {
        "id": "unknown_clause",
        "query": "ZX-999 unicorn refund clause",
        "expectedAnswerContains": [],
        "mustRetrieve": False,
    },
    {
        "id": "payment_terms",
        "query": "payment invoice billing",
        "expectedAnswerContains": ["payment", "invoice"],
        "mustRetrieve": True,
    },
]


async def evaluate_retrieval_cases(
    retriever: RagRetriever,
    *,
    cases: list[dict[str, Any]],
    sources: list[Any],
    retrieve_top_k: int = 100,
    final_top_k: int = 8,
    query_rewrite: bool = True,
    multi_query: bool = True,
    rerank: bool = True,
) -> dict[str, Any]:
    """Run retrieval-only evaluation and return aggregate metrics."""
    results_by_case: dict[str, list[SearchResult]] = {}
    traces_by_case: dict[str, dict[str, Any]] = {}
    for case in cases:
        trace = RetrievalTrace(
            query=str(case["query"]),
            variants=[],
            retrieve_top_k=retrieve_top_k,
            final_top_k=final_top_k,
        )
        results = await retriever.search(
            str(case["query"]),
            sources=sources,
            retrieve_top_k=retrieve_top_k,
            final_top_k=final_top_k,
            query_rewrite=query_rewrite,
            multi_query=multi_query,
            rerank=rerank,
            trace=trace,
        )
        case_id = str(case["id"])
        results_by_case[case_id] = results
        traces_by_case[case_id] = trace.model_dump()

    metrics = RagRetriever.evaluate_retrieval(cases, results_by_case)
    abstention_cases = [case for case in cases if not case.get("mustRetrieve", True)]
    abstention_hits = 0
    for case in abstention_cases:
        if not results_by_case.get(str(case["id"])):
            abstention_hits += 1
    metrics["abstentionCaseCount"] = len(abstention_cases)
    metrics["abstentionHitRate"] = abstention_hits / max(1, len(abstention_cases))
    metrics["traces"] = traces_by_case
    return metrics
