"""
响应模型定义
"""
from datetime import datetime
from typing import Optional, Any, Literal
from pydantic import BaseModel, Field


def _now_text() -> str:
    """返回统一响应时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AjaxResult(BaseModel):
    """统一 API 响应结构，兼容 Java AjaxResult 语义。"""
    # 如果接口错误，则 code 为非 200 值
    code: int = Field(200, description="业务状态码")
    # 时间
    time: Optional[str] = Field(None, description="响应时间")
    # 消息
    msg: str = Field("", description="响应消息")
    # 成功时 data 存返回数据，错误时通常为空
    data: Any = Field(None, description="响应数据")
    # true：成功，代表本次请求是否成功
    success: bool = Field(False, description="本次请求是否成功")

    @classmethod
    def success_response(
        cls,
        data: Any = None,
        msg: str = "成功",
        code: int = 200,
    ) -> "AjaxResult":
        return cls(code=code, time=_now_text(), msg=msg, data=data, success=True)

    @classmethod
    def fail_response(
        cls,
        msg: str = "失败",
        code: int = 500,
        data: Any = None,
    ) -> "AjaxResult":
        return cls(code=code, time=_now_text(), msg=msg, data=data, success=False)

    @classmethod
    def warn_response(
        cls,
        msg: str = "失败",
        code: int = 300,
        data: Any = None,
    ) -> "AjaxResult":
        return cls(code=code, time=_now_text(), msg=msg, data=data, success=False)

    @classmethod
    def unload_response(cls, msg: str = "请先登录") -> "AjaxResult":
        return cls(code=401, time=_now_text(), msg=msg, data=None, success=False)

    def failed(self) -> bool:
        return self.code != 200

    def to_response_dict(self) -> dict:
        """兼容 Pydantic v1/v2 的字典输出。"""
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()


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
