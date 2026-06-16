"""Agent 插件契约。

设计原则：
- 所有钩子都有默认空实现，插件按需覆写，最小插件只需提供 name。
- 钩子失败不应拖垮服务：registry 层统一 try/except + 日志降级。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, FastAPI


@dataclass
class PluginContext:
    """请求级上下文，由核心统一构建后传给插件钩子。"""
    request_id: str
    conversation_id: str | None = None
    space_id: str | None = None
    tenant_id: str | None = None
    owner_id: str | None = None
    api_key_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class CleanupTask:
    """插件注册的清理任务，由 /admin/cleanup 或外部定时任务统一触发。"""
    name: str
    run: Callable[[], Awaitable[int]]


@dataclass
class ToolSpec:
    """协议中立的工具声明：插件声明一次，MCP 与 tool_use 两条路径均可消费。"""
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[Any]]


class AgentPlugin:
    """插件基类。覆写所需钩子即可，未覆写的钩子为 no-op。"""

    name: str = "unnamed"

    def is_enabled(self) -> bool:
        return True

    async def on_startup(self, app: FastAPI) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_routers(self) -> list[APIRouter]:
        return []

    def get_tools(self, ctx: PluginContext) -> list[ToolSpec]:
        return []

    def build_mcp_server(self, ctx: PluginContext) -> Any | None:
        return None

    def system_prompt_fragment(self, ctx: PluginContext) -> str | None:
        return None

    def cleanup_tasks(self) -> list[CleanupTask]:
        return []
