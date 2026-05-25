"""
Agent 服务 - 核心 Claude Agent SDK 封装
"""
import json
import logging
import os
import tempfile
import uuid
import traceback
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ..config import settings
from .history import history_service
from .session import Session, session_manager
from .virtual_space import virtual_space_manager
from .docker_sandbox import docker_sandbox_runner

# 配置日志
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


def _format_exception_tree(exc: BaseException, indent: int = 0) -> str:
    """Format nested ExceptionGroup details that str(exc) hides."""
    prefix = "  " * indent
    lines = [f"{prefix}{type(exc).__name__}: {exc}"]
    nested = getattr(exc, "exceptions", None)
    if isinstance(nested, tuple):
        for index, child in enumerate(nested, start=1):
            lines.append(f"{prefix}sub-exception {index}:")
            lines.append(_format_exception_tree(child, indent + 1))
    return "\n".join(lines)


def _is_sdk_control_channel_close_race(error_detail: str) -> bool:
    """Detect Claude Agent SDK MCP control-channel close race errors."""
    return (
        "ProcessTransport is not ready for writing" in error_detail
        and "CLIConnectionError" in error_detail
    )


@dataclass
class AgentEvent:
    """Agent 事件"""
    type: str
    subtype: str | None = None
    data: Any = None
    conversation_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "subtype": self.subtype,
            "data": self.data,
            "conversationId": self.conversation_id
        }

    def to_sse(self) -> str:
        """转换为 SSE 格式"""
        return f"data: {json.dumps(self.to_dict(), ensure_ascii=False)}\n\n"


PROJECT_CLAUDE_MD_RELATIVE_PATH = ".claude/CLAUDE.md"

# 全局强制禁用写入/执行类工具（服务端安全模式），从配置读取，支持环境变量覆盖
GLOBAL_DISALLOWED_TOOLS = settings.global_disallowed_tools


def _load_project_claude_md(cwd: str | None) -> str:
    """读取项目级 .claude/CLAUDE.md，用于注入系统约束。"""
    if not cwd:
        return ""
    try:
        file_path = Path(cwd) / PROJECT_CLAUDE_MD_RELATIVE_PATH
        if not file_path.exists() or not file_path.is_file():
            return ""
        return file_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _merge_system_prompts(user_system_prompt: str | None, project_claude_md: str) -> str | None:
    """合并用户 systemPrompt 与项目级 CLAUDE.md（以项目约束为准）。"""
    project_part = (project_claude_md or "").strip()
    user_part = (user_system_prompt or "").strip()

    if not project_part and not user_part:
        return None
    if not project_part:
        return user_part
    if not user_part:
        return project_part

    return f"{user_part}\n\n---\n\n{project_part}"


class AgentService:
    """Claude Agent 服务"""

    def __init__(self):
        self._initialized = False

    async def _ensure_initialized(self):
        """确保 SDK 已初始化"""
        if self._initialized:
            return
        self._initialized = True

    async def query_stream(
        self,
        prompt: str,
        conversation_id: str | None = None,
        space_id: str | None = None,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
        max_turns: int | None = None,
        cwd: str | None = None,
        system_prompt: str | None = None,
        setting_sources: list[str] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        result_mode: str | None = None,
        mcp_servers: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        流式查询 Claude Agent

        Args:
            prompt: 用户提示词
            conversation_id: 会话ID（用于继续对话）
            space_id: 虚拟化/沙箱数据空间ID，优先于 conversation_id
            allowed_tools: 允许的工具列表
            disallowed_tools: 禁止的工具列表
            max_turns: 最大对话轮数
            cwd: 工作目录
            system_prompt: 系统提示词
            setting_sources: 设置来源
            model: 覆盖默认模型
            base_url: 覆盖默认 API URL
            api_key: 覆盖默认 API Key

        Yields:
            AgentEvent: Agent 事件
        """
        await self._ensure_initialized()

        session_id = conversation_id or str(uuid.uuid4())
        virtual_space_id = space_id or conversation_id or session_id
        virtual_space = None

        if docker_sandbox_runner.enabled or virtual_space_manager.enabled:
            virtual_space = virtual_space_manager.prepare(virtual_space_id, session_id=session_id)
            final_cwd = str(virtual_space.root)
        else:
            # 确定有效工作目录（优先级：请求传入 > 会话已有 > 按 conversationId 自动隔离）
            # SESSION_ISOLATED_WORKDIR=true 时，未传 cwd 的会话自动使用 <WORK_DIR>/sessions/<conversationId>/
            effective_cwd = cwd
            if not effective_cwd and settings.session_isolated_workdir and session_id:
                effective_cwd = str(Path(settings.work_dir) / "sessions" / session_id)

            # 自动创建工作目录（前端传入或自动隔离路径均可能不存在）
            final_cwd = effective_cwd or settings.work_dir
            Path(final_cwd).mkdir(parents=True, exist_ok=True)

        # 获取或创建会话。虚拟化模式下 cwd 是用户独立 Claude project 根目录。
        session = await session_manager.get_or_create_session(
            session_id=session_id,
            cwd=final_cwd
        )
        if virtual_space:
            await session_manager.update_session_metadata(
                session.id,
                {
                    "virtual_space_id": virtual_space.id,
                    "virtual_space_session_id": virtual_space.session_id,
                    "virtual_space_key": virtual_space_id,
                    "virtual_space_root": str(virtual_space.root),
                    "virtual_space_workspace": str(virtual_space.workspace),
                    "virtual_space_skills_dir": str(virtual_space.skills_dir),
                    "virtual_space_home": str(virtual_space.home_dir),
                },
            )

        # 构建工具配置
        # 新版 SDK 语义：[] 表示 Skills / 原生工具全开（推荐显式传 []）。
        # 请求层 None 会在进入本方法前被上层归一化为 []（与 [] 效果相同）。
        # 只有非空列表才表示白名单限制。
        tools = allowed_tools if allowed_tools is not None else []

        # 全局安全模式：强制禁用写入/执行类工具，避免在服务器落盘或执行任意命令
        effective_disallowed_tools: list[str] = []
        if disallowed_tools:
            effective_disallowed_tools.extend(disallowed_tools)
        for tool_name in GLOBAL_DISALLOWED_TOOLS:
            if tool_name not in effective_disallowed_tools:
                effective_disallowed_tools.append(tool_name)

        # 注入项目级 .claude/CLAUDE.md 作为系统约束（不写死在代码里，便于调整）
        project_claude_md = _load_project_claude_md(session.cwd or settings.work_dir)
        effective_system_prompt = _merge_system_prompts(system_prompt, project_claude_md)

        try:
            if docker_sandbox_runner.enabled:
                sandbox_output_base_url = os.getenv("CLAUDE_OUTPUT_BASE_URL", "")
                if sandbox_output_base_url and virtual_space:
                    output_base_dir = Path(os.getenv("CLAUDE_OUTPUT_DIR") or settings.work_dir).expanduser()
                    try:
                        relative_workspace = virtual_space.workspace.resolve().relative_to(
                            output_base_dir.resolve()
                        )
                        sandbox_output_base_url = (
                            sandbox_output_base_url.rstrip("/")
                            + "/"
                            + relative_workspace.as_posix()
                        )
                    except ValueError:
                        logger.warning(
                            "virtual space workspace is outside CLAUDE_OUTPUT_DIR/settings.work_dir; "
                            "keep CLAUDE_OUTPUT_BASE_URL unchanged"
                        )
                sandbox_env = {
                    "ANTHROPIC_API_KEY": api_key or settings.anthropic_api_key,
                    "ANTHROPIC_AUTH_TOKEN": api_key or settings.anthropic_auth_token,
                    "ANTHROPIC_BASE_URL": base_url or settings.anthropic_base_url,
                    "ANTHROPIC_MODEL": model or settings.anthropic_model,
                    "CLAUDE_OUTPUT_DIR": "/sandbox/workspace",
                    "CLAUDE_OUTPUT_BASE_URL": sandbox_output_base_url,
                    "AGENT_SDK_ADDITIONAL_SETTINGS_JSON": settings.agent_sdk_additional_settings_json,
                    "AGENT_SDK_PERMISSIONS_ALLOW": settings.agent_sdk_permissions_allow,
                    "AGENT_SDK_MCP_SERVERS_JSON": settings.agent_sdk_mcp_servers_json,
                    "AGENT_SDK_STRICT_MCP_CONFIG": str(settings.agent_sdk_strict_mcp_config).lower(),
                }
                for env_name in settings.sandbox_env_passthrough:
                    value = os.getenv(env_name)
                    if value is not None:
                        sandbox_env[env_name] = value
                sandbox_request = {
                    "session_id": session.id,
                    "prompt": prompt,
                    "cwd": "/sandbox",
                    "workspace": "/sandbox/workspace",
                    "allowed_tools": tools,
                    "disallowed_tools": effective_disallowed_tools,
                    "max_turns": max_turns,
                    "system_prompt": effective_system_prompt,
                    "setting_sources": setting_sources,
                    "model": model,
                    "base_url": base_url,
                    "api_key": api_key,
                    "result_mode": result_mode,
                    "metadata": session.metadata,
                    "env": sandbox_env,
                }
                async for raw_event in docker_sandbox_runner.run(
                    session_id=session.id,
                    sandbox_root=virtual_space.root,
                    sandbox_home=virtual_space.home_dir,
                    request=sandbox_request,
                ):
                    if raw_event.get("type") == "__sandbox_metadata":
                        metadata = raw_event.get("data") or {}
                        metadata = dict(metadata)

                        # Compatibility guard for older sandbox images: they
                        # may report container-only /sandbox paths under
                        # host-side virtual_space_* metadata keys. Preserve the
                        # host paths that were prepared before launching Docker.
                        for key in (
                            "virtual_space_root",
                            "virtual_space_workspace",
                            "virtual_space_skills_dir",
                            "virtual_space_home",
                        ):
                            value = str(metadata.get(key, ""))
                            if value == "/sandbox" or value.startswith("/sandbox/"):
                                metadata.pop(key, None)

                        await session_manager.update_session_metadata(session.id, metadata)
                        continue
                    yield AgentEvent(
                        type=raw_event.get("type", "stream_event"),
                        subtype=raw_event.get("subtype"),
                        data=raw_event.get("data"),
                        conversation_id=raw_event.get("conversationId") or session.id,
                    )
                return

            # 尝试导入 claude_agent_sdk
            sdk_available = find_spec("claude_agent_sdk") is not None

            if sdk_available:
                # 使用 Claude Agent SDK
                async for event in self._query_with_sdk(
                    prompt=prompt,
                    session=session,
                    allowed_tools=tools,
                    disallowed_tools=effective_disallowed_tools,
                    max_turns=max_turns,
                    system_prompt=effective_system_prompt,
                    setting_sources=setting_sources,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    result_mode=result_mode,
                    mcp_servers=mcp_servers,
                ):
                    yield event
            else:
                # SDK 不可用时的降级处理
                yield AgentEvent(
                    type="error",
                    data={"message": "claude_agent_sdk not installed. Please install: pip install claude-agent-sdk"},
                    conversation_id=session.id
                )

        except Exception as e:
            yield AgentEvent(
                type="error",
                data={"message": str(e)},
                conversation_id=session.id
            )

    async def _query_with_sdk(
        self,
        prompt: str,
        session: Session,
        allowed_tools: list[str],
        disallowed_tools: list[str] | None,
        max_turns: int | None,
        system_prompt: str | None = None,
        setting_sources: list[str] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        result_mode: str | None = None,
        mcp_servers: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """使用 Claude Agent SDK 执行查询"""
        from claude_agent_sdk import ClaudeAgentOptions, query

        # 发送开始事件
        yield AgentEvent(
            type="stream_event",
            subtype="start",
            data={"message": "Query started"},
            conversation_id=session.id
        )

        # 确定有效的配置（请求级别覆盖 > 环境配置）
        effective_api_key = api_key or settings.anthropic_api_key
        effective_base_url = base_url or settings.anthropic_base_url
        effective_model = model or settings.anthropic_model

        # 构建环境变量，传递 API 配置
        # 继承当前进程的所有环境变量
        env = dict(os.environ)
        # 避免 Claude Code CLI 在 macOS 上对 VS Code 的 IPC socket / named pipe 做 fs.watch 导致崩溃
        # macOS 不支持对命名管道 (named pipe/FIFO) 进行文件系统监视，会抛出 EOPNOTSUPP 错误
        env.pop("VSCODE_GIT_IPC_HANDLE", None)
        env.pop("VSCODE_IPC_HOOK", None)
        env.pop("VSCODE_IPC_HOOK_CLI", None)
        env.pop("VSCODE_IPC_HOOK_EXTHOST", None)
        # 移除 Electron 相关环境变量，避免 Claude Code CLI 继承 VS Code 的 Electron 上下文
        # 这可能导致 CLI 错误地尝试监视 CEF (Chromium Embedded Framework) 的 socket 文件
        env.pop("ELECTRON_RUN_AS_NODE", None)
        env.pop("ELECTRON_NO_ASAR", None)
        # 强制使用轮询模式进行文件监视，避免 macOS 对特殊文件类型的 fs.watch 限制
        env["CHOKIDAR_USEPOLLING"] = "true"
        env["WATCHPACK_POLLING"] = "true"
        # 使用独立的临时目录，避免与 VS Code/CEF 的 socket 文件冲突
        # 这可以防止 Claude Code CLI 意外扫描到 CEF 创建的 client_pipe_* 文件
        claude_tmp_dir = os.path.join(tempfile.gettempdir(), "claude_agent_sdk")
        os.makedirs(claude_tmp_dir, exist_ok=True)
        env["TMPDIR"] = claude_tmp_dir
        env["TEMP"] = claude_tmp_dir
        env["TMP"] = claude_tmp_dir

        # 覆盖 API 配置
        if effective_api_key:
            env["ANTHROPIC_API_KEY"] = effective_api_key
            env["ANTHROPIC_AUTH_TOKEN"] = effective_api_key
        if effective_base_url:
            env["ANTHROPIC_BASE_URL"] = effective_base_url
        if effective_model:
            env["ANTHROPIC_MODEL"] = effective_model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = effective_model
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = effective_model
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = effective_model

        # 动态注入会话级 CLAUDE_OUTPUT_DIR，实现 Skill 文件输出隔离。
        # 虚拟化模式下产物固定落在虚拟空间 workspace/，避免写入复制出的应用/skills。
        virtual_workspace = session.metadata.get("virtual_space_workspace")
        base_output_dir = env.get("CLAUDE_OUTPUT_DIR", "")
        if virtual_workspace:
            session_output_dir = str(Path(virtual_workspace))
            Path(session_output_dir).mkdir(parents=True, exist_ok=True)
            env["CLAUDE_OUTPUT_DIR"] = session_output_dir

            base_output_url = env.get("CLAUDE_OUTPUT_BASE_URL", "")
            url_base_dir = Path(base_output_dir or settings.work_dir).expanduser()
            try:
                relative_output = Path(session_output_dir).resolve().relative_to(url_base_dir.resolve())
                if base_output_url:
                    if relative_output.as_posix() == ".":
                        env["CLAUDE_OUTPUT_BASE_URL"] = base_output_url.rstrip("/")
                    else:
                        env["CLAUDE_OUTPUT_BASE_URL"] = (
                            base_output_url.rstrip("/") + "/" + relative_output.as_posix()
                        )
            except ValueError:
                if base_output_url:
                    logger.warning(
                        "CLAUDE_OUTPUT_DIR is outside URL base; keep CLAUDE_OUTPUT_BASE_URL unchanged"
                    )
        elif base_output_dir and session.id:
            session_output_dir = str(Path(base_output_dir) / session.id)
            Path(session_output_dir).mkdir(parents=True, exist_ok=True)
            env["CLAUDE_OUTPUT_DIR"] = session_output_dir
            # 同步追加 session.id 到 BASE_URL，保证 Skill 拼出的展示 URL 与文件路径一致
            base_output_url = env.get("CLAUDE_OUTPUT_BASE_URL", "")
            if base_output_url:
                env["CLAUDE_OUTPUT_BASE_URL"] = base_output_url.rstrip("/") + "/" + session.id

        # 调试日志
        logger.info("="*50)
        logger.info("Agent SDK 配置信息:")
        logger.info(f"  prompt: {prompt[:100]}...")
        logger.info(f"  system_prompt: {system_prompt[:200] if system_prompt else 'None'}...")
        logger.info(f"  allowed_tools: {allowed_tools}")
        logger.info(f"  disallowed_tools: {disallowed_tools}")
        logger.info(f"  effective_api_key: {'set' if effective_api_key else 'None'}")
        logger.info(f"  effective_base_url: {effective_base_url}")
        logger.info(f"  effective_model: {effective_model}")
        logger.info(f"  work_dir: {settings.work_dir}")
        logger.info("="*50)

        # 构建选项
        # setting_sources 控制配置加载
        # - "project": {cwd}/.claude/ 配置（加载 skills）
        # - 空列表: 不加载任何配置文件，仅使用 --settings 参数
        # 注意：当同时有 --setting-sources 和 --settings 时，文件配置可能覆盖 --settings
        # 默认使用 ["project"] 以加载 skills，但需确保 .claude/settings.json 中有 skipWebFetchPreflight
        effective_setting_sources = setting_sources if setting_sources is not None else ["project"]

        # 代码注入：附加 settings（permissions 等）与 MCP servers
        injected_settings: dict[str, Any] = {}
        if settings.agent_sdk_additional_settings_json:
            try:
                parsed = json.loads(settings.agent_sdk_additional_settings_json)
                if isinstance(parsed, dict):
                    injected_settings = parsed
                else:
                    logger.warning("AGENT_SDK_ADDITIONAL_SETTINGS_JSON must be a JSON object")
            except Exception as e:
                logger.warning(f"Invalid AGENT_SDK_ADDITIONAL_SETTINGS_JSON: {e}")

        if settings.agent_sdk_permissions_allow:
            allow_items = [
                item.strip()
                for item in settings.agent_sdk_permissions_allow.split(",")
                if item.strip()
            ]
            if allow_items:
                perms = injected_settings.setdefault("permissions", {})
                if not isinstance(perms, dict):
                    perms = {}
                    injected_settings["permissions"] = perms
                existing_allow = perms.get("allow", [])
                if not isinstance(existing_allow, list):
                    existing_allow = []
                # 去重但保持顺序
                combined = list(existing_allow)
                for item in allow_items:
                    if item not in combined:
                        combined.append(item)
                perms["allow"] = combined

        injected_settings_str = (
            json.dumps(injected_settings, ensure_ascii=False)
            if injected_settings
            else None
        )

        # 调试日志：确认 settings 注入情况
        logger.info(f"[Settings Injection] agent_sdk_additional_settings_json: {settings.agent_sdk_additional_settings_json}")
        logger.info(f"[Settings Injection] injected_settings: {injected_settings}")
        logger.info(f"[Settings Injection] injected_settings_str: {injected_settings_str}")
        logger.info(f"[Settings Injection] setting_sources: {effective_setting_sources}")

        injected_mcp_servers: Any = None
        if settings.agent_sdk_mcp_servers_json:
            try:
                parsed = json.loads(settings.agent_sdk_mcp_servers_json)
                if isinstance(parsed, dict) and "mcpServers" in parsed and isinstance(parsed["mcpServers"], dict):
                    injected_mcp_servers = parsed["mcpServers"]
                else:
                    injected_mcp_servers = parsed
            except Exception as e:
                logger.warning(f"Invalid AGENT_SDK_MCP_SERVERS_JSON: {e}")

        effective_mcp_servers: dict[str, Any] = {}
        if isinstance(injected_mcp_servers, dict):
            effective_mcp_servers.update(injected_mcp_servers)
        if mcp_servers:
            effective_mcp_servers.update(mcp_servers)

        extra_args: dict[str, str | None] = {}
        if settings.agent_sdk_strict_mcp_config:
            extra_args["strict-mcp-config"] = None

        # 收集 CLI stderr，用于错误诊断
        stderr_lines: list[str] = []

        def stderr_callback(msg: str) -> None:
            logger.error(f"[CLI stderr] {msg}")
            stderr_lines.append(msg)

        include_partial_messages = not bool(effective_mcp_servers)
        logger.info(
            "[ClaudeAgentOptions] include_partial_messages=%s (mcp_servers=%s)",
            include_partial_messages,
            list(effective_mcp_servers.keys()),
        )

        sdk_allowed_tools = allowed_tools if allowed_tools is not None else []
        logger.info("[ClaudeAgentOptions] sdk_allowed_tools=%s", sdk_allowed_tools)

        options = ClaudeAgentOptions(
            cwd=session.cwd or settings.work_dir,
            allowed_tools=sdk_allowed_tools,
            disallowed_tools=disallowed_tools or [],
            setting_sources=effective_setting_sources,
            env=env,
            model=effective_model,
            # 权限模式：bypassPermissions 跳过交互式权限确认
            permission_mode="bypassPermissions",
            # 关键：开启 partial messages，Claude Code CLI 才会输出逐 token 的 stream_event。
            # 但 SDK MCP server 依赖双向 control channel；partial streaming 在 MCP 场景下
            # 容易与 close/cancel 时序冲突，导致 ProcessTransport is not ready for writing。
            include_partial_messages=include_partial_messages,
            settings=injected_settings_str,
            mcp_servers=effective_mcp_servers,
            extra_args=extra_args,
            stderr=stderr_callback,
        )

        # 打印完整的 options 用于调试
        logger.info(f"[ClaudeAgentOptions] settings={options.settings}")
        logger.info(f"[ClaudeAgentOptions] setting_sources={options.setting_sources}")

        effective_result_mode = (
            (result_mode or settings.agent_sdk_stream_result_mode or "full")
            .strip()
            .lower()
        )
        if effective_result_mode not in ("full", "empty", "none"):
            logger.warning(
                f"Unknown result_mode '{effective_result_mode}', fallback to 'full'"
            )
            effective_result_mode = "full"

        if max_turns:
            options.max_turns = max_turns

        if system_prompt:
            # 使用 preset + append 方式，保留 Claude Code 的基本能力
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt,
            }

        # 如果有会话ID，先修复可能损坏的 .jsonl，再恢复
        if session.metadata.get("resume_id"):
            resume_id = session.metadata["resume_id"]
            result = history_service.repair_session(resume_id)
            if result.get("error") == "file not found":
                session.metadata["resume_id"] = None
                await session_manager.update_session_metadata(session.id, {"resume_id": None})
                logger.warning(
                    "[resume] 找不到 Claude 历史文件，已清除失效 resume_id=%s，本次请求将创建新 Claude session",
                    resume_id,
                )
            else:
                if result["repaired"]:
                    logger.warning(f"[resume] 修复损坏历史 resume_id={resume_id}, patched={result['patched_count']}")
                options.resume = resume_id

        # 最终调试日志：确认传给 query() 的 options
        logger.info(f"[FINAL] options.settings = {options.settings}")
        logger.info(f"[FINAL] options.setting_sources = {options.setting_sources}")
        logger.info(f"[FINAL] options.cwd = {options.cwd}")

        result_text = ""
        streamed_any_text_delta = False
        streamed_any_thinking_delta = False

        try:
            async for message in query(prompt=prompt, options=options):
                # 通过类名判断消息类型
                msg_class = type(message).__name__
                logger.debug(f"Received message: {msg_class}")

                if msg_class == "StreamEvent":
                    raw_event = getattr(message, "event", None)
                    if not isinstance(raw_event, dict):
                        continue

                    # Claude Code CLI 透传的 Anthropic Messages API stream events
                    # 重点处理 text_delta / thinking_delta，其余事件按需扩展
                    if raw_event.get("type") == "content_block_delta":
                        delta = raw_event.get("delta") or {}
                        if isinstance(delta, dict):
                            delta_type = delta.get("type")
                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    streamed_any_text_delta = True
                                    if effective_result_mode == "full":
                                        result_text += text
                                    yield AgentEvent(
                                        type="content_block_delta",
                                        subtype="text_delta",
                                        data={"text": text},
                                        conversation_id=session.id
                                    )
                            elif delta_type == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                if thinking:
                                    streamed_any_thinking_delta = True
                                    yield AgentEvent(
                                        type="content_block_delta",
                                        subtype="thinking_delta",
                                        data={"thinking": thinking},
                                        conversation_id=session.id
                                    )
                            elif delta_type == "signature_delta":
                                signature = delta.get("signature", "")
                                if signature:
                                    yield AgentEvent(
                                        type="content_block_delta",
                                        subtype="signature_delta",
                                        data={"signature": signature},
                                        conversation_id=session.id
                                    )
                    continue

                if msg_class == "AssistantMessage":
                    # 处理助手消息
                    content = getattr(message, "content", [])
                    for block in content:
                        block_type = type(block).__name__
                        if block_type == "TextBlock":
                            # 开启 partial messages 后，TextBlock 会在消息完成时一次性返回全文，
                            # 若已通过 StreamEvent 输出过 text_delta，则跳过以避免重复
                            if streamed_any_text_delta:
                                continue
                            text = getattr(block, "text", "")
                            if effective_result_mode == "full":
                                result_text += text
                            yield AgentEvent(
                                type="content_block_delta",
                                subtype="text_delta",
                                data={"text": text},
                                conversation_id=session.id
                            )
                        elif block_type == "ThinkingBlock":
                            # thinking 块：若已通过 StreamEvent 输出过 thinking_delta，则跳过以避免重复
                            if streamed_any_thinking_delta:
                                continue
                            thinking = getattr(block, "thinking", "")
                            signature = getattr(block, "signature", "")
                            if thinking or signature:
                                yield AgentEvent(
                                    type="content_block_delta",
                                    subtype="thinking",
                                    data={
                                        "thinking": thinking,
                                        "signature": signature,
                                    },
                                    conversation_id=session.id
                                )
                        elif block_type == "ToolUseBlock":
                            yield AgentEvent(
                                type="content_block_delta",
                                subtype="tool_use",
                                data={
                                    "name": getattr(block, "name", ""),
                                    "input": getattr(block, "input", {})
                                },
                                conversation_id=session.id
                            )

                elif msg_class == "ResultMessage":
                    # 处理结果
                    subtype = getattr(message, "subtype", None)
                    if subtype == "success":
                        result = getattr(message, "result", "")
                        session_id = getattr(message, "session_id", None)

                        # 保存 session_id 用于后续恢复（file 模式下同步写盘）
                        if session_id:
                            session.metadata["resume_id"] = session_id
                            await session_manager.update_session_metadata(
                                session.id, {"resume_id": session_id}
                            )

                        if effective_result_mode == "none":
                            yield AgentEvent(
                                type="stream_event",
                                subtype="end",
                                data={"message": "Query finished"},
                                conversation_id=session.id
                            )
                        elif effective_result_mode == "empty":
                            yield AgentEvent(
                                type="result",
                                subtype="success",
                                data={"result": ""},
                                conversation_id=session.id
                            )
                        else:
                            yield AgentEvent(
                                type="result",
                                subtype="success",
                                data={"result": result or result_text},
                                conversation_id=session.id
                            )
                    else:
                        is_error = getattr(message, "is_error", False)
                        result = getattr(message, "result", "Unknown error")
                        yield AgentEvent(
                            type="result",
                            subtype="error" if is_error else "success",
                            data={"error" if is_error else "result": result},
                            conversation_id=session.id
                        )

                elif msg_class == "SystemMessage":
                    # 系统消息，透传
                    yield AgentEvent(
                        type="stream_event",
                        subtype=getattr(message, "subtype", "system"),
                        data=getattr(message, "data", {}),
                        conversation_id=session.id
                    )

                else:
                    # 其他消息类型
                    yield AgentEvent(
                        type="stream_event",
                        subtype=msg_class.lower(),
                        data={"raw": str(message)},
                        conversation_id=session.id
                    )

        except Exception as e:
            error_detail = _format_exception_tree(e)
            error_detail += "\n[Traceback]\n" + "".join(
                traceback.format_exception(type(e), e, e.__traceback__)
            )
            if stderr_lines:
                error_detail += "\n[CLI stderr]\n" + "\n".join(stderr_lines)
            logger.error(f"[_query_with_sdk] error: {error_detail}")

            # Claude Agent SDK can raise from query.close() after MCP control responses
            # if the subprocess transport has already closed. Do not surface that race
            # as a fatal user error when useful output was already produced.
            if _is_sdk_control_channel_close_race(error_detail):
                logger.warning(
                    "[_query_with_sdk] SDK control channel close race detected; "
                    "streamed_any_text_delta=%s result_text_len=%s",
                    streamed_any_text_delta,
                    len(result_text),
                )
                if streamed_any_text_delta or result_text:
                    yield AgentEvent(
                        type="stream_event",
                        subtype="end",
                        data={
                            "message": "Query completed; ignored SDK control channel close race",
                            "sdkCloseRaceIgnored": True,
                        },
                        conversation_id=session.id,
                    )
                    return

                yield AgentEvent(
                    type="error",
                    data={
                        "message": "Claude Agent SDK control channel closed before MCP control response was written.",
                        "code": "sdk_control_channel_close_race",
                        "recoverable": True,
                        "detail": error_detail,
                    },
                    conversation_id=session.id,
                )
                return

            # 历史会话损坏（工具调用中断导致 tool_calls 无对应 tool_result）时，
            # 清除 resume_id 让下次请求以新 session 启动，conversationId 保持不变。
            # 历史 .jsonl 文件仍保留在磁盘，本次对话上下文丢失但 conversationId 可继续使用。
            if "tool_call_ids did not have response messages" in error_detail and session.metadata.get("resume_id"):
                old_resume_id = session.metadata["resume_id"]
                await session_manager.update_session_metadata(session.id, {"resume_id": None})
                logger.warning(f"[_query_with_sdk] 历史会话损坏，已清除 resume_id={old_resume_id}，下次请求将以新 session 继续")
                yield AgentEvent(
                    type="error",
                    data={
                        "message": "历史会话因上次中断损坏，已自动重置。请重新发送消息，对话可继续（历史上下文已丢失）。",
                        "code": "corrupted_session_reset",
                    },
                    conversation_id=session.id
                )
            else:
                yield AgentEvent(
                    type="error",
                    data={"message": error_detail},
                    conversation_id=session.id
                )

    async def query(
        self,
        prompt: str,
        conversation_id: str | None = None,
        space_id: str | None = None,
        allowed_tools: list[str] | None = None,
        disallowed_tools: list[str] | None = None,
        max_turns: int | None = None,
        cwd: str | None = None,
        system_prompt: str | None = None,
        setting_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        非流式查询 Claude Agent

        Returns:
            dict: 包含 success, result, conversation_id, error 的字典
        """
        result_text = ""
        final_conversation_id = conversation_id
        error_message = None

        async for event in self.query_stream(
            prompt=prompt,
            conversation_id=conversation_id,
            space_id=space_id,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            max_turns=max_turns,
            cwd=cwd,
            system_prompt=system_prompt,
            setting_sources=setting_sources
        ):
            if event.conversation_id:
                final_conversation_id = event.conversation_id

            if event.type == "content_block_delta" and event.subtype == "text_delta":
                result_text += event.data.get("text", "")
            elif event.type == "result":
                if event.subtype == "success":
                    result_text = event.data.get("result", result_text)
                else:
                    error_message = event.data.get("error")
            elif event.type == "error":
                error_message = event.data.get("message")

        if error_message:
            return {
                "success": False,
                "result": None,
                "conversationId": final_conversation_id,
                "error": error_message
            }

        return {
            "success": True,
            "result": result_text,
            "conversationId": final_conversation_id,
            "error": None
        }


# 全局 Agent 服务实例
agent_service = AgentService()
