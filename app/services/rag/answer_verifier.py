"""Evidence verification and citation alignment for RAG answers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models.rag import RagCitation
from .vector_store import SearchResult, TOKEN_RE


@dataclass(slots=True)
class RagVerificationResult:
    """Structured verification outcome for confidence gating."""

    retrieval_confidence: float
    citation_alignment_score: float
    answer_support_score: float
    confidence: float
    status: str
    reasons: list[str]

    def model_dump(self) -> dict[str, Any]:
        return {
            "retrievalConfidence": self.retrieval_confidence,
            "citationAlignmentScore": self.citation_alignment_score,
            "answerSupportScore": self.answer_support_score,
            "confidence": self.confidence,
            "status": self.status,
            "reasons": self.reasons,
        }


class RagAnswerVerifier:
    """Lightweight verifier that checks whether evidence supports an answer."""

    def assess_evidence(self, query: str, results: list[SearchResult]) -> RagVerificationResult:
        """Estimate retrieval quality before answer generation."""
        retrieval_confidence = self.retrieval_confidence(query, results)
        citation_alignment_score = self.citation_alignment("", [], results)
        confidence = retrieval_confidence * 0.8 + citation_alignment_score * 0.2
        reasons = []
        if not results:
            reasons.append("no_retrieval_results")
        elif retrieval_confidence < 0.35:
            reasons.append("weak_retrieval_match")
        return RagVerificationResult(
            retrieval_confidence=retrieval_confidence,
            citation_alignment_score=citation_alignment_score,
            answer_support_score=0.0,
            confidence=confidence,
            status="ok" if confidence >= 0.35 else "insufficient_context",
            reasons=reasons,
        )

    def verify_answer(
        self,
        *,
        query: str,
        answer: str,
        citations: list[RagCitation],
        results: list[SearchResult],
        min_alignment: float,
    ) -> RagVerificationResult:
        """Verify final answer support against retrieval evidence and citations."""
        retrieval_confidence = self.retrieval_confidence(query, results)
        citation_alignment_score = self.citation_alignment(answer, citations, results)
        answer_support_score = self.answer_support(answer, results)
        confidence = max(
            0.0,
            min(
                1.0,
                0.35 * retrieval_confidence
                + 0.35 * citation_alignment_score
                + 0.30 * answer_support_score,
            ),
        )
        reasons: list[str] = []
        if not results:
            reasons.append("no_retrieval_results")
        if citations and citation_alignment_score < min_alignment:
            reasons.append("citation_alignment_below_threshold")
        if answer and answer_support_score < 0.25:
            reasons.append("answer_not_supported_by_evidence")
        status = "ok" if not reasons else "insufficient_context"
        return RagVerificationResult(
            retrieval_confidence=retrieval_confidence,
            citation_alignment_score=citation_alignment_score,
            answer_support_score=answer_support_score,
            confidence=confidence,
            status=status,
            reasons=reasons,
        )

    @classmethod
    def retrieval_confidence(cls, query: str, results: list[SearchResult]) -> float:
        if not results:
            return 0.0
        query_tokens = set(cls._tokenize(query))
        if not query_tokens:
            return 0.0
        top = results[0]
        top_tokens = set(cls._tokenize(top.text))
        overlap = len(query_tokens & top_tokens) / max(1, len(query_tokens))
        score_component = max(0.0, min(1.0, top.score))
        support_component = min(1.0, len(results) / 5)
        provenance_bonus = 0.1 if any(result.search_type == "hybrid" for result in results) else 0.0
        return max(
            0.0,
            min(1.0, 0.45 * overlap + 0.35 * score_component + 0.10 * support_component + provenance_bonus),
        )

    @classmethod
    def citation_alignment(
        cls,
        answer: str,
        citations: list[RagCitation],
        results: list[SearchResult],
    ) -> float:
        if not results:
            return 0.0
        if not citations:
            return min(1.0, len(results) / 5)
        result_text_by_chunk = {result.chunk_id: result.text for result in results}
        scores: list[float] = []
        for citation in citations:
            quote = citation.quote or ""
            evidence = result_text_by_chunk.get(citation.chunk_id or "", "")
            if not quote or not evidence:
                scores.append(0.0)
                continue
            quote_tokens = set(cls._tokenize(quote))
            evidence_tokens = set(cls._tokenize(evidence))
            quote_overlap = len(quote_tokens & evidence_tokens) / max(1, len(quote_tokens))
            answer_tokens = set(cls._tokenize(answer))
            answer_overlap = len(answer_tokens & quote_tokens) / max(1, min(len(answer_tokens), len(quote_tokens)) or 1)
            scores.append(max(quote_overlap, answer_overlap))
        return sum(scores) / max(1, len(scores))

    @classmethod
    def answer_support(cls, answer: str, results: list[SearchResult]) -> float:
        answer_tokens = set(cls._tokenize(answer))
        if not answer_tokens or not results:
            return 0.0
        evidence_tokens: set[str] = set()
        for result in results:
            evidence_tokens.update(cls._tokenize(result.text))
        return len(answer_tokens & evidence_tokens) / max(1, len(answer_tokens))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


rag_answer_verifier = RagAnswerVerifier()
