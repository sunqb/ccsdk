from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI

from app.plugins.base import AgentPlugin, PluginContext, ToolSpec
from app.plugins.registry import PluginRegistry
from app.plugins.tooling import as_anthropic_tools, as_sdk_mcp_server
from app.plugins.rag_plugin import RagPlugin


class _EchoPlugin(AgentPlugin):
    name = "echo"

    def __init__(self, *, enabled: bool = True, fail_startup: bool = False) -> None:
        self._enabled = enabled
        self._fail_startup = fail_startup
        self.started = False
        self.stopped = False

    def is_enabled(self) -> bool:
        return self._enabled

    async def on_startup(self, app: FastAPI) -> None:
        if self._fail_startup:
            raise RuntimeError("startup failed")
        self.started = True

    async def on_shutdown(self) -> None:
        self.stopped = True

    def get_routers(self) -> list[APIRouter]:
        router = APIRouter()

        @router.get("/echo-plugin/ping")
        async def ping() -> dict[str, str]:
            return {"status": "ok"}

        return [router]

    def get_tools(self, ctx: PluginContext) -> list[ToolSpec]:
        async def _handler(tool_input: dict[str, Any]) -> dict[str, Any]:
            return {"echo": tool_input.get("message", "")}

        return [
            ToolSpec(
                name="echo_message",
                description="Echo a message",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
                handler=_handler,
            )
        ]


@pytest.mark.asyncio
async def test_plugin_registry_startup_shutdown_and_router_mount() -> None:
    registry = PluginRegistry()
    plugin = _EchoPlugin()
    registry.register(plugin)

    app = FastAPI()
    await registry.startup_all(app)
    registry.mount_routers(app)
    assert plugin.started is True

    await registry.shutdown_all()
    assert plugin.stopped is True


@pytest.mark.asyncio
async def test_tool_spec_dispatcher_matches_direct_handler() -> None:
    async def _handler(tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"value": tool_input["value"] * 2}

    spec = ToolSpec(
        name="double",
        description="Double a number",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
        handler=_handler,
    )
    _, dispatcher = as_anthropic_tools([spec])

    direct = await _handler({"value": 3})
    dispatched = await dispatcher.execute("double", {"value": 3})
    assert direct == dispatched == {"value": 6}


@pytest.mark.asyncio
async def test_collect_mcp_servers_wraps_tool_specs() -> None:
    registry = PluginRegistry()
    registry.register(_EchoPlugin())
    ctx = PluginContext(request_id="req_test")

    servers = registry.collect_mcp_servers(ctx)
    assert "echo" in servers
    assert servers["echo"] is not None


def test_rag_plugin_enabled_follows_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "rag_enabled", False)
    assert RagPlugin().is_enabled() is False

    monkeypatch.setattr(settings, "rag_enabled", True)
    assert RagPlugin().is_enabled() is True


def test_builtin_registry_registers_rag_plugin() -> None:
    from app.plugins import plugin_registry

    names = [plugin.name for plugin in plugin_registry.plugins]
    assert "rag" in names


def test_agent_sdk_include_partial_with_mcp_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings

    monkeypatch.delenv("AGENT_SDK_INCLUDE_PARTIAL_WITH_MCP", raising=False)
    assert Settings().agent_sdk_include_partial_with_mcp is True
