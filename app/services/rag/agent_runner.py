"""RAG-specific agent runners independent from the Claude Agent core service."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx

from ...config import settings
from ...models.rag import RagRequestContext, RagStreamRequest
from .tool_executor import RagToolExecutor, rag_tool_executor
from .tool_schema import rag_direct_tools_schema


@dataclass(slots=True)
class RagAgentRunnerConfig:
    """Runtime configuration for RAG-only agent execution."""

    mode: str = "auto"
    direct_timeout_seconds: float = 120.0
    direct_max_tokens: int = 2048


class RagAgentRunner:
    """Run a provider-native RAG tool loop without touching app.services.agent."""

    def __init__(
        self,
        *,
        tool_executor: RagToolExecutor | None = None,
        config: RagAgentRunnerConfig | None = None,
    ) -> None:
        self.tool_executor = tool_executor or rag_tool_executor
        self.config = config or RagAgentRunnerConfig(
            mode=settings.rag_agent_mode,
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

    def should_use_direct(self, *, base_url: str | None, mode: str | None = None) -> bool:
        """Return whether direct tool loop should be the primary RAG path."""
        resolved_mode = (mode or self.config.mode or "auto").strip().lower()
        if resolved_mode == "direct":
            return True
        if resolved_mode == "claude_sdk":
            return False
        if resolved_mode != "auto":
            return False
        if not base_url:
            return False
        normalized = base_url.lower()
        return "anthropic.com" not in normalized

    def should_fallback_to_direct(self, data: Any, *, base_url: str | None) -> bool:
        """Detect Claude Code MCP transport failures that direct tool loop can bypass."""
        if not self.should_use_direct(base_url=base_url, mode="auto"):
            return False
        text = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
        return "ProcessTransport is not ready for writing" in text or "TaskGroup" in text

    async def stream_direct(
        self,
        *,
        request: RagStreamRequest,
        context: RagRequestContext,
        request_id: str,
        system_prompt: str,
        reason: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a RAG answer through an Anthropic-compatible tool-use loop."""
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

        async with httpx.AsyncClient(timeout=self.config.direct_timeout_seconds) as client:
            for turn in range(request.options.max_turns):
                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "max_tokens": self.config.direct_max_tokens,
                        "messages": messages,
                        "tools": rag_direct_tools_schema(),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = payload.get("content") or []
                if not isinstance(content, list):
                    raise RuntimeError("Invalid direct RAG response content")

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

                if payload.get("stop_reason") != "tool_use" or not tool_uses:
                    if answer:
                        yield self.sse_event("agent_delta", {"text": answer, "requestId": request_id})
                    yield self.sse_event(
                        "result",
                        {
                            "answer": answer,
                            "citations": [],
                            "requestId": request_id,
                            "mode": "direct",
                            "toolCalls": tool_calls,
                        },
                    )
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

        yield self.sse_event(
            "error",
            {
                "code": "rag_direct_runner_max_turns",
                "message": "Direct RAG tool loop reached maxTurns without final answer.",
                "requestId": request_id,
            },
        )


rag_agent_runner = RagAgentRunner()
