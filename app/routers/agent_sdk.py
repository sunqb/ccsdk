"""
Agent SDK API 路由 - 兼容原 cc-agent-sdk API
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Optional

from ..models.request import StreamRequest, HistoryRequest
from ..services.agent import agent_service
from ..services.history import history_service
from ..services.session import session_manager
from ..auth import verify_api_key
from ..config import settings

router = APIRouter(prefix="/agent-sdk", tags=["Agent SDK"])


async def _generate_sse_stream(
    prompt: str,
    conversation_id: Optional[str],
    allowed_tools: Optional[list[str]],
    disallowed_tools: Optional[list[str]],
    max_turns: Optional[int],
    system_prompt: Optional[str],
    setting_sources: Optional[list[str]],
    cwd: Optional[str],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    result_mode: Optional[str] = None,
    event_mode: str = "full",
) -> AsyncGenerator[str, None]:
    """生成 SSE 事件流"""
    # 默认工具列表：空列表表示使用 SDK 默认工具（完整工具集）
    # 如果用户明确传递 ["Skill"]，则只允许 Skill
    tools = allowed_tools if allowed_tools is not None else None

    effective_event_mode = (event_mode or "full").strip().lower()
    if effective_event_mode not in ("full", "text_only"):
        effective_event_mode = "full"

    async for event in agent_service.query_stream(
        prompt=prompt,
        conversation_id=conversation_id,
        allowed_tools=tools,
        disallowed_tools=disallowed_tools,
        max_turns=max_turns,
        system_prompt=system_prompt,
        setting_sources=setting_sources,
        cwd=cwd,
        model=model,
        base_url=base_url,
        api_key=api_key,
        result_mode=result_mode,
    ):
        if effective_event_mode == "full":
            yield event.to_sse()
            continue

        # text_only：仅输出 text_delta，并保留 end/error 作为结束与异常信号
        if event.type == "content_block_delta" and event.subtype == "text_delta":
            yield event.to_sse()
        elif event.type == "stream_event" and event.subtype == "end":
            yield event.to_sse()
        elif event.type == "error":
            yield event.to_sse()


@router.post("/stream", dependencies=[Depends(verify_api_key)])
async def agent_sdk_stream(request: StreamRequest):
    """
    Agent SDK 流式端点 - 兼容原 cc-agent-sdk API

    接收用户消息，返回 text/event-stream，逐步推送 Claude Agent SDK 原始事件：
    - stream_event: 流事件
    - content_block_delta: 内容增量
    - assistant: 助手消息
    - result: 最终结果
    - error: 错误信息

    **请求参数:**
    - prompt/userMessage: 用户消息（二选一）
    - conversationId: 会话ID，映射到 cc 的 resume；不传则创建新会话
    - model: 可选，覆盖默认模型
    - baseURL: 可选，覆盖默认 API URL
    - apiKey: 可选，覆盖默认 API Key
    - options: 透传给 claude-agent-sdk 的选项
      - allowedTools (默认 ["Skill"])
      - disallowedTools
      - tools
      - maxTurns
    - systemPrompt: 系统提示词
    - settingSources: 设置来源，默认 ["user", "project"]
    - cwd: 工作目录
    """
    # 获取有效的 prompt
    prompt = request.get_prompt()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing userMessage (or provide a raw prompt)")

    # 从 options 中提取参数
    allowed_tools = None
    disallowed_tools = None
    max_turns = None

    if request.options:
        allowed_tools = request.options.allowed_tools
        disallowed_tools = request.options.disallowed_tools
        max_turns = request.options.max_turns

    # 处理 systemPrompt
    system_prompt = None
    if request.system_prompt:
        if isinstance(request.system_prompt, str):
            system_prompt = request.system_prompt
        elif isinstance(request.system_prompt, dict):
            # 预设配置，转换为字符串
            system_prompt = str(request.system_prompt)

    event_mode = (request.event_mode or settings.agent_sdk_stream_event_mode or "full").strip().lower()
    if event_mode not in ("full", "text_only"):
        event_mode = "full"

    # text_only 模式：默认不输出最终 result 全量（避免重复/浪费带宽）
    result_mode = request.result_mode
    if event_mode == "text_only":
        result_mode = "none"

    return StreamingResponse(
        _generate_sse_stream(
            prompt=prompt,
            conversation_id=request.conversation_id,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            max_turns=max_turns,
            system_prompt=system_prompt,
            setting_sources=request.setting_sources,
            cwd=request.cwd,
            model=request.model,
            base_url=request.base_url,
            api_key=request.api_key,
            result_mode=result_mode,
            event_mode=event_mode,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/history", dependencies=[Depends(verify_api_key)])
async def get_history(
    conversation_id: str = Query(
        ...,
        alias="conversationId",
        description="会话ID（文件名）"
    ),
    offset: int = Query(0, description="起始消息序号"),
    limit: int = Query(200, description="返回消息数量"),
    include_thinking: bool = Query(
        False,
        alias="includeThinking",
        description="是否包含 thinking 块"
    ),
    raw: bool = Query(False, description="是否返回完整事件数组")
):
    """
    历史记录查询端点

    读取 ~/.claude/projects/<project>/<conversationId>.jsonl 中的会话数据

    **查询参数:**
    - conversationId: 必填，会话ID（文件名）
    - offset: 可选，起始消息序号（默认 0）
    - limit: 可选，返回消息数量（默认 200）
    - includeThinking: 可选，是否包含 thinking 块（默认 false）
    - raw: 可选，返回完整事件数组（默认 false）
    """
    result = history_service.get_history(
        conversation_id=conversation_id,
        offset=offset,
        limit=limit,
        include_thinking=include_thinking,
        raw=raw
    )

    # 兼容：若用户传入的是本服务的 conversationId（内存会话ID），尝试映射到 Claude Code 的 session_id
    # 注意：该映射依赖进程内存；服务重启后需要直接使用 Claude Code 的 session_id（.jsonl 文件名）
    if result.get("error") == "Conversation not found":
        session = await session_manager.get_session(conversation_id)
        resume_id = session.metadata.get("resume_id") if session else None
        if isinstance(resume_id, str) and resume_id:
            resolved = history_service.get_history(
                conversation_id=resume_id,
                offset=offset,
                limit=limit,
                include_thinking=include_thinking,
                raw=raw
            )
            if resolved.get("error") != "Conversation not found":
                resolved["requestedConversationId"] = conversation_id
                resolved["resolvedConversationId"] = resume_id
                return resolved

    return result


@router.get("/projects", dependencies=[Depends(verify_api_key)])
async def list_projects():
    """
    列出所有项目

    返回 ~/.claude/projects/ 下所有项目目录
    """
    projects = history_service.list_projects()
    claude_data_dir = history_service.get_claude_data_dir()
    return {
        "claudeDataDir": claude_data_dir,
        "projects": projects
    }


@router.get("/conversations", dependencies=[Depends(verify_api_key)])
async def list_conversations(
    limit: int = Query(100, description="返回会话数量限制")
):
    """
    列出所有会话

    返回 ~/.claude/projects/ 下所有 .jsonl 文件
    """
    claude_data_dir = history_service.get_claude_data_dir()
    conversations = history_service.list_conversations(limit=limit)
    return {
        "claudeDataDir": claude_data_dir,
        "conversations": conversations
    }
