"""
WeChat Bot 消息处理器模块

负责：
- 调用 AgentService 或 RagAgentRunner
- 聚合 SSE 流式文本
- 处理超时和异常
"""
import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

from app.config import settings
from app.services.agent import AgentService, AgentEvent

from .message_router import RouteDecision, RouteMode
from .session import WeChatSession

if TYPE_CHECKING:
    from .adapter import WeChatBotAdapter

logger = logging.getLogger(__name__)

# Agent 服务单例
_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """获取 Agent 服务实例"""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service


class MessageProcessor:
    """
    消息处理器

    负责：
    1. 调用 Agent/RAG 服务
    2. 聚合流式响应
    3. 返回最终文本
    """

    def __init__(self):
        self._agent_service = get_agent_service()
        self._timeout_seconds = settings.wechatbot_message_timeout_seconds

    async def process(
        self,
        decision: RouteDecision,
        session: WeChatSession,
    ) -> str:
        """
        处理消息并返回回复文本

        Args:
            decision: 路由决策
            session: 微信会话

        Returns:
            str: 回复文本
        """
        try:
            async with asyncio.timeout(self._timeout_seconds):
                if decision.mode == RouteMode.HELP:
                    from .message_router import get_help_text
                    return get_help_text()

                elif decision.mode == RouteMode.STATUS:
                    from .message_router import get_status_text
                    return get_status_text(
                        conversation_id=decision.conversation_id,
                        default_mode=session.default_mode,
                    )

                elif decision.mode == RouteMode.RESET:
                    # 重置由 manager 处理，这里返回提示
                    return "好的，正在重置会话..."

                elif decision.mode == RouteMode.AGENT:
                    return await self._call_agent(decision, session)

                elif decision.mode == RouteMode.RAG:
                    return await self._call_rag(decision, session)

                else:
                    return "暂不支持该消息类型。"

        except asyncio.TimeoutError:
            logger.warning(f"消息处理超时: user_hash={session.user_id_hash}")
            return "处理超时，请稍后重试。"

        except Exception as e:
            logger.exception(f"消息处理失败: {e}")
            session.last_error = str(e)[:200]
            return "处理消息时出现错误，请稍后再试。"

    async def _call_agent(
        self,
        decision: RouteDecision,
        session: WeChatSession,
    ) -> str:
        """
        调用普通 Agent

        Args:
            decision: 路由决策
            session: 微信会话

        Returns:
            str: Agent 回复文本
        """
        if not decision.message.strip():
            return "请输入要咨询的问题。"

        # 构建 Agent 请求
        # 使用配置的默认系统提示词
        system_prompt = settings.wechatbot_agent_system_prompt

        # 收集流式文本
        full_text = []

        try:
            async for event in self._agent_service.query_stream(
                prompt=decision.message,
                conversation_id=decision.conversation_id,
                system_prompt=system_prompt,
                allowed_tools=[],  # 微信入口不开放工具调用，避免远程触发写入/命令执行。
                max_turns=10,
                space_id=decision.space_id,
            ):
                text = self._extract_text_from_event(event)
                if text:
                    full_text.append(text)

        except asyncio.TimeoutError:
            # 超时，返回已收集的部分
            if full_text:
                return self._join_text(full_text)
            raise

        return self._join_text(full_text)

    async def _call_rag(
        self,
        decision: RouteDecision,
        session: WeChatSession,
    ) -> str:
        """
        调用 RAG Agent

        Args:
            decision: 路由决策
            session: 微信会话

        Returns:
            str: RAG 回复文本（包含引用信息）
        """
        if not decision.message.strip():
            return "请输入要咨询的问题。"

        # 检查是否有 RAG scope 配置
        rag_scope = decision.rag_scope or {}

        if not any(rag_scope.values()):
            return "当前未配置知识库，无法使用 RAG 模式。请联系管理员配置 WECHATBOT_DEFAULT_RAG_SCOPE。"

        try:
            # 导入 RAG 相关模块
            from app.models.rag import RagRequestContext, RagSource, RagStreamRequest
            from app.services.rag import rag_agent_runner

            # 构建 RAG 请求
            request_id = str(uuid.uuid4())
            rag_request = RagStreamRequest(
                message=decision.message,
                conversation_id=decision.conversation_id,
            )

            # 从 rag_scope 提取来源信息
            sources = []
            if rag_scope.get("knowledgeBaseId"):
                sources.append(RagSource(
                    type="knowledge_base",
                    id=str(rag_scope["knowledgeBaseId"])
                ))
            if rag_scope.get("fileSetId"):
                sources.append(RagSource(
                    type="file_set",
                    id=str(rag_scope["fileSetId"])
                ))
            if sources:
                rag_request.sources = sources

            if rag_scope.get("knowledgeBaseName"):
                rag_request.knowledge_base_name = str(rag_scope["knowledgeBaseName"])
            if rag_scope.get("knowledgeBaseNames"):
                rag_request.knowledge_base_names = rag_scope["knowledgeBaseNames"]

            # 构建 RAG 上下文
            context = RagRequestContext(
                request_id=request_id,
                conversation_id=decision.conversation_id,
                sources=rag_request.get_sources() if rag_request.sources else [],
                top_k=settings.rag_default_top_k,
            )

            # 系统提示词
            system_prompt = settings.wechatbot_agent_system_prompt

            # 调用 RAG 流式接口
            answer_parts = []
            citations = []

            async for sse_event in rag_agent_runner.stream_claude_sdk(
                request=rag_request,
                context=context,
                request_id=request_id,
                system_prompt=system_prompt,
                allowed_tools=[],  # 微信入口不开放工具调用。
                space_id=decision.space_id,
            ):
                # 解析 SSE 事件
                event_data = self._parse_rag_sse_event(sse_event)
                if not event_data:
                    continue

                event_type = event_data.get("type")
                data = event_data.get("data", {})

                if event_type == "agent_delta":
                    # 文本增量
                    text = data.get("text", "")
                    if text:
                        answer_parts.append(text)

                elif event_type == "result":
                    # 最终结果
                    answer = data.get("answer", "")
                    if answer:
                        answer_parts = [answer]  # 替换为完整答案
                    citations = data.get("citations", [])

                elif event_type == "error":
                    # 错误
                    error_msg = data.get("message", "RAG 处理失败")
                    logger.warning(f"RAG 错误: {error_msg}")
                    return f"RAG 处理失败: {error_msg}"

            # 拼接答案
            answer = self._join_text(answer_parts)

            # 如果没有答案，返回提示
            if not answer.strip():
                return "抱歉，未能根据知识库找到相关答案。"

            # 添加引用信息
            return self._format_rag_answer_with_citations(answer, citations)

        except asyncio.TimeoutError:
            return "RAG 查询超时，请稍后重试。"
        except Exception as e:
            logger.exception(f"RAG 调用失败: {e}")
            return "RAG 处理失败，请稍后再试。"

    def _parse_rag_sse_event(self, sse_line: str) -> dict | None:
        """
        解析 RAG SSE 事件行

        Args:
            sse_line: SSE 格式的一行，如 "event: agent_delta\\ndata: {...}"

        Returns:
            dict | None: 解析后的事件数据
        """
        if not sse_line.strip():
            return None

        event_type = None
        event_data_str = None

        for line in sse_line.split("\n"):
            line = line.strip()
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                event_data_str = line[5:].strip()

        if event_type and event_data_str:
            try:
                data = json.loads(event_data_str)
                return {"type": event_type, "data": data}
            except json.JSONDecodeError:
                pass

        return None

    def _format_rag_answer_with_citations(
        self,
        answer: str,
        citations: list[dict],
    ) -> str:
        """
        格式化带引用的 RAG 答案

        Args:
            answer: 原始答案文本
            citations: 引用列表

        Returns:
            str: 格式化后的文本
        """
        if not citations:
            return answer

        # 限制引用数量（最多显示 3 条）
        display_citations = citations[:3]

        # 构建引用信息
        citation_lines = []
        for i, cit in enumerate(display_citations, 1):
            source = cit.get("source", "")
            score = cit.get("score", 0)
            if score:
                citation_lines.append(f"[{i}] {source} (相关度: {score:.2f})")
            else:
                citation_lines.append(f"[{i}] {source}")

        # 组合答案和引用
        result = answer
        if citation_lines:
            result += "\n\n📚 参考资料:\n" + "\n".join(citation_lines)

        return result

    def _extract_text_from_event(self, event: AgentEvent) -> str | None:
        """
        从 AgentEvent 中提取文本内容

        Args:
            event: Agent 事件

        Returns:
            str | None: 提取的文本，如果没有则返回 None
        """
        # content_block_delta/text_delta - 流式文本增量
        if event.type == "content_block_delta" and event.subtype == "text_delta":
            if isinstance(event.data, dict):
                return event.data.get("text", "")
            return str(event.data) if event.data else None

        # result - 最终结果
        if event.type == "result":
            if isinstance(event.data, dict):
                return event.data.get("text") or event.data.get("result", "")
            return str(event.data) if event.data else None

        # content_block - 内容块
        if event.type == "content_block":
            if isinstance(event.data, dict):
                return event.data.get("text") or event.data.get("content", "")
            return str(event.data) if event.data else None

        return None

    def _join_text(self, texts: list[str]) -> str:
        """
        将文本片段拼接为完整回复

        Args:
            texts: 文本片段列表

        Returns:
            str: 拼接后的完整文本
        """
        if not texts:
            return ""

        # 简单的拼接
        full_text = "".join(texts)

        max_chars = settings.wechatbot_max_reply_chars
        truncated = False
        if max_chars > 0 and len(full_text) > max_chars:
            full_text = full_text[:max_chars]
            truncated = True

        # 移除可能重复的句子（流式输出可能有少量重复）
        lines = full_text.split("\n")
        deduped = []
        seen = set()

        for line in lines:
            # 简单的去重逻辑
            line_stripped = line.strip()
            if line_stripped and line_stripped not in seen:
                seen.add(line_stripped)
                deduped.append(line)

        result = "\n".join(deduped)
        if truncated:
            result += "\n\n[回复过长，已截断]"
        return result


# 全局处理器单例
_message_processor: MessageProcessor | None = None


def get_message_processor() -> MessageProcessor:
    """获取消息处理器实例"""
    global _message_processor
    if _message_processor is None:
        _message_processor = MessageProcessor()
    return _message_processor
