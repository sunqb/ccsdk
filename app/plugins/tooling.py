"""ToolSpec 桥接适配器：一份声明，两种消费形态。"""
from __future__ import annotations

import json
from typing import Any

from .base import ToolSpec


def _to_tool_text(payload: Any) -> dict[str, list[dict[str, str]]]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def as_sdk_mcp_server(server_name: str, specs: list[ToolSpec]) -> Any:
    from claude_agent_sdk import create_sdk_mcp_server, tool

    sdk_tools = []
    for spec in specs:
        decorated = tool(spec.name, spec.description, spec.input_schema)(
            _wrap_handler(spec)
        )
        sdk_tools.append(decorated)
    return create_sdk_mcp_server(name=server_name, tools=sdk_tools)


def _wrap_handler(spec: ToolSpec):
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        result = await spec.handler(args)
        return _to_tool_text(result)

    return _handler


def as_anthropic_tools(
    specs: list[ToolSpec],
) -> tuple[list[dict[str, Any]], "ToolDispatcher"]:
    schema = [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in specs
    ]
    return schema, ToolDispatcher(specs)


class ToolDispatcher:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._handlers = {spec.name: spec.handler for spec in specs}

    async def execute(self, name: str, tool_input: dict[str, Any]) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        return await handler(tool_input)
