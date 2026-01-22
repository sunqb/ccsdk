"""
Agent 服务 - 核心 Claude Agent SDK 封装
"""
import asyncio
import json
import logging
import os
import tempfile
from typing import Optional, Any, AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .session import session_manager, Session

# 配置日志
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


@dataclass
class AgentEvent:
    """Agent 事件"""
    type: str
    subtype: Optional[str] = None
    data: Any = None
    conversation_id: Optional[str] = None

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

# 全局强制禁用写入/执行类工具（服务端安全模式）
GLOBAL_DISALLOWED_TOOLS = ["Write", "Bash"]


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
        conversation_id: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
        disallowed_tools: Optional[list[str]] = None,
        max_turns: Optional[int] = None,
        cwd: Optional[str] = None,
        system_prompt: Optional[str] = None,
        setting_sources: Optional[list[str]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        result_mode: Optional[str] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        流式查询 Claude Agent

        Args:
            prompt: 用户提示词
            conversation_id: 会话ID（用于继续对话）
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

        # 获取或创建会话
        session = await session_manager.get_or_create_session(
            session_id=conversation_id,
            cwd=cwd or settings.work_dir
        )

        # 构建工具配置
        # None 表示使用 SDK 默认工具集（完整工具）
        # 空列表或明确指定的列表则使用用户指定的
        tools = allowed_tools

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
            # 尝试导入 claude_agent_sdk
            try:
                from claude_agent_sdk import query, ClaudeAgentOptions
                sdk_available = True
            except ImportError:
                sdk_available = False

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
        disallowed_tools: Optional[list[str]],
        max_turns: Optional[int],
        system_prompt: Optional[str] = None,
        setting_sources: Optional[list[str]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        result_mode: Optional[str] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """使用 Claude Agent SDK 执行查询"""
        from claude_agent_sdk import query, ClaudeAgentOptions

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
        # 默认只加载项目配置
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

        extra_args: dict[str, str | None] = {}
        if settings.agent_sdk_strict_mcp_config:
            extra_args["strict-mcp-config"] = None

        options = ClaudeAgentOptions(
            cwd=session.cwd or settings.work_dir,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools or [],
            setting_sources=effective_setting_sources,
            env=env,
            model=effective_model,
            # 权限模式：bypassPermissions 跳过交互式权限确认
            permission_mode="bypassPermissions",
            # 关键：开启 partial messages，Claude Code CLI 才会输出逐 token 的 stream_event
            # 否则 SDK 只会在 AssistantMessage 完整生成后一次性返回 TextBlock，导致“假流式”
            include_partial_messages=True,
            settings=injected_settings_str,
            mcp_servers=injected_mcp_servers or {},
            extra_args=extra_args,
        )

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

        # 如果有会话ID，尝试恢复
        if session.metadata.get("resume_id"):
            options.resume = session.metadata["resume_id"]

        result_text = ""
        streamed_any_text_delta = False

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
                    # 重点处理 text_delta，其余事件按需扩展
                    if raw_event.get("type") == "content_block_delta":
                        delta = raw_event.get("delta") or {}
                        if isinstance(delta, dict) and delta.get("type") == "text_delta":
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

                        # 保存 session_id 用于后续恢复
                        if session_id:
                            session.metadata["resume_id"] = session_id

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
            yield AgentEvent(
                type="error",
                data={"message": str(e)},
                conversation_id=session.id
            )

    async def query(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
        disallowed_tools: Optional[list[str]] = None,
        max_turns: Optional[int] = None,
        cwd: Optional[str] = None,
        system_prompt: Optional[str] = None,
        setting_sources: Optional[list[str]] = None,
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
