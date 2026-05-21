"""
RAG 请求、响应与内部数据模型定义。
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RagSourceType = Literal["knowledge_base", "file_set", "external_retriever"]
RagFileStatus = Literal[
    "pending",
    "uploaded",
    "parsing",
    "chunking",
    "embedding",
    "indexing",
    "ready",
    "partial_ready",
    "failed",
]
RagEventMode = Literal["rag", "agent-sdk-compatible"]
LowConfidenceStrategy = Literal["insufficient_context", "answer_with_warning"]
RagVerificationMode = Literal["off", "standard", "strict"]
RagAbstentionMode = Literal["off", "insufficient_context", "require_human"]


class RagSource(BaseModel):
    """RAG 检索来源。"""

    type: RagSourceType = Field(..., description="来源类型")
    id: str = Field(..., description="来源 ID，如 knowledgeBaseId 或 fileSetId")
    metadata: dict[str, Any] | None = Field(None, description="来源元数据")

    class Config:
        populate_by_name = True


class RagQueryOptions(BaseModel):
    """RAG 问答选项。"""

    top_k: int = Field(8, alias="topK", ge=1, le=30, description="检索 TopK")
    retrieve_top_k: int = Field(
        100,
        alias="retrieveTopK",
        ge=1,
        le=200,
        description="多路召回候选池大小",
    )
    final_top_k: int | None = Field(
        None,
        alias="finalTopK",
        ge=1,
        le=30,
        description="进入回答的最终证据数量；默认兼容 topK",
    )
    hybrid: bool = Field(True, description="是否启用混合检索")
    rerank: bool = Field(False, description="是否启用 rerank")
    rerank_provider: str | None = Field(
        None,
        alias="rerankProvider",
        description="Rerank provider，如 local_lexical 或 cross_encoder_http",
    )
    query_rewrite: bool = Field(True, alias="queryRewrite", description="是否启用本地查询扩展")
    multi_query: bool = Field(True, alias="multiQuery", description="是否启用多查询召回")
    context_window: int = Field(
        0,
        alias="contextWindow",
        ge=0,
        le=3,
        description="围绕命中 chunk 扩展读取的邻居窗口",
    )
    min_confidence: float = Field(
        0.0,
        alias="minConfidence",
        ge=0.0,
        le=1.0,
        description="非流式回答的最低检索置信度",
    )
    low_confidence_strategy: LowConfidenceStrategy = Field(
        "insufficient_context",
        alias="lowConfidenceStrategy",
        description="低置信度回答策略",
    )
    verification_mode: RagVerificationMode = Field(
        "standard",
        alias="verificationMode",
        description="答案验证强度",
    )
    abstention_mode: RagAbstentionMode = Field(
        "insufficient_context",
        alias="abstentionMode",
        description="证据不足时的兜底策略",
    )
    answer_with_citations: bool = Field(
        True,
        alias="answerWithCitations",
        description="是否要求回答携带引用",
    )
    max_turns: int = Field(10, alias="maxTurns", ge=1, le=20, description="Agent 最大轮次")
    event_mode: RagEventMode = Field(
        "rag",
        alias="eventMode",
        description="SSE 事件模式",
    )

    class Config:
        populate_by_name = True


class RagCitation(BaseModel):
    """RAG 回答引用。"""

    source_id: str = Field(..., alias="sourceId", description="来源 ID")
    source_name: str = Field(..., alias="sourceName", description="来源名称")
    chunk_id: str | None = Field(None, alias="chunkId", description="Chunk ID")
    page: int | None = Field(None, description="页码")
    quote: str | None = Field(None, description="引用原文")
    score: float | None = Field(None, description="检索相关性分数")
    metadata: dict[str, Any] | None = Field(None, description="引用元数据")

    class Config:
        populate_by_name = True


class RagFileInfo(BaseModel):
    """上传文件信息。"""

    file_id: str = Field(..., alias="fileId", description="文件 ID")
    filename: str = Field(..., description="原始文件名")
    mime_type: str | None = Field(None, alias="mimeType", description="MIME 类型")
    size: int = Field(..., ge=0, description="文件大小，单位字节")
    status: RagFileStatus = Field("pending", description="文件处理状态")
    error: str | None = Field(None, description="文件级错误信息")

    class Config:
        populate_by_name = True


class UploadFileResponse(BaseModel):
    """RAG 文件上传响应。"""

    file_set_id: str = Field(..., alias="fileSetId", description="文件集 ID")
    status: RagFileStatus = Field(..., description="文件集索引状态")
    conversation_id: str | None = Field(None, alias="conversationId", description="会话 ID")
    files: list[RagFileInfo] = Field(default_factory=list, description="上传文件列表")

    class Config:
        populate_by_name = True


class CreateKnowledgeBaseRequest(BaseModel):
    """Create a persistent knowledge base from an existing file set."""

    name: str = Field(..., min_length=1, description="知识库名称")
    description: str | None = Field(None, description="知识库描述")
    source_file_set_id: str = Field(..., alias="sourceFileSetId", description="来源 fileSet ID")
    tenant_id: str | None = Field(None, alias="tenantId", description="租户 ID")
    owner_id: str | None = Field(None, alias="ownerId", description="所有者 ID")
    api_key_id: str | None = Field(None, alias="apiKeyId", description="API Key ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="知识库元数据")

    class Config:
        populate_by_name = True


class KnowledgeBaseInfo(BaseModel):
    """Persistent knowledge base metadata."""

    knowledge_base_id: str = Field(..., alias="knowledgeBaseId", description="知识库 ID")
    name: str = Field(..., description="知识库名称")
    description: str | None = Field(None, description="知识库描述")
    source_file_set_id: str = Field(..., alias="sourceFileSetId", description="来源 fileSet ID")
    status: str = Field(..., description="知识库状态")
    created_at: datetime = Field(..., alias="createdAt", description="创建时间")
    updated_at: datetime = Field(..., alias="updatedAt", description="更新时间")
    tenant_id: str | None = Field(None, alias="tenantId", description="租户 ID")
    owner_id: str | None = Field(None, alias="ownerId", description="所有者 ID")
    api_key_id: str | None = Field(None, alias="apiKeyId", description="API Key ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="知识库元数据")

    class Config:
        populate_by_name = True


class KnowledgeBaseListResponse(BaseModel):
    """Knowledge base list response."""

    knowledge_bases: list[KnowledgeBaseInfo] = Field(
        default_factory=list,
        alias="knowledgeBases",
        description="知识库列表",
    )

    class Config:
        populate_by_name = True


class RagFileSetStatusResponse(BaseModel):
    """RAG 文件集索引状态响应。"""

    file_set_id: str = Field(..., alias="fileSetId", description="文件集 ID")
    status: RagFileStatus = Field(..., description="文件集索引状态")
    progress: int = Field(0, ge=0, le=100, description="索引进度百分比")
    indexed_chunks: int = Field(0, alias="indexedChunks", ge=0, description="已索引块数")
    total_chunks: int | None = Field(None, alias="totalChunks", ge=0, description="总块数")
    files: list[RagFileInfo] = Field(default_factory=list, description="文件状态列表")
    errors: list[str] = Field(default_factory=list, description="错误列表")

    class Config:
        populate_by_name = True


class RagStreamRequest(BaseModel):
    """RAG 流式问答请求。"""

    message: str = Field(..., min_length=1, description="用户问题")
    conversation_id: str | None = Field(None, alias="conversationId", description="会话 ID")
    knowledge_base_id: str | None = Field(
        None,
        alias="knowledgeBaseId",
        description="知识库 ID",
    )
    file_set_id: str | None = Field(None, alias="fileSetId", description="文件集 ID")
    sources: list[RagSource] | None = Field(None, description="显式检索来源")
    options: RagQueryOptions = Field(default_factory=RagQueryOptions, description="RAG 选项")
    model: str | None = Field(None, description="模型名称，覆盖默认配置")
    base_url: str | None = Field(None, alias="baseURL", description="API Base URL")
    api_key: str | None = Field(None, alias="apiKey", description="API Key")
    cwd: str | None = Field(None, description="工作目录")

    class Config:
        populate_by_name = True

    def get_sources(self) -> list[RagSource]:
        """获取显式或兼容字段推导出的检索来源。"""
        if self.sources is not None:
            return self.sources

        sources: list[RagSource] = []
        if self.knowledge_base_id:
            sources.append(RagSource(type="knowledge_base", id=self.knowledge_base_id))
        if self.file_set_id:
            sources.append(RagSource(type="file_set", id=self.file_set_id))
        return sources


class RagAnswer(BaseModel):
    """RAG 非流式回答结构。"""

    answer: str = Field(..., description="回答文本")
    citations: list[RagCitation] = Field(default_factory=list, description="引用列表")
    conversation_id: str | None = Field(None, alias="conversationId", description="会话 ID")
    usage: dict[str, Any] = Field(default_factory=dict, description="检索和 Agent 使用统计")

    class Config:
        populate_by_name = True


class RagErrorResponse(BaseModel):
    """RAG 统一错误响应。"""

    code: str = Field(..., description="错误码")
    message: str = Field(..., description="错误信息")
    request_id: str | None = Field(None, alias="requestId", description="请求 ID")
    details: dict[str, Any] | None = Field(None, description="错误详情")

    class Config:
        populate_by_name = True


class RagRequestContext(BaseModel):
    """请求级 RAG 工具上下文，用于隔离并发请求。"""

    request_id: str = Field(..., alias="requestId", description="请求 ID")
    conversation_id: str | None = Field(None, alias="conversationId", description="会话 ID")
    tenant_id: str | None = Field(None, alias="tenantId", description="租户 ID")
    owner_id: str | None = Field(None, alias="ownerId", description="所有者 ID")
    api_key_id: str | None = Field(None, alias="apiKeyId", description="API Key ID")
    sources: list[RagSource] = Field(default_factory=list, description="允许访问的来源")
    active_file_set_id: str | None = Field(
        None,
        alias="activeFileSetId",
        description="当前活跃文件集 ID",
    )
    top_k: int = Field(8, alias="topK", ge=1, le=30, description="最大检索 TopK")
    permissions: dict[str, Any] = Field(default_factory=dict, description="权限上下文")

    class Config:
        populate_by_name = True
