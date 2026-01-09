"""
Agent 服务 - 核心 Claude Agent SDK 封装
"""
import asyncio
import json
import logging
from typing import Optional, Any, AsyncGenerator
from dataclasses import dataclass

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
                    disallowed_tools=disallowed_tools,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    setting_sources=setting_sources,
                    model=model,
                    base_url=base_url,
                    api_key=api_key
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
        api_key: Optional[str] = None
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
        import os
        env = dict(os.environ)

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
        logger.info(f"  effective_api_key: {effective_api_key[:20] if effective_api_key else 'None'}...")
        logger.info(f"  effective_base_url: {effective_base_url}")
        logger.info(f"  effective_model: {effective_model}")
        logger.info(f"  work_dir: {settings.work_dir}")
        logger.info("="*50)

        # 构建选项
        # setting_sources 控制配置加载
        # - "project": {cwd}/.claude/ 配置（加载 skills）
        # 默认只加载项目配置
        effective_setting_sources = setting_sources if setting_sources is not None else ["project"]
        options = ClaudeAgentOptions(
            cwd=session.cwd or settings.work_dir,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools or [],
            setting_sources=effective_setting_sources,
            env=env,
            model=effective_model,
            # 权限模式：bypassPermissions 跳过交互式权限确认
            permission_mode="bypassPermissions",
        )

        if max_turns:
            options.max_turns = max_turns

        if system_prompt:
            # 使用 preset + append 方式，保留 Claude Code 的基本能力
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt
            }

        # 如果有会话ID，尝试恢复
        if session.metadata.get("resume_id"):
            options.resume = session.metadata["resume_id"]

        result_text = ""

        try:
            async for message in query(prompt=prompt, options=options):
                # 通过类名判断消息类型
                msg_class = type(message).__name__
                logger.debug(f"Received message: {msg_class}")

                if msg_class == "AssistantMessage":
                    # 处理助手消息
                    content = getattr(message, "content", [])
                    for block in content:
                        block_type = type(block).__name__
                        if block_type == "TextBlock":
                            text = getattr(block, "text", "")
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
