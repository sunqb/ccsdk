"""
RAG MySQL 数据库模块。

提供 SQLAlchemy 异步引擎、会话工厂和 ORM 模型定义。
当 RAG_DB_DSN 配置时使用 MySQL；否则回退到 SQLite snapshot。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.mysql import JSON, MEDIUMTEXT
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
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, comment="扩展元数据")
    create_by: Mapped[str | None] = mapped_column(String(64), comment="创建人")
    create_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    update_by: Mapped[str | None] = mapped_column(String(64), comment="更新人")
    update_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
    is_delete: Mapped[int] = mapped_column(SmallInteger, default=1, comment="是否删除，1：正常，2：删除")

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", name="uk_kb_id"),
        UniqueConstraint("tenant_id", "owner_id", "name", "is_delete", name="uk_scope_name"),
        Index("idx_source_file_set_id", "source_file_set_id"),
        Index("idx_name", "name"),
        Index("idx_scope_name_active", "name", "is_delete"),
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
        {"comment": "RAG文件表"},
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
    vector_id: Mapped[str | None] = mapped_column(String(128), comment="向量库中的向量点ID")
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
