"""
响应模型定义
"""
from typing import Optional, Any, Literal
from pydantic import BaseModel, Field


class EventData(BaseModel):
    """SSE 事件数据"""
    type: str = Field(..., description="事件类型")
    subtype: Optional[str] = Field(None, description="事件子类型")
    data: Any = Field(None, description="事件数据")
    conversation_id: Optional[str] = Field(
        None,
        alias="conversationId",
        description="会话ID"
    )

    class Config:
        populate_by_name = True


class QueryResponse(BaseModel):
    """查询响应（非流式）"""
    success: bool = Field(..., description="是否成功")
    result: Optional[str] = Field(None, description="结果文本")
    conversation_id: Optional[str] = Field(
        None,
        alias="conversationId",
        description="会话ID"
    )
    error: Optional[str] = Field(None, description="错误信息")

    class Config:
        populate_by_name = True


class SkillInfo(BaseModel):
    """Skill 信息"""
    name: str = Field(..., description="Skill 名称")
    description: Optional[str] = Field(None, description="Skill 描述")
    path: str = Field(..., description="Skill 路径")
    enabled: bool = Field(True, description="是否启用")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: Literal["healthy", "unhealthy"] = Field(..., description="服务状态")
    version: str = Field(..., description="版本号")
