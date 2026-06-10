"""
RAG MySQL 数据库模块。

提供 SQLAlchemy 异步引擎、会话工厂和 ORM 模型定义。
当 DB_DSN 配置时使用 MySQL；否则回退到 SQLite snapshot。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.mysql import JSON, LONGTEXT, MEDIUMTEXT
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings


class Base(DeclarativeBase):
    """ORM 基类。"""
    pass


# ---------------------------------------------------------------------------
# ORM 模型
# ---------------------------------------------------------------------------

class ERagKnowledgeBase(Base):
    """RAG 知识库表。"""
    __tablename__ = "e_rag_knowledge_base"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    knowledge_base_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="知识库业务ID，如kb_xxx")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="知识库名称，如zsk1")
    description: Mapped[str | None] = mapped_column(String(512), comment="知识库描述")
    source_file_set_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="来源文件集业务ID")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态，1：处理中，2：就绪，3：部分就绪，4：失败")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    vector_provider: Mapped[str | None] = mapped_column(String(64), comment="向量库类型")
    vector_collection: Mapped[str | None] = mapped_column(String(128), comment="向量库collection")
    vector_namespace: Mapped[str | None] = mapped_column(String(128), comment="向量库namespace")
    vector_filter: Mapped[dict | None] = mapped_column(JSON, comment="向量检索过滤条件")
    embedding_provider: Mapped[str | None] = mapped_column(String(64), comment="Embedding provider")
    embedding_model: Mapped[str | None] = mapped_column(String(128), comment="Embedding model")
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, comment="Embedding dimension")
    embedding_base_url: Mapped[str | None] = mapped_column(String(512), comment="Embedding service base URL")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")
    tenant_scope_id: Mapped[str] = mapped_column(String(64), Computed("coalesce(`tenant_id`, '')"), comment="归一化租户作用域")
    owner_scope_id: Mapped[str] = mapped_column(String(64), Computed("coalesce(`owner_id`, '')"), comment="归一化所有者作用域")

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", name="uk_kb_id"),
        UniqueConstraint("tenant_scope_id", "owner_scope_id", "name", "is_delete", name="uk_scope_name"),
        Index("idx_source_file_set_id", "source_file_set_id"),
        Index("idx_name", "name"),
        Index("idx_scope_name_active", "name", "is_delete"),
        Index("idx_tenant_owner", "tenant_id", "owner_id"),
        Index("idx_embedding_model", "embedding_provider", "embedding_model"),
        {"comment": "RAG知识库表"},
    )


class ERagFileSet(Base):
    """RAG 文件集表。"""
    __tablename__ = "e_rag_file_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    file_set_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件集业务ID")
    conversation_id: Mapped[str | None] = mapped_column(String(64), comment="会话ID")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态，1：处理中，2：就绪，3：部分就绪，4：失败")
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0, comment="已索引chunk数")
    total_chunks: Mapped[int] = mapped_column(Integer, default=0, comment="总chunk数")
    temporary: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否临时，1：临时，2：持久")
    parse_only: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否仅解析不入库RAG，1：否（默认，走RAG），2：是（纯文件问答）")
    knowledge_base_id: Mapped[str | None] = mapped_column(String(64), comment="关联知识库业务ID")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    expires_time: Mapped[datetime | None] = mapped_column(DateTime, comment="过期时间")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("file_set_id", name="uk_file_set_id"),
        Index("idx_knowledge_base_id", "knowledge_base_id"),
        Index("idx_conversation_id", "conversation_id"),
        {"comment": "RAG文件集表"},
    )


class ERagFile(Base):
    """RAG 文件表。"""
    __tablename__ = "e_rag_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    file_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件业务ID")
    file_set_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件集业务ID")
    filename: Mapped[str] = mapped_column(String(512), nullable=False, comment="原始文件名")
    mime_type: Mapped[str | None] = mapped_column(String(128), comment="MIME类型")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, comment="文件大小，单位字节")
    storage_type: Mapped[int] = mapped_column(SmallInteger, default=1, comment="存储类型，1：本地，2：对象存储，3：外部URL")
    file_path: Mapped[str | None] = mapped_column(String(1024), comment="原始文件存储地址")
    parsed_file_path: Mapped[str | None] = mapped_column(String(1024), comment="解析后文本文件地址")
    parsed_content_id: Mapped[str | None] = mapped_column(String(64), comment="parseOnly解析内容ID")
    file_url: Mapped[str | None] = mapped_column(String(1024), comment="文件访问URL")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态，1：处理中，2：就绪，3：失败")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(1024), comment="错误信息")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("file_id", name="uk_file_id"),
        Index("idx_file_set_id", "file_set_id"),
        Index("idx_parsed_content_id", "parsed_content_id"),
        {"comment": "RAG文件表"},
    )


class ERagParsedContent(Base):
    """RAG 解析内容缓存表（纯文件问答模式专用）。

    同一文件内容在同一 parser/config 下只保存一份 ``parsed_text``。
    具体上传文件通过 ``ERagFile.parsed_content_id`` 引用本表。
    """

    __tablename__ = "e_rag_parsed_content"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="id")
    parsed_content_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="解析内容业务ID，如pc_xxx")
    md5: Mapped[str] = mapped_column(String(32), nullable=False, comment="文件内容MD5，用于去重复用")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, comment="文件大小，单位字节")
    parser: Mapped[str] = mapped_column(String(32), nullable=False, comment="解析器：local / mineru / kimi")
    parser_version: Mapped[str | None] = mapped_column(String(64), comment="解析器版本")
    parser_config_hash: Mapped[str | None] = mapped_column(String(64), comment="解析配置hash")
    mime_type: Mapped[str | None] = mapped_column(String(128), comment="MIME类型")
    parsed_text: Mapped[str | None] = mapped_column(LONGTEXT, comment="解析后文本")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态，1：处理中，2：就绪，3：失败")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(1024), comment="错误信息")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")
    parser_version_scope: Mapped[str] = mapped_column(String(64), Computed("coalesce(`parser_version`, '')"), comment="归一化解析器版本")
    parser_config_hash_scope: Mapped[str] = mapped_column(String(64), Computed("coalesce(`parser_config_hash`, '')"), comment="归一化解析配置hash")

    __table_args__ = (
        UniqueConstraint("parsed_content_id", name="uk_parsed_content_id"),
        UniqueConstraint(
            "md5",
            "file_size",
            "parser",
            "parser_version_scope",
            "parser_config_hash_scope",
            "is_delete",
            name="uk_parse_cache_key",
        ),
        Index("idx_md5", "md5"),
        Index("idx_parser", "parser"),
        {"comment": "RAG解析内容缓存表"},
    )


class ERagChunk(Base):
    """RAG Chunk 表。"""
    __tablename__ = "e_rag_chunk"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="Chunk业务ID")
    file_set_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件集业务ID")
    knowledge_base_id: Mapped[str | None] = mapped_column(String(64), comment="知识库业务ID")
    source_file_id: Mapped[str | None] = mapped_column(String(64), comment="来源文件业务ID")
    vector_provider: Mapped[str | None] = mapped_column(String(64), comment="向量库类型")
    vector_collection: Mapped[str | None] = mapped_column(String(128), comment="向量库collection")
    vector_namespace: Mapped[str | None] = mapped_column(String(128), comment="向量库namespace")
    vector_id: Mapped[str | None] = mapped_column(String(128), comment="向量库中的向量点ID")
    embedding_provider: Mapped[str | None] = mapped_column(String(64), comment="Embedding provider")
    embedding_model: Mapped[str | None] = mapped_column(String(128), comment="Embedding model")
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, comment="Embedding dimension")
    chunk_index: Mapped[int | None] = mapped_column(Integer, comment="Chunk序号")
    chunk_text: Mapped[str | None] = mapped_column(MEDIUMTEXT, comment="Chunk文本内容")
    token_count: Mapped[int] = mapped_column(Integer, default=0, comment="Token数量")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("chunk_id", name="uk_chunk_id"),
        Index("idx_file_set_id", "file_set_id"),
        Index("idx_knowledge_base_id", "knowledge_base_id"),
        Index("idx_source_file_id", "source_file_id"),
        Index("idx_vector_id", "vector_provider", "vector_collection", "vector_id"),
        {"comment": "RAG Chunk表"},
    )


class ERagIngestionJob(Base):
    """RAG 入库任务表。"""
    __tablename__ = "e_rag_ingestion_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="入库任务业务ID")
    file_set_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="关联文件集业务ID")
    knowledge_base_id: Mapped[str | None] = mapped_column(String(64), comment="关联知识库业务ID")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    status: Mapped[str] = mapped_column(String(32), default="pending", comment="任务状态")
    stage: Mapped[str | None] = mapped_column(String(32), comment="当前阶段")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, comment="进度百分比")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="当前重试次数")
    max_retries: Mapped[int] = mapped_column(Integer, default=0, comment="最大重试次数")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(2048), comment="错误信息")
    started_time: Mapped[datetime | None] = mapped_column(DateTime, comment="任务开始时间")
    finished_time: Mapped[datetime | None] = mapped_column(DateTime, comment="任务结束时间")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("job_id", name="uk_job_id"),
        Index("idx_file_set_id", "file_set_id"),
        Index("idx_ingestion_knowledge_base_id", "knowledge_base_id"),
        Index("idx_ingestion_scope_status", "tenant_id", "owner_id", "status", "is_delete"),
        Index("idx_status_stage", "status", "stage", "is_delete"),
        Index("idx_ingestion_create_time", "create_time"),
        {"comment": "RAG 入库任务表"},
    )


class ERagQueryLog(Base):
    """RAG 查询日志表。"""
    __tablename__ = "e_rag_query_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    query_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="查询业务ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="请求ID")
    conversation_id: Mapped[str | None] = mapped_column(String(64), comment="会话ID")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    message: Mapped[str | None] = mapped_column(MEDIUMTEXT, comment="用户原始问题")
    source_scope_json: Mapped[dict | None] = mapped_column(JSON, comment="来源范围")
    retrieval_top_k: Mapped[int | None] = mapped_column(Integer, comment="请求 top_k")
    retrieve_top_k: Mapped[int | None] = mapped_column(Integer, comment="候选召回池大小")
    final_top_k: Mapped[int | None] = mapped_column(Integer, comment="最终证据数量")
    matched_chunks: Mapped[dict | list | None] = mapped_column(JSON, comment="命中 chunk")
    citation_count: Mapped[int] = mapped_column(Integer, default=0, comment="引用数量")
    confidence: Mapped[float | None] = mapped_column(Numeric(8, 6), comment="置信度")
    abstained: Mapped[int] = mapped_column(SmallInteger, default=2, comment="是否拒答，1是2否")
    abstention_reason: Mapped[str | None] = mapped_column(String(128), comment="拒答原因")
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="端到端耗时")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="提示词 token")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="回答 token")
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, comment="Embedding token")
    model: Mapped[str | None] = mapped_column(String(128), comment="回答模型")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("query_id", name="uk_query_id"),
        Index("idx_query_request_id", "request_id"),
        Index("idx_query_conversation_id", "conversation_id"),
        Index("idx_query_scope_time", "tenant_id", "owner_id", "create_time"),
        Index("idx_query_api_key_time", "api_key_id", "create_time"),
        Index("idx_abstained", "abstained", "create_time"),
        {"comment": "RAG 查询日志表"},
    )


class ERagToolCallLog(Base):
    """RAG 工具调用日志表。"""
    __tablename__ = "e_rag_tool_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    tool_call_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="工具调用业务ID")
    query_id: Mapped[str | None] = mapped_column(String(64), comment="关联查询ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="关联请求ID")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="工具名称")
    tool_args_json: Mapped[dict | None] = mapped_column(JSON, comment="工具参数")
    result_count: Mapped[int] = mapped_column(Integer, default=0, comment="结果数量")
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="耗时")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(2048), comment="错误信息")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uk_tool_call_id"),
        Index("idx_tool_query_id", "query_id"),
        Index("idx_tool_request_id", "request_id"),
        Index("idx_tool_name_time", "tool_name", "create_time"),
        Index("idx_tool_scope_time", "tenant_id", "owner_id", "create_time"),
        {"comment": "RAG 工具调用日志表"},
    )


class ERagUsageDaily(Base):
    """RAG 每日用量表。"""
    __tablename__ = "e_rag_usage_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    stat_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="统计日期")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    uploaded_files: Mapped[int] = mapped_column(Integer, default=0, comment="上传文件数")
    uploaded_bytes: Mapped[int] = mapped_column(BigInteger, default=0, comment="上传字节数")
    parsed_pages: Mapped[int] = mapped_column(Integer, default=0, comment="解析页数")
    chunks_created: Mapped[int] = mapped_column(Integer, default=0, comment="创建 chunk 数")
    embedding_tokens: Mapped[int] = mapped_column(BigInteger, default=0, comment="Embedding token")
    query_count: Mapped[int] = mapped_column(Integer, default=0, comment="查询次数")
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0, comment="检索次数")
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, comment="提示词 token")
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, comment="回答 token")
    storage_bytes: Mapped[int] = mapped_column(BigInteger, default=0, comment="存储字节数")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")
    tenant_scope_id: Mapped[str] = mapped_column(String(64), Computed("coalesce(`tenant_id`, '')"), comment="归一化租户作用域")
    owner_scope_id: Mapped[str] = mapped_column(String(64), Computed("coalesce(`owner_id`, '')"), comment="归一化所有者作用域")
    api_key_scope_id: Mapped[str] = mapped_column(String(64), Computed("coalesce(`api_key_id`, '')"), comment="归一化 API Key 作用域")

    __table_args__ = (
        UniqueConstraint("stat_date", "tenant_scope_id", "owner_scope_id", "api_key_scope_id", "is_delete", name="uk_usage_scope_day"),
        Index("idx_usage_scope_date", "tenant_id", "owner_id", "stat_date"),
        Index("idx_usage_api_key_date", "api_key_id", "stat_date"),
        {"comment": "RAG 每日用量表"},
    )


class ERagAuditLog(Base):
    """RAG 审计日志表。"""
    __tablename__ = "e_rag_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="id")
    audit_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="审计业务ID")
    tenant_id: Mapped[str | None] = mapped_column(String(64), comment="租户ID")
    owner_id: Mapped[str | None] = mapped_column(String(64), comment="所有者ID")
    api_key_id: Mapped[str | None] = mapped_column(String(64), comment="API Key ID")
    actor_id: Mapped[str | None] = mapped_column(String(64), comment="操作者ID")
    actor_type: Mapped[str | None] = mapped_column(String(32), comment="操作者类型")
    action: Mapped[str] = mapped_column(String(128), nullable=False, comment="动作")
    resource_type: Mapped[str | None] = mapped_column(String(64), comment="资源类型")
    resource_id: Mapped[str | None] = mapped_column(String(128), comment="资源ID")
    request_id: Mapped[str | None] = mapped_column(String(64), comment="请求ID")
    detail_json: Mapped[dict | None] = mapped_column(JSON, comment="操作详情")
    ip_address: Mapped[str | None] = mapped_column(String(64), comment="客户端IP")
    user_agent: Mapped[str | None] = mapped_column(String(512), comment="User-Agent")
    result: Mapped[str | None] = mapped_column(String(32), comment="结果")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(2048), comment="错误信息")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("audit_id", name="uk_audit_id"),
        Index("idx_audit_scope_time", "tenant_id", "owner_id", "create_time"),
        Index("idx_resource", "resource_type", "resource_id"),
        Index("idx_action_time", "action", "create_time"),
        Index("idx_audit_request_id", "request_id"),
        {"comment": "RAG 审计日志表"},
    )


class ERagProviderHealth(Base):
    """RAG provider 健康状态表。"""
    __tablename__ = "e_rag_provider_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="id")
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="Provider health ID")
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="Provider 类型")
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="Provider 名称")
    endpoint: Mapped[str | None] = mapped_column(String(512), comment="Endpoint，不含密钥")
    collection: Mapped[str | None] = mapped_column(String(128), comment="Collection 或 namespace")
    status: Mapped[str] = mapped_column(String(32), default="unknown", comment="健康状态")
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="健康检查耗时")
    capabilities_json: Mapped[dict | None] = mapped_column(JSON, comment="能力信息")
    error_code: Mapped[str | None] = mapped_column(String(64), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(String(2048), comment="错误信息")
    checked_time: Mapped[datetime | None] = mapped_column(DateTime, comment="检查时间")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("provider_id", "is_delete", name="uk_provider_id"),
        Index("idx_provider", "provider_type", "provider_name", "status"),
        Index("idx_checked_time", "checked_time"),
        {"comment": "RAG provider 健康状态表"},
    )


# ---------------------------------------------------------------------------
# 状态映射：内存 RagFileStatus 字符串 <-> 数据库 tinyint
# ---------------------------------------------------------------------------

_RAG_FILE_STATUS_TO_INT: dict[str, int] = {
    "pending": 1,
    "uploaded": 1,
    "parsing": 1,
    "chunking": 1,
    "embedding": 1,
    "indexing": 1,
    "ready": 2,
    "partial_ready": 3,
    "failed": 4,
}

_RAG_FILE_STATUS_FROM_INT: dict[int, str] = {
    1: "parsing",
    2: "ready",
    3: "partial_ready",
    4: "failed",
}

_KB_STATUS_TO_INT: dict[str, int] = {
    "processing": 1,
    "ready": 2,
    "partial_ready": 3,
    "failed": 4,
}

_KB_STATUS_FROM_INT: dict[int, str] = {v: k for k, v in _KB_STATUS_TO_INT.items()}


def rag_status_to_int(status: str) -> int:
    return _RAG_FILE_STATUS_TO_INT.get(status, 1)


def rag_status_from_int(status: int) -> str:
    return _RAG_FILE_STATUS_FROM_INT.get(status, "parsing")


def kb_status_to_int(status: str) -> int:
    return _KB_STATUS_TO_INT.get(status, 1)


def kb_status_from_int(status: int) -> str:
    return _KB_STATUS_FROM_INT.get(status, "processing")


# ---------------------------------------------------------------------------
# 引擎 & 会话工厂
# ---------------------------------------------------------------------------

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_rag_db() -> None:
    """初始化 RAG MySQL 引擎、会话工厂和表结构。"""
    global _engine, _session_factory

    dsn = settings.rag_db_dsn
    if not dsn:
        return

    _engine = create_async_engine(
        dsn,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        echo=False,
    )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print(f"[RAG DB] MySQL 连接初始化完成: {dsn.split('@')[-1] if '@' in dsn else dsn}")


async def close_rag_db() -> None:
    """关闭数据库引擎。"""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """返回当前会话工厂；MySQL 未配置时返回 None。"""
    return _session_factory


def is_mysql_available() -> bool:
    """判断 MySQL 是否已配置并初始化。"""
    return _session_factory is not None
