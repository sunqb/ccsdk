"""插件注册表：核心唯一感知插件的位置。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from .base import AgentPlugin, CleanupTask, PluginContext, ToolSpec
from .tooling import ToolDispatcher, as_anthropic_tools, as_sdk_mcp_server

logger = logging.getLogger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: list[AgentPlugin] = []

    def register(self, plugin: AgentPlugin) -> None:
        self._plugins.append(plugin)

    @property
    def plugins(self) -> list[AgentPlugin]:
        return list(self._plugins)

    @property
    def enabled_plugins(self) -> list[AgentPlugin]:
        return [plugin for plugin in self._plugins if plugin.is_enabled()]

    def list_plugin_status(self) -> list[dict[str, Any]]:
        return [{"name": plugin.name, "enabled": plugin.is_enabled()} for plugin in self._plugins]

    async def startup_all(self, app: FastAPI) -> None:
        for plugin in self.enabled_plugins:
            try:
                await plugin.on_startup(app)
                logger.info("[Plugin] %s started", plugin.name)
            except Exception:
                logger.exception("[Plugin] %s startup failed (degraded)", plugin.name)

    async def shutdown_all(self) -> None:
        for plugin in self.enabled_plugins:
            try:
                await plugin.on_shutdown()
            except Exception:
                logger.exception("[Plugin] %s shutdown failed", plugin.name)

    def mount_routers(self, app: FastAPI) -> None:
        for plugin in self.enabled_plugins:
            for router in plugin.get_routers():
                app.include_router(router)

    def collect_mcp_servers(self, ctx: PluginContext) -> dict[str, Any]:
        servers: dict[str, Any] = {}
        for plugin in self.enabled_plugins:
            try:
                server = plugin.build_mcp_server(ctx)
                if server is None:
                    specs = plugin.get_tools(ctx)
                    if specs:
                        server = as_sdk_mcp_server(plugin.name, specs)
                if server is not None:
                    servers[plugin.name] = server
            except Exception:
                logger.exception("[Plugin] %s tool collection failed", plugin.name)
        return servers

    def collect_anthropic_tools(
        self, ctx: PluginContext,
    ) -> tuple[list[dict[str, Any]], ToolDispatcher]:
        specs: list[ToolSpec] = []
        for plugin in self.enabled_plugins:
            try:
                specs.extend(plugin.get_tools(ctx))
            except Exception:
                logger.exception("[Plugin] %s get_tools failed", plugin.name)
        return as_anthropic_tools(specs)

    def collect_prompt_fragments(self, ctx: PluginContext) -> list[str]:
        fragments: list[str] = []
        for plugin in self.enabled_plugins:
            fragment = plugin.system_prompt_fragment(ctx)
            if fragment:
                fragments.append(fragment)
        return fragments

    def collect_cleanup_tasks(self) -> list[CleanupTask]:
        tasks: list[CleanupTask] = []
        for plugin in self.enabled_plugins:
            tasks.extend(plugin.cleanup_tasks())
        return tasks


plugin_registry = PluginRegistry()
