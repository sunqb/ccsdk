"""
RAG MySQL 持久化存储。

当 RAG_DB_DSN 配置时，知识库元数据写入 MySQL 结构化表；
否则回退到 SQLite JSON snapshot。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update, and_, func, literal
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import (
    ERagFileSet,
    ERagKnowledgeBase,
    kb_status_from_int,
    kb_status_to_int,
    get_session_factory,
    is_mysql_available,
)


class RagMySqlStore:
    """MySQL 持久化存储 for RAG knowledge base metadata."""

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
    ) -> None:
        factory = get_session_factory()
        if factory is None:
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
            "metadata": row.metadata_json or {},
            "created_at": row.create_time,
            "updated_at": row.update_time,
        }


rag_mysql_store = RagMySqlStore()
