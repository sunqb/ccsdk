"""RAG-specific agent runners independent from the Claude Agent core service."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from ...config import settings
from ...models.rag import RagCitation, RagRequestContext, RagStreamRequest
from ...services.agent import agent_service
from .answer_verifier import rag_answer_verifier
from .mcp import create_rag_mcp_server
from .observability import RecordingRagToolService
from .pipeline import abstention_reason_labels, structured_abstention_answer
from .tool_executor import RagToolExecutor, rag_tool_executor
from .tool_schema import rag_direct_tools_schema
from .tools import RagToolService, rag_tool_service
from .vector_store import SearchResult


@dataclass(slots=True)
class RagAgentRunnerConfig:
    """Runtime configuration for RAG-only agent execution."""

    direct_timeout_seconds: float = 120.0
    direct_max_tokens: int = 2048


class RagAgentRunner:
    """Run RAG answers via endpoint-specific SDK MCP or direct tool loops."""

    def __init__(
        self,
        *,
        tool_executor: RagToolExecutor | None = None,
        tool_service: RagToolService | None = None,
        config: RagAgentRunnerConfig | None = None,
    ) -> None:
        self.tool_service = tool_service or rag_tool_service
        self.tool_executor = tool_executor or RagToolExecutor(tool_service=self.tool_service)
        self.config = config or RagAgentRunnerConfig(
            direct_timeout_seconds=settings.rag_direct_timeout_seconds,
            direct_max_tokens=settings.rag_direct_max_tokens,
        )

    @staticmethod
    def sse_event(event: str, data: dict[str, Any]) -> str:
        """Format a RAG SSE event."""
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def anthropic_messages_url(base_url: str | None) -> str | None:
        """Build an Anthropic-compatible messages endpoint URL."""
        if not base_url:
            return None
        return f"{base_url.rstrip('/')}/v1/messages"

    async def stream_claude_sdk(
        self,
        *,
        request: RagStreamRequest,
        context: RagRequestContext,
        request_id: str,
        system_prompt: str,
        allowed_tools: list[str] | None = None,
        cwd: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Primary path: Claude Agent SDK + request-scoped in-process RAG MCP tools.

        ``allowed_tools`` 语义与 Agent SDK 一致：
        - ``[]``：不限制工具（Skills 全开），仅通过 ``mcp_servers`` 注入 RAG tools
        - 非空列表：仅允许列出的工具（如 ``/rag/stream`` 的 RAG MCP 四件套）
        """
        recording_service = RecordingRagToolService(self.tool_service)
        rag_mcp_server = create_rag_mcp_server(context, tool_service=recording_service)
        answer_parts: list[str] = []

        try:
            async for event in agent_service.query_stream(
                prompt=request.message,
                conversation_id=request.conversation_id,
                allowed_tools=allowed_tools,
                max_turns=request.options.max_turns,
                system_prompt=system_prompt,
                cwd=cwd or request.cwd,
                model=request.model,
                base_url=request.base_url,
                api_key=request.api_key,
                result_mode="full",
                mcp_servers={"rag": rag_mcp_server},
            ):
                text = _extract_agent_delta(event)
                if text:
                    answer_parts.append(text)
                    yield self.sse_event("agent_delta", {"text": text, "requestId": request_id})
                elif event.type == "error":
                    yield self.sse_event(
                        "error",
                        {"code": "agent_error", "message": event.data, "requestId": request_id},
                    )
                    return
        except Exception as exc:  # noqa: BLE001
            yield self.sse_event(
                "error",
                {"code": "rag_claude_sdk_error", "message": str(exc), "requestId": request_id},
            )
            return

        answer = "".join(answer_parts)
        citations = self._citations_from_results(recording_service.search_results)
        verification = rag_answer_verifier.verify_answer(
            query=request.message,
            answer=answer,
            citations=citations,
            results=recording_service.search_results,
            min_alignment=settings.rag_min_citation_alignment,
        )
        if _should_abstain(request, verification):
            answer = structured_abstention_answer(abstention_reason_labels(verification.reasons))

        yield self.sse_event(
            "result",
            {
                "answer": answer,
                "citations": [citation.model_dump(by_alias=True) for citation in citations],
                "requestId": request_id,
                "mode": "claude_sdk",
                "toolCalls": recording_service.tool_calls,
                "verification": verification.model_dump(),
            },
        )

    async def stream_direct(
        self,
        *,
        request: RagStreamRequest,
        context: RagRequestContext,
        request_id: str,
        system_prompt: str,
        reason: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Fallback path: Anthropic-compatible direct tool-use loop."""
        api_key = request.api_key or settings.anthropic_api_key
        base_url = request.base_url or settings.anthropic_base_url
        model = request.model or settings.anthropic_model
        url = self.anthropic_messages_url(base_url)
        if not api_key or not url:
            yield self.sse_event(
                "error",
                {
                    "code": "rag_direct_runner_unavailable",
                    "message": reason or "Missing API key or Anthropic-compatible base URL.",
                    "requestId": request_id,
                },
            )
            return

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"{system_prompt}\n\n"
                    "请先使用可用的 RAG 工具检索资料，再基于工具结果回答用户问题。\n"
                    "如果资料不足，请明确说明资料不足。\n\n"
                    f"用户问题：{request.message}"
                ),
            }
        ]
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        answer = ""
        tool_calls: list[dict[str, Any]] = []
        retrieved_results: list[dict[str, Any]] = []

        max_turns = request.options.max_turns

        async with httpx.AsyncClient(timeout=self.config.direct_timeout_seconds) as client:
            for turn in range(max_turns):
                is_final_turn = turn == max_turns - 1
                request_body: dict[str, Any] = {
                    "model": model,
                    "max_tokens": self.config.direct_max_tokens,
                    "messages": messages,
                }
                if not is_final_turn:
                    request_body["tools"] = rag_direct_tools_schema()
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "请根据以上 RAG 工具返回的资料，直接给出最终回答。"
                                "不要再调用任何工具；若资料不足请明确说明。"
                            ),
                        }
                    )
                    request_body["messages"] = messages

                response = await client.post(url, headers=headers, json=request_body)
                response.raise_for_status()
                payload = response.json()
                content = payload.get("content") or []
                if not isinstance(content, list):
                    raise RuntimeError("Invalid direct RAG response content")

                stop_reason = payload.get("stop_reason")
                text_parts = [
                    str(item.get("text") or "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                tool_uses = [
                    item
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "tool_use"
                ]
                if text_parts:
                    answer += "".join(text_parts)

                logger.info(
                    "rag_direct_turn turn=%s/%s stop_reason=%s tool_uses=%s text_len=%s",
                    turn + 1,
                    max_turns,
                    stop_reason,
                    len(tool_uses),
                    sum(len(part) for part in text_parts),
                )

                if is_final_turn or stop_reason != "tool_use" or not tool_uses:
                    async for event in self._yield_direct_result(
                        request=request,
                        request_id=request_id,
                        answer=answer,
                        retrieved_results=retrieved_results,
                        tool_calls=tool_calls,
                        partial=is_final_turn and bool(tool_uses),
                    ):
                        yield event
                    return

                messages.append({"role": "assistant", "content": content})
                tool_results = []
                for tool_use in tool_uses:
                    tool_name = str(tool_use.get("name") or "")
                    tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
                    tool_result = await self.tool_executor.execute(
                        name=tool_name,
                        tool_input=tool_input,
                        context=context,
                    )
                    result_count = len(tool_result) if isinstance(tool_result, list) else None
                    if tool_name == "rag_hybrid_search" and isinstance(tool_result, list):
                        retrieved_results.extend(
                            item for item in tool_result if isinstance(item, dict)
                        )
                    tool_calls.append(
                        {
                            "turn": turn + 1,
                            "name": tool_name,
                            "input": tool_input,
                            "resultCount": result_count,
                        }
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.get("id"),
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )
                messages.append({"role": "user", "content": tool_results})

        search_results = self._search_results_from_payload(retrieved_results)
        if answer.strip() or search_results:
            async for event in self._yield_direct_result(
                request=request,
                request_id=request_id,
                answer=answer,
                retrieved_results=retrieved_results,
                tool_calls=tool_calls,
                partial=True,
            ):
                yield event
            return

        yield self.sse_event(
            "error",
            {
                "code": "rag_direct_runner_max_turns",
                "message": "Direct RAG tool loop reached maxTurns without final answer.",
                "requestId": request_id,
            },
        )

    async def _yield_direct_result(
        self,
        *,
        request: RagStreamRequest,
        request_id: str,
        answer: str,
        retrieved_results: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        partial: bool = False,
    ) -> AsyncGenerator[str, None]:
        """Emit direct-runner SSE result (and optional partial warning)."""
        search_results = self._search_results_from_payload(retrieved_results)
        citations = self._citations_from_results(search_results)
        verification = rag_answer_verifier.verify_answer(
            query=request.message,
            answer=answer,
            citations=citations,
            results=search_results,
            min_alignment=settings.rag_min_citation_alignment,
        )
        if _should_abstain(request, verification):
            answer = structured_abstention_answer(abstention_reason_labels(verification.reasons))
        if answer:
            yield self.sse_event("agent_delta", {"text": answer, "requestId": request_id})
        result_payload: dict[str, Any] = {
            "answer": answer,
            "citations": [citation.model_dump(by_alias=True) for citation in citations],
            "requestId": request_id,
            "mode": "direct",
            "toolCalls": tool_calls,
            "verification": verification.model_dump(),
        }
        if partial:
            result_payload["warning"] = {
                "code": "rag_direct_runner_partial",
                "message": "Answer synthesized after turn budget; increase maxTurns if needed.",
            }
        yield self.sse_event("result", result_payload)

    @staticmethod
    def _search_results_from_payload(payload: list[dict[str, Any]]) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in payload:
            chunk_id = str(item.get("chunkId") or "")
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    source_file_id=item.get("sourceFileId"),
                    chunk_index=item.get("chunkIndex"),
                    text=str(item.get("text") or ""),
                    score=float(item.get("score") or 0.0),
                    metadata=dict(item.get("metadata") or {}),
                    search_type=str(item.get("searchType") or "vector"),
                )
            )
        return results

    def _citations_from_results(self, results: list[SearchResult]) -> list[RagCitation]:
        citations: list[RagCitation] = []
        for result in results[: settings.rag_final_top_k]:
            metadata = result.metadata or {}
            citations.append(
                RagCitation(
                    sourceId=str(
                        metadata.get("sourceFileId")
                        or metadata.get("source_file_id")
                        or result.source_file_id
                        or result.chunk_id
                    ),
                    sourceName=str(
                        metadata.get("filename")
                        or metadata.get("sourceName")
                        or metadata.get("source_name")
                        or "unknown"
                    ),
                    chunkId=result.chunk_id,
                    page=metadata.get("page"),
                    quote=result.text[:240],
                    score=result.score,
                    metadata={
                        **metadata,
                        "sourceFileId": result.source_file_id,
                        "chunkIndex": result.chunk_index,
                        "searchType": result.search_type,
                    },
                )
            )
        return citations


def _extract_agent_delta(event: Any) -> str | None:
    if event.type == "content_block_delta" and event.subtype == "text_delta":
        data = event.data if isinstance(event.data, dict) else {}
        text = data.get("text")
        return text if isinstance(text, str) and text else None
    return None


def _should_abstain(request: RagStreamRequest, verification: Any) -> bool:
    if request.options.abstention_mode == "off":
        return False
    if request.options.verification_mode == "off":
        return False
    if verification.status == "ok":
        return False
    if request.options.verification_mode == "strict":
        return True
    return verification.citation_alignment_score < settings.rag_min_citation_alignment


rag_agent_runner = RagAgentRunner()
