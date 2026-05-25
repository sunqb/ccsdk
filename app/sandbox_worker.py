"""
容器内 Agent worker。

宿主进程通过 stdin 传入 JSON 请求，本进程逐行输出 AgentEvent JSON。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from .config import settings
from .services.agent import AgentService
from .services.session import Session


def _emit(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


async def _main() -> int:
    raw = sys.stdin.readline()
    if not raw:
        _emit({
            "type": "error",
            "subtype": None,
            "data": {"message": "Missing sandbox request"},
            "conversationId": None,
        })
        return 2

    request = json.loads(raw)
    session_id = request["session_id"]
    sandbox_cwd = request.get("cwd") or "/sandbox"
    workspace = request.get("workspace") or "/sandbox/workspace"
    Path(workspace).mkdir(parents=True, exist_ok=True)

    settings.work_dir = workspace
    settings.skills_dir = "/sandbox/.claude/skills"
    settings.virtual_space_enabled = False
    settings.sandbox_enabled = False

    env = request.get("env") or {}
    for key, value in env.items():
        if value is not None:
            os.environ[str(key)] = str(value)

    settings.anthropic_api_key = env.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key
    settings.anthropic_auth_token = env.get("ANTHROPIC_AUTH_TOKEN") or settings.anthropic_auth_token
    settings.anthropic_base_url = env.get("ANTHROPIC_BASE_URL") or settings.anthropic_base_url
    settings.anthropic_model = env.get("ANTHROPIC_MODEL") or settings.anthropic_model
    settings.agent_sdk_additional_settings_json = env.get(
        "AGENT_SDK_ADDITIONAL_SETTINGS_JSON"
    )
    settings.agent_sdk_permissions_allow = env.get("AGENT_SDK_PERMISSIONS_ALLOW")
    settings.agent_sdk_mcp_servers_json = env.get("AGENT_SDK_MCP_SERVERS_JSON")
    settings.agent_sdk_strict_mcp_config = (
        env.get("AGENT_SDK_STRICT_MCP_CONFIG", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )

    session = Session(
        id=session_id,
        cwd=sandbox_cwd,
        metadata=request.get("metadata") or {},
    )
    # Keep host-side virtual_space_* metadata intact. The worker only knows
    # container paths, so expose them under sandbox_* keys instead.
    session.metadata["sandbox_workspace"] = workspace

    service = AgentService()
    async for event in service._query_with_sdk(
        prompt=request["prompt"],
        session=session,
        allowed_tools=request.get("allowed_tools"),
        disallowed_tools=request.get("disallowed_tools"),
        max_turns=request.get("max_turns"),
        system_prompt=request.get("system_prompt"),
        setting_sources=request.get("setting_sources"),
        model=request.get("model"),
        base_url=request.get("base_url"),
        api_key=request.get("api_key"),
        result_mode=request.get("result_mode"),
    ):
        _emit(event.to_dict())

    _emit({
        "type": "__sandbox_metadata",
        "subtype": None,
        "data": session.metadata,
        "conversationId": session_id,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
