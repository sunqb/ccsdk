"""
Agent API 路由
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from ..models.request import QueryRequest
from ..models.response import QueryResponse
from ..services.agent import agent_service

router = APIRouter(prefix="/agent", tags=["Agent"])


async def _generate_sse_events(
    prompt: str,
    conversation_id: str | None,
    allowed_tools: list[str] | None,
    disallowed_tools: list[str] | None,
    max_turns: int | None,
    cwd: str | None
) -> AsyncGenerator[str, None]:
    """生成 SSE 事件流"""
    async for event in agent_service.query_stream(
        prompt=prompt,
        conversation_id=conversation_id,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
        max_turns=max_turns,
        cwd=cwd
    ):
        yield event.to_sse()


@router.post("/query")
async def query_agent(request: QueryRequest) -> QueryResponse:
    """
    非流式查询 Agent

    - **prompt**: 用户输入的提示词
    - **conversationId**: 可选，会话ID用于继续之前的对话
    - **allowedTools**: 可选，允许使用的工具列表
    - **disallowedTools**: 可选，禁止使用的工具列表
    - **maxTurns**: 可选，最大对话轮数
    - **cwd**: 可选，工作目录
    """
    result = await agent_service.query(
        prompt=request.prompt,
        conversation_id=request.conversation_id,
        allowed_tools=request.allowed_tools,
        disallowed_tools=request.disallowed_tools,
        max_turns=request.max_turns,
        cwd=request.cwd
    )

    return QueryResponse(
        success=result["success"],
        result=result.get("result"),
        conversation_id=result.get("conversationId"),
        error=result.get("error")
    )


@router.post("/query/stream")
async def query_agent_stream(request: QueryRequest):
    """
    流式查询 Agent（SSE）

    返回 `text/event-stream` 格式的事件流，事件类型包括：
    - **stream_event**: 流事件（start, end 等）
    - **content_block_delta**: 内容增量（text_delta, tool_use）
    - **result**: 最终结果
    - **error**: 错误信息
    """
    return StreamingResponse(
        _generate_sse_events(
            prompt=request.prompt,
            conversation_id=request.conversation_id,
            allowed_tools=request.allowed_tools,
            disallowed_tools=request.disallowed_tools,
            max_turns=request.max_turns,
            cwd=request.cwd
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
