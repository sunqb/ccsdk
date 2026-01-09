"""
请求模型定义
"""
from typing import Optional, Any, Union
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """自定义工具定义"""
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    input_schema: dict[str, Any] = Field(
        ...,
        alias="inputSchema",
        description="输入参数 JSON Schema"
    )

    class Config:
        populate_by_name = True


class AgentSDKOptions(BaseModel):
    """Agent SDK 选项（透传给 claude-agent-sdk）"""
    allowed_tools: Optional[list[str]] = Field(
        None,
        alias="allowedTools",
        description="允许使用的工具列表，默认 ['Skill']"
    )
    disallowed_tools: Optional[list[str]] = Field(
        None,
        alias="disallowedTools",
        description="禁止使用的工具列表"
    )
    tools: Optional[list[ToolDefinition]] = Field(
        None,
        description="自定义工具列表"
    )
    max_turns: Optional[int] = Field(
        None,
        alias="maxTurns",
        description="最大对话轮数"
    )

    class Config:
        populate_by_name = True


class StreamRequest(BaseModel):
    """Agent SDK 流式请求 - 兼容原 cc-agent-sdk API"""
    # 主要参数
    prompt: Optional[str] = Field(None, description="完整的提示词输入")
    user_message: Optional[str] = Field(
        None,
        alias="userMessage",
        description="用户消息（prompt 的别名）"
    )
    conversation_id: Optional[str] = Field(
        None,
        alias="conversationId",
        description="会话ID，映射到 cc 的 resume；不传则创建新会话"
    )

    # API 配置覆盖（请求级别）
    model: Optional[str] = Field(
        None,
        description="模型名称，覆盖默认配置"
    )
    base_url: Optional[str] = Field(
        None,
        alias="baseURL",
        description="API Base URL，覆盖默认配置"
    )
    api_key: Optional[str] = Field(
        None,
        alias="apiKey",
        description="API Key，覆盖默认配置"
    )

    # SDK 选项
    options: Optional[AgentSDKOptions] = Field(
        None,
        description="透传给 @anthropic-ai/claude-agent-sdk 的选项"
    )
    system_prompt: Optional[Union[str, dict[str, Any]]] = Field(
        None,
        alias="systemPrompt",
        description="系统提示词，可以是字符串或预设配置"
    )
    setting_sources: Optional[list[str]] = Field(
        None,
        alias="settingSources",
        description="设置来源，默认 ['user', 'project']"
    )
    cwd: Optional[str] = Field(
        None,
        description="工作目录"
    )

    class Config:
        populate_by_name = True

    def get_prompt(self) -> str:
        """获取有效的 prompt（优先 prompt，其次 userMessage）"""
        return self.prompt or self.user_message or ""


class HistoryRequest(BaseModel):
    """历史记录查询请求"""
    conversation_id: str = Field(
        ...,
        alias="conversationId",
        description="会话ID（文件名）"
    )
    offset: int = Field(0, description="起始消息序号")
    limit: int = Field(200, description="返回消息数量")
    include_thinking: bool = Field(
        False,
        alias="includeThinking",
        description="是否包含 thinking 块"
    )
    raw: bool = Field(False, description="是否返回完整事件数组")

    class Config:
        populate_by_name = True


class QueryRequest(BaseModel):
    """Agent 查询请求（简化版）"""
    prompt: str = Field(..., description="用户输入的提示词")
    conversation_id: Optional[str] = Field(
        None,
        alias="conversationId",
        description="会话ID，用于继续之前的对话"
    )
    allowed_tools: Optional[list[str]] = Field(
        None,
        alias="allowedTools",
        description="允许使用的工具列表"
    )
    disallowed_tools: Optional[list[str]] = Field(
        None,
        alias="disallowedTools",
        description="禁止使用的工具列表"
    )
    tools: Optional[list[dict[str, Any]]] = Field(
        None,
        description="自定义工具配置"
    )
    max_turns: Optional[int] = Field(
        None,
        alias="maxTurns",
        description="最大对话轮数"
    )
    system_prompt: Optional[str] = Field(
        None,
        alias="systemPrompt",
        description="系统提示词"
    )
    setting_sources: Optional[list[str]] = Field(
        None,
        alias="settingSources",
        description="设置来源"
    )
    cwd: Optional[str] = Field(
        None,
        description="工作目录"
    )

    class Config:
        populate_by_name = True


class SkillRequest(BaseModel):
    """Skill 调用请求"""
    args: Optional[str] = Field(None, description="Skill 参数")
    conversation_id: Optional[str] = Field(
        None,
        alias="conversationId",
        description="会话ID"
    )
    cwd: Optional[str] = Field(
        None,
        description="工作目录，决定 project 级别 skills 的位置 ({cwd}/.claude/skills/)"
    )
    setting_sources: Optional[list[str]] = Field(
        None,
        alias="settingSources",
        description="设置来源，可选 ['user', 'project', 'local']，默认 ['user', 'project']"
    )

    class Config:
        populate_by_name = True
