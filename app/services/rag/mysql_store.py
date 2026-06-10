"""
RAG MySQL 持久化存储。

当 DB_DSN 配置时，知识库元数据写入 MySQL 结构化表；
否则回退到 SQLite JSON snapshot。
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, update

from ...database import (
    ERagAuditLog,
    ERagChunk,
    ERagFile,
    ERagFileSet,
    ERagIngestionJob,
    ERagKnowledgeBase,
    ERagParsedContent,
    ERagProviderHealth,
    ERagQueryLog,
    ERagToolCallLog,
    ERagUsageDaily,
    get_session_factory,
    is_mysql_available,
    kb_status_from_int,
    kb_status_to_int,
    rag_status_from_int,
    rag_status_to_int,
)
from .chunker import RagChunk


_PARSED_FILE_STATUS_TO_INT = {
    "pending": 1,
    "uploaded": 1,
    "parsing": 1,
    "ready": 2,
    "failed": 3,
}
_PARSED_FILE_STATUS_FROM_INT = {1: "parsing", 2: "ready", 3: "failed"}


def _parsed_file_status_to_int(status: str) -> int:
    return _PARSED_FILE_STATUS_TO_INT.get(status, 1)


def _parsed_file_status_from_int(status: int) -> str:
    return _PARSED_FILE_STATUS_FROM_INT.get(status, "parsing")


class RagMySqlStore:
    """MySQL 持久化存储 for RAG knowledge base metadata."""

    def __init__(self) -> None:
        # Local/dev fallback used when DB_DSN is not configured. Production
        # still uses MySQL as the source of truth via get_session_factory().
        self._memory_file_sets: dict[str, dict[str, Any]] = {}
        self._memory_parsed_files: dict[str, list[dict[str, Any]]] = {}
        self._memory_parsed_contents: dict[str, dict[str, Any]] = {}

    async def save_knowledge_base(
        self,
        *,
        knowledge_base_id: str,
        name: str,
        source_file_set_id: str,
        status: str = "ready",
        description: str | None = None,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
        vector_provider: str | None = None,
        vector_collection: str | None = None,
        vector_namespace: str | None = None,
        vector_filter: dict | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        embedding_base_url: str | None = None,
        metadata: dict | None = None,
        create_by: str | None = None,
    ) -> None:
        factory = get_session_factory()
        if factory is None:
            return
        now = datetime.now(UTC)
        row = ERagKnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            name=name,
            source_file_set_id=source_file_set_id,
            status=kb_status_to_int(status),
            description=description,
            tenant_id=tenant_id,
            owner_id=owner_id,
            api_key_id=api_key_id,
            vector_provider=vector_provider,
            vector_collection=vector_collection,
            vector_namespace=vector_namespace,
            vector_filter=vector_filter,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            embedding_base_url=embedding_base_url,
            metadata_json=metadata or {},
            create_by=create_by,
            create_time=now,
            update_by=create_by,
            update_time=now,
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def get_knowledge_base_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> dict[str, Any] | None:
        """按名称查询知识库，返回 dict 或 None。

        使用 COALESCE 处理 NULL 值，确保 tenant_id/owner_id 为 NULL 时
        也能正确匹配（MySQL 中 NULL != NULL，必须用 COALESCE 归一化）。
        """
        factory = get_session_factory()
        if factory is None:
            return None

        conditions = [
            ERagKnowledgeBase.name == name,
            ERagKnowledgeBase.is_delete == 1,
            func.coalesce(ERagKnowledgeBase.tenant_id, "") == (tenant_id or ""),
            func.coalesce(ERagKnowledgeBase.owner_id, "") == (owner_id or ""),
        ]
        if api_key_id is not None:
            conditions.append(
                func.coalesce(ERagKnowledgeBase.api_key_id, "") == api_key_id
            )

        async with factory() as session:
            result = await session.execute(
                select(ERagKnowledgeBase).where(and_(*conditions))
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._kb_row_to_dict(row)

    async def get_knowledge_base_by_id(
        self,
        knowledge_base_id: str,
    ) -> dict[str, Any] | None:
        """按 knowledge_base_id 查询知识库。"""
        factory = get_session_factory()
        if factory is None:
            return None

        async with factory() as session:
            result = await session.execute(
                select(ERagKnowledgeBase).where(
                    and_(
                        ERagKnowledgeBase.knowledge_base_id == knowledge_base_id,
                        ERagKnowledgeBase.is_delete == 1,
                    )
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._kb_row_to_dict(row)

    async def check_name_exists(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
    ) -> bool:
        """检查同作用域下知识库名称是否已存在。

        使用 COALESCE 处理 NULL 值，避免 MySQL 中 NULL != NULL
        导致同作用域重名检查失效。
        """
        factory = get_session_factory()
        if factory is None:
            return False

        conditions = [
            ERagKnowledgeBase.name == name,
            ERagKnowledgeBase.is_delete == 1,
            func.coalesce(ERagKnowledgeBase.tenant_id, "") == (tenant_id or ""),
            func.coalesce(ERagKnowledgeBase.owner_id, "") == (owner_id or ""),
        ]

        async with factory() as session:
            result = await session.execute(
                select(ERagKnowledgeBase.id).where(and_(*conditions)).limit(1)
            )
            return result.scalar_one_or_none() is not None

    async def resolve_knowledge_base_names(
        self,
        names: list[str],
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """批量解析知识库名称为 knowledge_base_id。

        返回解析结果列表，每个元素包含 name、knowledge_base_id。
        如果某个名称不存在，对应元素包含 error 字段。
        """
        results: list[dict[str, Any]] = []
        for name in names:
            kb = await self.get_knowledge_base_by_name(
                name,
                tenant_id=tenant_id,
                owner_id=owner_id,
                api_key_id=api_key_id,
            )
            if kb is None:
                results.append({"name": name, "error": "knowledge_base_not_found"})
            else:
                results.append({
                    "name": name,
                    "knowledge_base_id": kb["knowledge_base_id"],
                    "source_file_set_id": kb["source_file_set_id"],
                })
        return results

    async def list_knowledge_bases(
        self,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出知识库。"""
        factory = get_session_factory()
        if factory is None:
            return []

        conditions = [ERagKnowledgeBase.is_delete == 1]
        if tenant_id is not None:
            conditions.append(ERagKnowledgeBase.tenant_id == tenant_id)
        if owner_id is not None:
            conditions.append(ERagKnowledgeBase.owner_id == owner_id)
        if api_key_id is not None:
            conditions.append(ERagKnowledgeBase.api_key_id == api_key_id)
        if name is not None:
            conditions.append(ERagKnowledgeBase.name == name)

        async with factory() as session:
            result = await session.execute(
                select(ERagKnowledgeBase)
                .where(and_(*conditions))
                .order_by(ERagKnowledgeBase.create_time.desc())
            )
            rows = result.scalars().all()
            return [self._kb_row_to_dict(row) for row in rows]

    async def delete_knowledge_base(
        self,
        knowledge_base_id: str,
        *,
        update_by: str | None = None,
    ) -> bool:
        """软删除知识库。"""
        factory = get_session_factory()
        if factory is None:
            return False

        async with factory() as session:
            result = await session.execute(
                update(ERagKnowledgeBase)
                .where(
                    and_(
                        ERagKnowledgeBase.knowledge_base_id == knowledge_base_id,
                        ERagKnowledgeBase.is_delete == 1,
                    )
                )
                .values(
                    is_delete=2,
                    update_by=update_by,
                    update_time=datetime.now(UTC),
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def save_file_set(
        self,
        *,
        file_set_id: str,
        conversation_id: str | None = None,
        status: str = "pending",
        indexed_chunks: int = 0,
        total_chunks: int = 0,
        temporary: bool = True,
        knowledge_base_id: str | None = None,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
        metadata: dict | None = None,
        expires_time: datetime | None = None,
        create_by: str | None = None,
        parse_only: int | None = None,
    ) -> None:
        factory = get_session_factory()
        if factory is None:
            now = datetime.now(UTC)
            self._memory_file_sets[file_set_id] = {
                "file_set_id": file_set_id,
                "conversation_id": conversation_id,
                "status": status,
                "indexed_chunks": indexed_chunks,
                "total_chunks": total_chunks,
                "temporary": temporary,
                "knowledge_base_id": knowledge_base_id,
                "tenant_id": tenant_id,
                "owner_id": owner_id,
                "api_key_id": api_key_id,
                "metadata": metadata or {},
                "expires_time": expires_time,
                "created_at": now,
                "updated_at": now,
                "parse_only": 1 if parse_only is None else int(parse_only),
            }
            return
        now = datetime.now(UTC)
        from ...database import rag_status_to_int
        row = ERagFileSet(
            file_set_id=file_set_id,
            conversation_id=conversation_id,
            status=rag_status_to_int(status),
            indexed_chunks=indexed_chunks,
            total_chunks=total_chunks,
            temporary=1 if temporary else 2,
            parse_only=1 if parse_only is None else int(parse_only),
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            api_key_id=api_key_id,
            metadata_json=metadata or {},
            expires_time=expires_time,
            create_by=create_by,
            create_time=now,
            update_by=create_by,
            update_time=now,
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def update_file_set_status(
        self,
        *,
        file_set_id: str,
        status: str,
        indexed_chunks: int | None = None,
        total_chunks: int | None = None,
        temporary: bool | None = None,
        knowledge_base_id: str | None = None,
        metadata: dict | None = None,
        update_by: str | None = None,
        parse_only: int | None = None,
    ) -> None:
        """Update file-set status and counters in MySQL."""
        factory = get_session_factory()
        if factory is None:
            row = self._memory_file_sets.get(file_set_id)
            if row is not None:
                row["status"] = status
                row["updated_at"] = datetime.now(UTC)
                if indexed_chunks is not None:
                    row["indexed_chunks"] = indexed_chunks
                if total_chunks is not None:
                    row["total_chunks"] = total_chunks
                if temporary is not None:
                    row["temporary"] = temporary
                if knowledge_base_id is not None:
                    row["knowledge_base_id"] = knowledge_base_id
                if metadata is not None:
                    row["metadata"] = metadata
                if parse_only is not None:
                    row["parse_only"] = int(parse_only)
            return

        values: dict[str, Any] = {
            "status": rag_status_to_int(status),
            "update_by": update_by,
            "update_time": datetime.now(UTC),
        }
        if indexed_chunks is not None:
            values["indexed_chunks"] = indexed_chunks
        if total_chunks is not None:
            values["total_chunks"] = total_chunks
        if temporary is not None:
            values["temporary"] = 1 if temporary else 2
        if knowledge_base_id is not None:
            values["knowledge_base_id"] = knowledge_base_id
        if metadata is not None:
            values["metadata_json"] = metadata
        if parse_only is not None:
            values["parse_only"] = int(parse_only)

        async with factory() as session:
            await session.execute(
                update(ERagFileSet)
                .where(and_(ERagFileSet.file_set_id == file_set_id, ERagFileSet.is_delete == 1))
                .values(**values)
            )
            await session.commit()

    # ========================================================================
    # 纯文件问答（parse-only）相关方法
    # ========================================================================

    async def save_parsed_content(
        self,
        *,
        parsed_content_id: str,
        md5: str,
        file_size: int,
        parser: str,
        parsed_text: str | None,
        parser_version: str | None = None,
        parser_config_hash: str | None = None,
        mime_type: str | None = None,
        status: str = "ready",
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
        create_by: str | None = None,
    ) -> None:
        """Persist reusable parse-only content cache."""
        factory = get_session_factory()
        if factory is None:
            now = datetime.now(UTC)
            self._memory_parsed_contents[parsed_content_id] = {
                "parsed_content_id": parsed_content_id,
                "md5": md5,
                "file_size": file_size,
                "parser": parser,
                "parser_version": parser_version,
                "parser_config_hash": parser_config_hash,
                "mime_type": mime_type,
                "parsed_text": parsed_text or "",
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "metadata": metadata or {},
                "created_at": now,
                "updated_at": now,
            }
            return
        now = datetime.now(UTC)
        row = ERagParsedContent(
            parsed_content_id=parsed_content_id,
            md5=md5,
            file_size=file_size,
            parser=parser,
            parser_version=parser_version,
            parser_config_hash=parser_config_hash,
            mime_type=mime_type,
            parsed_text=parsed_text,
            status=_parsed_file_status_to_int(status),
            error_code=error_code,
            error_message=error_message,
            metadata_json=metadata or {},
            create_by=create_by,
            create_time=now,
            update_by=create_by,
            update_time=now,
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def get_parsed_content_by_cache_key(
        self,
        md5: str,
        *,
        file_size: int,
        parser: str,
        parser_version: str | None = None,
        parser_config_hash: str | None = None,
    ) -> dict[str, Any] | None:
        """Return ready parsed content for md5 + size + parser cache key."""
        factory = get_session_factory()
        if factory is None:
            for row in self._memory_parsed_contents.values():
                if (
                    row.get("md5") == md5
                    and int(row.get("file_size") or 0) == file_size
                    and row.get("parser") == parser
                    and (row.get("parser_version") or "") == (parser_version or "")
                    and (row.get("parser_config_hash") or "") == (parser_config_hash or "")
                    and row.get("status") == "ready"
                    and row.get("parsed_text")
                ):
                    return dict(row)
            return None
        async with factory() as session:
            result = await session.execute(
                select(ERagParsedContent)
                .where(
                    and_(
                        ERagParsedContent.md5 == md5,
                        ERagParsedContent.file_size == file_size,
                        ERagParsedContent.parser == parser,
                        func.coalesce(ERagParsedContent.parser_version, "") == (parser_version or ""),
                        func.coalesce(ERagParsedContent.parser_config_hash, "") == (parser_config_hash or ""),
                        ERagParsedContent.status == _parsed_file_status_to_int("ready"),
                        ERagParsedContent.parsed_text.is_not(None),
                        ERagParsedContent.parsed_text != "",
                        ERagParsedContent.is_delete == 1,
                    )
                )
                .order_by(ERagParsedContent.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return self._parsed_content_row_to_dict(row) if row is not None else None

    async def get_parsed_files_by_set(self, file_set_id: str) -> list[dict[str, Any]]:
        """Return uploaded files joined with ready reusable parsed content."""
        factory = get_session_factory()
        if factory is None:
            results: list[dict[str, Any]] = []
            for row in self._memory_parsed_files.get(file_set_id, []):
                content = self._memory_parsed_contents.get(str(row.get("parsed_content_id")))
                if not content or content.get("status") != "ready" or not content.get("parsed_text"):
                    continue
                results.append({**content, **row, "metadata": content.get("metadata") or {}})
            return results
        async with factory() as session:
            result = await session.execute(
                select(ERagFile, ERagParsedContent)
                .join(
                    ERagParsedContent,
                    ERagFile.parsed_content_id == ERagParsedContent.parsed_content_id,
                )
                .where(
                    and_(
                        ERagFile.file_set_id == file_set_id,
                        ERagFile.status == rag_status_to_int("ready"),
                        ERagFile.is_delete == 1,
                        ERagParsedContent.status == _parsed_file_status_to_int("ready"),
                        ERagParsedContent.is_delete == 1,
                    )
                )
                .order_by(ERagFile.id.asc())
            )
            rows = result.all()
            return [
                {
                    "file_id": file_row.file_id,
                    "file_set_id": file_row.file_set_id,
                    "filename": file_row.filename,
                    "mime_type": file_row.mime_type or content_row.mime_type,
                    "file_size": file_row.file_size,
                    "parsed_content_id": content_row.parsed_content_id,
                    "md5": content_row.md5,
                    "parser": content_row.parser,
                    "parsed_text": content_row.parsed_text or "",
                    "status": _parsed_file_status_from_int(content_row.status),
                    "metadata": content_row.metadata_json or {},
                }
                for file_row, content_row in rows
            ]

    def _parsed_content_row_to_dict(self, row: ERagParsedContent) -> dict[str, Any]:
        return {
            "parsed_content_id": row.parsed_content_id,
            "md5": row.md5,
            "file_size": row.file_size,
            "parser": row.parser,
            "parser_version": row.parser_version,
            "parser_config_hash": row.parser_config_hash,
            "mime_type": row.mime_type,
            "parsed_text": row.parsed_text or "",
            "status": _parsed_file_status_from_int(row.status),
            "metadata": row.metadata_json or {},
        }

    async def get_file_set_parse_only(self, file_set_id: str) -> int | None:
        """Return parse_only flag (1=RAG mode, 2=parse-only) for a file set.

        Returns None when the file set does not exist.
        """
        factory = get_session_factory()
        if factory is None:
            row = self._memory_file_sets.get(file_set_id)
            if row is None:
                return None
            return int(row.get("parse_only") or 1)
        async with factory() as session:
            result = await session.execute(
                select(ERagFileSet.parse_only).where(
                    and_(
                        ERagFileSet.file_set_id == file_set_id,
                        ERagFileSet.is_delete == 1,
                    )
                )
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else None

    async def get_file_set_metadata(self, file_set_id: str) -> dict[str, Any] | None:
        """Load file-set metadata from MySQL without depending on process memory."""
        factory = get_session_factory()
        if factory is None:
            row = self._memory_file_sets.get(file_set_id)
            return dict(row) if row is not None else None

        async with factory() as session:
            result = await session.execute(
                select(ERagFileSet).where(
                    and_(
                        ERagFileSet.file_set_id == file_set_id,
                        ERagFileSet.is_delete == 1,
                    )
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {
                "file_set_id": row.file_set_id,
                "conversation_id": row.conversation_id,
                "status": rag_status_from_int(row.status),
                "indexed_chunks": row.indexed_chunks,
                "total_chunks": row.total_chunks,
                "temporary": row.temporary == 1,
                "knowledge_base_id": row.knowledge_base_id,
                "tenant_id": row.tenant_id,
                "owner_id": row.owner_id,
                "api_key_id": row.api_key_id,
                "metadata": row.metadata_json or {},
                "expires_time": row.expires_time,
                "created_at": row.create_time,
                "updated_at": row.update_time,
            }

    async def save_file(
        self,
        *,
        file_id: str,
        file_set_id: str,
        filename: str,
        mime_type: str | None = None,
        file_size: int = 0,
        status: str = "uploaded",
        parsed_content_id: str | None = None,
        metadata: dict | None = None,
        create_by: str | None = None,
    ) -> None:
        """Persist uploaded file metadata."""
        factory = get_session_factory()
        if factory is None:
            now = datetime.now(UTC)
            rows = self._memory_parsed_files.setdefault(file_set_id, [])
            rows[:] = [item for item in rows if item.get("file_id") != file_id]
            rows.append(
                {
                    "file_id": file_id,
                    "file_set_id": file_set_id,
                    "filename": filename,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "parsed_content_id": parsed_content_id,
                    "status": status,
                    "metadata": metadata or {},
                    "created_at": now,
                    "updated_at": now,
                }
            )
            return
        now = datetime.now(UTC)
        row = ERagFile(
            file_id=file_id,
            file_set_id=file_set_id,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            parsed_content_id=parsed_content_id,
            status=rag_status_to_int(status),
            metadata_json=metadata or {},
            create_by=create_by,
            create_time=now,
            update_by=create_by,
            update_time=now,
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def update_file_status(
        self,
        *,
        file_id: str,
        status: str,
        mime_type: str | None = None,
        parsed_content_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
        update_by: str | None = None,
    ) -> None:
        """Update one uploaded file's processing state."""
        factory = get_session_factory()
        if factory is None:
            for rows in self._memory_parsed_files.values():
                for row in rows:
                    if row.get("file_id") != file_id:
                        continue
                    row["status"] = status
                    row["error_code"] = error_code
                    row["error_message"] = error_message
                    row["updated_at"] = datetime.now(UTC)
                    if mime_type is not None:
                        row["mime_type"] = mime_type
                    if parsed_content_id is not None:
                        row["parsed_content_id"] = parsed_content_id
                    if metadata is not None:
                        row["metadata"] = metadata
                    return
            return

        values: dict[str, Any] = {
            "status": rag_status_to_int(status),
            "error_code": error_code,
            "error_message": error_message,
            "update_by": update_by,
            "update_time": datetime.now(UTC),
        }
        if mime_type is not None:
            values["mime_type"] = mime_type
        if parsed_content_id is not None:
            values["parsed_content_id"] = parsed_content_id
        if metadata is not None:
            values["metadata_json"] = metadata

        async with factory() as session:
            await session.execute(
                update(ERagFile)
                .where(and_(ERagFile.file_id == file_id, ERagFile.is_delete == 1))
                .values(**values)
            )
            await session.commit()

    async def save_chunks(
        self,
        *,
        chunks: list[RagChunk],
        vector_provider: str | None = None,
        vector_collection: str | None = None,
        vector_namespace: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        create_by: str | None = None,
    ) -> None:
        """Persist chunk metadata after vector indexing succeeds."""
        factory = get_session_factory()
        if factory is None or not chunks:
            return

        now = datetime.now(UTC)
        rows = []
        for chunk in chunks:
            metadata = dict(chunk.metadata or {})
            rows.append(
                ERagChunk(
                    chunk_id=chunk.chunk_id,
                    file_set_id=str(metadata.get("file_set_id") or metadata.get("fileSetId")),
                    knowledge_base_id=metadata.get("knowledge_base_id") or metadata.get("knowledgeBaseId"),
                    source_file_id=chunk.source_file_id,
                    vector_provider=vector_provider,
                    vector_collection=vector_collection,
                    vector_namespace=vector_namespace,
                    vector_id=self._point_id(chunk.chunk_id) if vector_provider == "qdrant" else chunk.chunk_id,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    embedding_dimension=embedding_dimension,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.text,
                    token_count=chunk.token_count,
                    metadata_json=metadata,
                    create_by=create_by,
                    create_time=now,
                    update_by=create_by,
                    update_time=now,
                    is_delete=1,
                )
            )

        async with factory() as session:
            chunk_ids = [chunk.chunk_id for chunk in chunks]
            await session.execute(delete(ERagChunk).where(ERagChunk.chunk_id.in_(chunk_ids)))
            session.add_all(rows)
            await session.commit()

    async def get_file_set_status(self, file_set_id: str) -> dict[str, Any] | None:
        """Load file-set status with files from MySQL."""
        factory = get_session_factory()
        if factory is None:
            return None

        async with factory() as session:
            fs_result = await session.execute(
                select(ERagFileSet).where(
                    and_(ERagFileSet.file_set_id == file_set_id, ERagFileSet.is_delete == 1)
                )
            )
            file_set = fs_result.scalar_one_or_none()
            if file_set is None:
                return None
            files_result = await session.execute(
                select(ERagFile)
                .where(and_(ERagFile.file_set_id == file_set_id, ERagFile.is_delete == 1))
                .order_by(ERagFile.id.asc())
            )
            return {
                "file_set_id": file_set.file_set_id,
                "conversation_id": file_set.conversation_id,
                "status": rag_status_from_int(file_set.status),
                "indexed_chunks": file_set.indexed_chunks,
                "total_chunks": file_set.total_chunks,
                "metadata": file_set.metadata_json or {},
                "files": [self._file_row_to_dict(row) for row in files_result.scalars().all()],
            }

    async def update_file_set_kb_binding(
        self,
        file_set_id: str,
        knowledge_base_id: str,
    ) -> None:
        """更新 file_set 关联的知识库。"""
        factory = get_session_factory()
        if factory is None:
            return
        async with factory() as session:
            await session.execute(
                update(ERagFileSet)
                .where(
                    and_(
                        ERagFileSet.file_set_id == file_set_id,
                        ERagFileSet.is_delete == 1,
                    )
                )
                .values(
                    knowledge_base_id=knowledge_base_id,
                    temporary=2,
                    update_time=datetime.now(UTC),
                )
            )
            await session.commit()

    async def update_chunks_knowledge_base(
        self,
        *,
        file_set_id: str,
        knowledge_base_id: str,
        metadata: dict | None = None,
    ) -> None:
        """Tag persisted chunks with the promoted knowledge base ID."""
        factory = get_session_factory()
        if factory is None:
            return
        values: dict[str, Any] = {
            "knowledge_base_id": knowledge_base_id,
            "update_time": datetime.now(UTC),
        }
        async with factory() as session:
            await session.execute(
                update(ERagChunk)
                .where(and_(ERagChunk.file_set_id == file_set_id, ERagChunk.is_delete == 1))
                .values(**values)
            )
            await session.commit()

    async def create_ingestion_job(
        self,
        *,
        job_id: str,
        file_set_id: str,
        knowledge_base_id: str | None = None,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
        status: str = "running",
        stage: str | None = None,
        progress_percent: int = 0,
        retry_count: int = 0,
        max_retries: int = 0,
        metadata: dict | None = None,
        create_by: str | None = None,
    ) -> None:
        """Create a production metadata row for one ingestion job."""
        factory = get_session_factory()
        if factory is None:
            return
        now = datetime.now(UTC)
        row = ERagIngestionJob(
            job_id=job_id,
            file_set_id=file_set_id,
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            api_key_id=api_key_id,
            status=status,
            stage=stage,
            progress_percent=progress_percent,
            retry_count=retry_count,
            max_retries=max_retries,
            started_time=now if status in {"running", "succeeded", "partial_failed", "failed"} else None,
            metadata_json=metadata or {},
            create_by=create_by,
            create_time=now,
            update_by=create_by,
            update_time=now,
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def update_ingestion_job(
        self,
        *,
        job_id: str,
        status: str | None = None,
        stage: str | None = None,
        progress_percent: int | None = None,
        knowledge_base_id: str | None = None,
        retry_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
        update_by: str | None = None,
    ) -> None:
        """Update an ingestion job status transition."""
        factory = get_session_factory()
        if factory is None:
            return

        now = datetime.now(UTC)
        values: dict[str, Any] = {"update_by": update_by, "update_time": now}
        if status is not None:
            values["status"] = status
            if status in {"succeeded", "partial_failed", "failed", "cancelled"}:
                values["finished_time"] = now
        if stage is not None:
            values["stage"] = stage
        if progress_percent is not None:
            values["progress_percent"] = max(0, min(100, progress_percent))
        if knowledge_base_id is not None:
            values["knowledge_base_id"] = knowledge_base_id
        if retry_count is not None:
            values["retry_count"] = retry_count
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if metadata is not None:
            values["metadata_json"] = metadata

        async with factory() as session:
            await session.execute(
                update(ERagIngestionJob)
                .where(and_(ERagIngestionJob.job_id == job_id, ERagIngestionJob.is_delete == 1))
                .values(**values)
            )
            await session.commit()

    async def get_ingestion_job(self, job_id: str) -> dict[str, Any] | None:
        """Load one ingestion job by business ID."""
        factory = get_session_factory()
        if factory is None:
            return None
        async with factory() as session:
            result = await session.execute(
                select(ERagIngestionJob).where(
                    and_(ERagIngestionJob.job_id == job_id, ERagIngestionJob.is_delete == 1)
                )
            )
            row = result.scalar_one_or_none()
            return None if row is None else self._ingestion_job_row_to_dict(row)

    async def record_query_log(self, **kwargs: Any) -> None:
        """Persist one RAG query log row."""
        factory = get_session_factory()
        if factory is None:
            return
        row = ERagQueryLog(
            query_id=kwargs["query_id"],
            request_id=kwargs.get("request_id"),
            conversation_id=kwargs.get("conversation_id"),
            tenant_id=kwargs.get("tenant_id"),
            owner_id=kwargs.get("owner_id"),
            api_key_id=kwargs.get("api_key_id"),
            message=kwargs.get("message"),
            source_scope_json=kwargs.get("source_scope"),
            retrieval_top_k=kwargs.get("retrieval_top_k"),
            retrieve_top_k=kwargs.get("retrieve_top_k"),
            final_top_k=kwargs.get("final_top_k"),
            matched_chunks=kwargs.get("matched_chunks"),
            citation_count=kwargs.get("citation_count", 0),
            confidence=kwargs.get("confidence"),
            abstained=1 if kwargs.get("abstained") else 2,
            abstention_reason=kwargs.get("abstention_reason"),
            latency_ms=kwargs.get("latency_ms"),
            prompt_tokens=kwargs.get("prompt_tokens", 0),
            completion_tokens=kwargs.get("completion_tokens", 0),
            embedding_tokens=kwargs.get("embedding_tokens", 0),
            model=kwargs.get("model"),
            metadata_json=kwargs.get("metadata") or {},
            create_time=datetime.now(UTC),
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def record_tool_call_log(self, **kwargs: Any) -> None:
        """Persist one RAG tool-call log row."""
        factory = get_session_factory()
        if factory is None:
            return
        row = ERagToolCallLog(
            tool_call_id=kwargs["tool_call_id"],
            query_id=kwargs.get("query_id"),
            request_id=kwargs.get("request_id"),
            tenant_id=kwargs.get("tenant_id"),
            owner_id=kwargs.get("owner_id"),
            api_key_id=kwargs.get("api_key_id"),
            tool_name=kwargs["tool_name"],
            tool_args_json=kwargs.get("tool_args") or {},
            result_count=kwargs.get("result_count", 0),
            latency_ms=kwargs.get("latency_ms"),
            error_code=kwargs.get("error_code"),
            error_message=kwargs.get("error_message"),
            metadata_json=kwargs.get("metadata") or {},
            create_time=datetime.now(UTC),
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()

    async def increment_usage_daily(self, *, stat_date: date | None = None, **kwargs: Any) -> None:
        """Increment daily usage counters for one normalized scope."""
        factory = get_session_factory()
        if factory is None:
            return

        current_date = stat_date or datetime.now(UTC).date()
        tenant_id = kwargs.get("tenant_id")
        owner_id = kwargs.get("owner_id")
        api_key_id = kwargs.get("api_key_id")
        increments = {
            name: int(kwargs.get(name, 0) or 0)
            for name in (
                "uploaded_files",
                "uploaded_bytes",
                "parsed_pages",
                "chunks_created",
                "embedding_tokens",
                "query_count",
                "retrieval_count",
                "prompt_tokens",
                "completion_tokens",
                "storage_bytes",
            )
        }
        now = datetime.now(UTC)
        async with factory() as session:
            result = await session.execute(
                select(ERagUsageDaily).where(
                    and_(
                        ERagUsageDaily.stat_date == current_date,
                        func.coalesce(ERagUsageDaily.tenant_id, "") == (tenant_id or ""),
                        func.coalesce(ERagUsageDaily.owner_id, "") == (owner_id or ""),
                        func.coalesce(ERagUsageDaily.api_key_id, "") == (api_key_id or ""),
                        ERagUsageDaily.is_delete == 1,
                    )
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = ERagUsageDaily(
                    stat_date=current_date,
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    api_key_id=api_key_id,
                    metadata_json=kwargs.get("metadata") or {},
                    create_time=now,
                    update_time=now,
                    is_delete=1,
                    **increments,
                )
                session.add(row)
            else:
                for name, value in increments.items():
                    setattr(row, name, getattr(row, name) + value)
                row.metadata_json = kwargs.get("metadata") or row.metadata_json
                row.update_time = now
            await session.commit()

    async def record_audit_log(self, **kwargs: Any) -> str | None:
        """Persist an audit log row and return its audit_id."""
        factory = get_session_factory()
        if factory is None:
            return None
        audit_id = kwargs.get("audit_id") or f"audit_{uuid.uuid4().hex}"
        row = ERagAuditLog(
            audit_id=audit_id,
            tenant_id=kwargs.get("tenant_id"),
            owner_id=kwargs.get("owner_id"),
            api_key_id=kwargs.get("api_key_id"),
            actor_id=kwargs.get("actor_id"),
            actor_type=kwargs.get("actor_type"),
            action=kwargs["action"],
            resource_type=kwargs.get("resource_type"),
            resource_id=kwargs.get("resource_id"),
            request_id=kwargs.get("request_id"),
            detail_json=kwargs.get("detail") or {},
            ip_address=kwargs.get("ip_address"),
            user_agent=kwargs.get("user_agent"),
            result=kwargs.get("result"),
            error_code=kwargs.get("error_code"),
            error_message=kwargs.get("error_message"),
            create_time=datetime.now(UTC),
            is_delete=1,
        )
        async with factory() as session:
            session.add(row)
            await session.commit()
        return audit_id

    async def upsert_provider_health(self, **kwargs: Any) -> None:
        """Insert or update one provider health row."""
        factory = get_session_factory()
        if factory is None:
            return
        provider_id = kwargs["provider_id"]
        now = datetime.now(UTC)
        async with factory() as session:
            result = await session.execute(
                select(ERagProviderHealth).where(
                    and_(ERagProviderHealth.provider_id == provider_id, ERagProviderHealth.is_delete == 1)
                )
            )
            row = result.scalar_one_or_none()
            values = {
                "provider_type": kwargs["provider_type"],
                "provider_name": kwargs["provider_name"],
                "endpoint": kwargs.get("endpoint"),
                "collection": kwargs.get("collection"),
                "status": kwargs.get("status", "unknown"),
                "latency_ms": kwargs.get("latency_ms"),
                "capabilities_json": kwargs.get("capabilities") or {},
                "error_code": kwargs.get("error_code"),
                "error_message": kwargs.get("error_message"),
                "checked_time": kwargs.get("checked_time") or now,
                "metadata_json": kwargs.get("metadata") or {},
                "update_time": now,
            }
            if row is None:
                session.add(
                    ERagProviderHealth(
                        provider_id=provider_id,
                        create_time=now,
                        is_delete=1,
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await session.commit()

    @staticmethod
    def _kb_row_to_dict(row: ERagKnowledgeBase) -> dict[str, Any]:
        return {
            "knowledge_base_id": row.knowledge_base_id,
            "name": row.name,
            "description": row.description,
            "source_file_set_id": row.source_file_set_id,
            "status": kb_status_from_int(row.status),
            "tenant_id": row.tenant_id,
            "owner_id": row.owner_id,
            "api_key_id": row.api_key_id,
            "vector_provider": row.vector_provider,
            "vector_collection": row.vector_collection,
            "vector_namespace": row.vector_namespace,
            "vector_filter": row.vector_filter,
            "embedding_provider": row.embedding_provider,
            "embedding_model": row.embedding_model,
            "embedding_dimension": row.embedding_dimension,
            "embedding_base_url": row.embedding_base_url,
            "metadata": row.metadata_json or {},
            "created_at": row.create_time,
            "updated_at": row.update_time,
        }

    @staticmethod
    def _file_row_to_dict(row: ERagFile) -> dict[str, Any]:
        return {
            "file_id": row.file_id,
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size": row.file_size,
            "status": rag_status_from_int(row.status),
            "error_code": row.error_code,
            "error_message": row.error_message,
            "metadata": row.metadata_json or {},
        }

    @staticmethod
    def _ingestion_job_row_to_dict(row: ERagIngestionJob) -> dict[str, Any]:
        return {
            "job_id": row.job_id,
            "file_set_id": row.file_set_id,
            "knowledge_base_id": row.knowledge_base_id,
            "tenant_id": row.tenant_id,
            "owner_id": row.owner_id,
            "api_key_id": row.api_key_id,
            "status": row.status,
            "stage": row.stage,
            "progress_percent": row.progress_percent,
            "retry_count": row.retry_count,
            "max_retries": row.max_retries,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "started_time": row.started_time,
            "finished_time": row.finished_time,
            "metadata": row.metadata_json or {},
            "created_at": row.create_time,
            "updated_at": row.update_time,
        }

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rag-chunk:{chunk_id}"))


rag_mysql_store = RagMySqlStore()
