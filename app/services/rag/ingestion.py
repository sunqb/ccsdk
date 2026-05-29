"""In-memory RAG ingestion service for the MVP."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...config import settings
from ...models.rag import (
    KnowledgeBaseInfo,
    RagFileInfo,
    RagFileSetStatusResponse,
    RagFileStatus,
    UploadFileResponse,
)
from .chunker import RagChunk, TextChunker
from .embedding_factory import get_embedder, get_embedding_profile, validate_dimension_compatibility
from .embeddings import EmbeddingProvider
from .parser import DocumentParser, HybridDocumentParser, LocalDocumentParser
from .state_store import SQLiteRagStateStore
from .vector_store import LocalVectorStore, VectorStore
from .vector_store_factory import get_vector_store


@dataclass(slots=True)
class IngestFile:
    """Lightweight file payload accepted by the ingestion service."""

    filename: str
    content: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileSetRecord:
    """In-memory metadata for a temporary RAG file set."""

    file_set_id: str
    conversation_id: str | None
    status: RagFileStatus
    files: list[RagFileInfo] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    errors: list[str] = field(default_factory=list)
    indexed_chunks: int = 0
    total_chunks: int = 0
    expires_at: datetime | None = None
    temporary: bool = True
    knowledge_base_id: str | None = None
    tenant_id: str | None = None
    owner_id: str | None = None
    api_key_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeBaseRecord:
    """In-memory metadata for a persistent RAG knowledge base."""

    knowledge_base_id: str
    name: str
    source_file_set_id: str
    status: str = "ready"
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str | None = None
    owner_id: str | None = None
    api_key_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RagIngestionService:
    """Parse, chunk, embed, and index temporary RAG file sets.

    Metadata is kept in memory for fast access. When ``state_store`` is
    provided in local mode, metadata and local-vector chunks are snapshotted to
    SQLite after successful state transitions so local file sets survive process
    restarts.

    When MySQL is configured (DB_DSN), production metadata is persisted to
    structured MySQL tables. SQLite is not a production metadata source of truth.
    """

    def __init__(
        self,
        *,
        parser: DocumentParser | None = None,
        chunker: TextChunker | None = None,
        embedder: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        state_store: SQLiteRagStateStore | None = None,
        mysql_store: Any | None = None,
    ) -> None:
        self.parser = parser or self._build_parser()
        self.chunker = chunker or TextChunker(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        self.embedder = embedder or self._build_embedder()
        self.vector_store = vector_store or get_vector_store()
        self.state_store = state_store
        self.mysql_store = mysql_store
        self._records: dict[str, FileSetRecord] = {}
        self._knowledge_bases: dict[str, KnowledgeBaseRecord] = {}
        self._ingestion_jobs: dict[str, dict[str, Any]] = {}
        self._pending_ingestion_payloads: dict[str, list[IngestFile]] = {}
        self._load_state()

    async def enqueue_ingestion_job(
        self,
        files: list[IngestFile | tuple[str, bytes]],
        *,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UploadFileResponse:
        """Create an ingestion job and return immediately for async HTTP uploads."""
        if len(files) > settings.rag_max_upload_files:
            raise ValueError(f"Too many files; max is {settings.rag_max_upload_files}")

        file_set_id = f"fs_{uuid4().hex}"
        job_id = f"job_{uuid4().hex}"
        normalized_files = [self._normalize_file(file) for file in files]
        for input_file in normalized_files:
            self._validate_file_size(input_file)

        record = FileSetRecord(
            file_set_id=file_set_id,
            conversation_id=conversation_id,
            status="pending",
            tenant_id=self._metadata_string(metadata or {}, "tenant_id", "tenantId"),
            owner_id=self._metadata_string(metadata or {}, "owner_id", "ownerId"),
            api_key_id=self._metadata_string(metadata or {}, "api_key_id", "apiKeyId"),
            metadata=metadata or {},
        )
        self._records[file_set_id] = record
        self._ingestion_jobs[job_id] = {
            "jobId": job_id,
            "fileSetId": file_set_id,
            "status": "pending",
            "stage": "uploaded",
            "createdAt": datetime.now(UTC).isoformat(),
        }
        self._pending_ingestion_payloads[job_id] = normalized_files
        self._touch(record, "uploaded")
        await self._persist_mysql_file_set(record)
        await self._persist_mysql_ingestion_job_create(
            job_id=job_id,
            record=record,
            status="pending",
            progress_percent=0,
        )

        for input_file in normalized_files:
            file_info = RagFileInfo(
                fileId=f"file_{uuid4().hex}",
                filename=input_file.filename,
                mimeType=None,
                size=len(input_file.content),
                status="uploaded",
            )
            record.files.append(file_info)
            await self._persist_mysql_file(record=record, file_info=file_info, input_file=input_file)

        self._persist_state()
        return UploadFileResponse(
            fileSetId=file_set_id,
            jobId=job_id,
            status=record.status,
            conversationId=conversation_id,
            files=record.files,
        )

    async def run_ingestion_job(self, job_id: str) -> None:
        """Run a queued ingestion job in-process; external queues can call the same worker hook."""
        job = self._ingestion_jobs.get(job_id)
        if not job:
            return
        file_set_id = str(job.get("fileSetId"))
        record = self._records.get(file_set_id)
        payloads = self._pending_ingestion_payloads.pop(job_id, [])
        if record is None or not payloads:
            await self._persist_mysql_ingestion_job_update(
                job_id=job_id,
                status="failed",
                stage="finalizing",
                progress_percent=0,
                error_code="job_payload_missing",
                error_message="Queued ingestion payload is not available in this worker",
            )
            return

        job["status"] = "running"
        job["stage"] = "parsing"
        job["updatedAt"] = datetime.now(UTC).isoformat()
        await self._persist_mysql_ingestion_job_update(
            job_id=job_id,
            status="running",
            stage="parsing",
            progress_percent=10,
        )

        for file_info, input_file in zip(record.files, payloads):
            try:
                await self._ingest_single_file(
                    job_id=job_id,
                    record=record,
                    file_info=file_info,
                    input_file=input_file,
                    metadata=record.metadata,
                )
            except Exception as exc:  # noqa: BLE001 - capture per-file ingestion failures
                failed_stage = file_info.status
                file_info.status = "failed"
                error_code = self._error_code_for_status(failed_stage)
                file_info.error_code = error_code
                file_info.error_message = str(exc)
                file_info.error = f"{error_code}: {exc}"
                record.errors.append(f"{input_file.filename}: {file_info.error}")
                self._touch(record)
                await self._persist_mysql_file_status(file_info)

        self._finalize_status(record)
        job_status = "succeeded" if record.status == "ready" else "partial_failed" if record.indexed_chunks else "failed"
        job["status"] = job_status
        job["stage"] = "finalizing"
        job["updatedAt"] = datetime.now(UTC).isoformat()
        await self._persist_mysql_file_set_status(record)
        await self._persist_mysql_ingestion_job_update(
            job_id=job_id,
            status=job_status,
            stage="finalizing",
            progress_percent=100 if record.indexed_chunks else 0,
            error_code="partial_failed" if record.status == "partial_ready" else None,
            error_message="; ".join(record.errors) if record.errors else None,
            metadata={**record.metadata, "errors": record.errors},
        )
        self._persist_state()

    async def ingest_files(
        self,
        files: list[IngestFile | tuple[str, bytes]],
        *,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UploadFileResponse:
        """Ingest files and return the final file set status.

        This MVP implementation performs ingestion inline and stores metadata in
        memory. A later router can wrap this call in BackgroundTasks if needed.
        """
        if len(files) > settings.rag_max_upload_files:
            raise ValueError(f"Too many files; max is {settings.rag_max_upload_files}")

        file_set_id = f"fs_{uuid4().hex}"
        job_id = f"job_{uuid4().hex}"
        record = FileSetRecord(
            file_set_id=file_set_id,
            conversation_id=conversation_id,
            status="pending",
            tenant_id=self._metadata_string(metadata or {}, "tenant_id", "tenantId"),
            owner_id=self._metadata_string(metadata or {}, "owner_id", "ownerId"),
            api_key_id=self._metadata_string(metadata or {}, "api_key_id", "apiKeyId"),
            metadata=metadata or {},
        )
        self._records[file_set_id] = record
        self._ingestion_jobs[job_id] = {
            "jobId": job_id,
            "fileSetId": file_set_id,
            "status": "running",
            "createdAt": datetime.now(UTC).isoformat(),
        }
        self._touch(record, "uploaded")
        await self._persist_mysql_file_set(record)
        await self._persist_mysql_ingestion_job_create(job_id=job_id, record=record)

        normalized_files = [self._normalize_file(file) for file in files]
        for input_file in normalized_files:
            self._validate_file_size(input_file)
            file_id = f"file_{uuid4().hex}"
            file_info = RagFileInfo(
                fileId=file_id,
                filename=input_file.filename,
                mimeType=None,
                size=len(input_file.content),
                status="uploaded",
            )
            record.files.append(file_info)
            await self._persist_mysql_file(record=record, file_info=file_info, input_file=input_file)

            try:
                await self._ingest_single_file(
                    job_id=job_id,
                    record=record,
                    file_info=file_info,
                    input_file=input_file,
                    metadata=metadata or {},
                )
            except Exception as exc:  # noqa: BLE001 - capture per-file ingestion failures
                failed_stage = file_info.status
                file_info.status = "failed"
                error_code = self._error_code_for_status(failed_stage)
                file_info.error_code = error_code
                file_info.error_message = str(exc)
                file_info.error = f"{error_code}: {exc}"
                record.errors.append(f"{input_file.filename}: {file_info.error}")
                self._touch(record)
                await self._persist_mysql_file_status(file_info)

        self._finalize_status(record)
        job_status = "succeeded" if record.status == "ready" else "partial_failed" if record.indexed_chunks else "failed"
        self._ingestion_jobs[job_id]["status"] = job_status
        self._ingestion_jobs[job_id]["updatedAt"] = datetime.now(UTC).isoformat()
        await self._persist_mysql_file_set_status(record)
        await self._persist_mysql_ingestion_job_update(
            job_id=job_id,
            status=job_status,
            stage="finalizing",
            progress_percent=100 if record.indexed_chunks else 0,
            error_code="partial_failed" if record.status == "partial_ready" else None,
            error_message="; ".join(record.errors) if record.errors else None,
            metadata={**record.metadata, "errors": record.errors},
        )
        self._persist_state()
        return UploadFileResponse(
            fileSetId=record.file_set_id,
            jobId=job_id,
            status=record.status,
            conversationId=record.conversation_id,
            files=record.files,
        )

    async def _ingest_single_file(
        self,
        *,
        job_id: str,
        record: FileSetRecord,
        file_info: RagFileInfo,
        input_file: IngestFile,
        metadata: dict[str, Any],
    ) -> None:
        self._touch(record, "parsing")
        await self._persist_mysql_ingestion_job_update(job_id=job_id, stage="parsing", progress_percent=20)
        file_info.status = "parsing"
        await self._persist_mysql_file_status(file_info)

        file_metadata = {
            **metadata,
            **input_file.metadata,
            "file_set_id": record.file_set_id,
            "fileSetId": record.file_set_id,
            "file_id": file_info.file_id,
            "fileId": file_info.file_id,
            "source_file_id": file_info.file_id,
            "sourceFileId": file_info.file_id,
            "conversation_id": record.conversation_id,
            "conversationId": record.conversation_id,
        }
        document = self.parser.parse_bytes(
            input_file.content,
            filename=input_file.filename,
            metadata=file_metadata,
        )
        file_info.mime_type = document.mime_type
        await self._persist_mysql_file_status(file_info)

        self._touch(record, "chunking")
        await self._persist_mysql_ingestion_job_update(job_id=job_id, stage="chunking", progress_percent=40)
        file_info.status = "chunking"
        await self._persist_mysql_file_status(file_info)
        chunks = self.chunker.chunk_document(document, source_file_id=file_info.file_id)
        if not chunks:
            raise ValueError("No indexable text content")

        self._apply_chunk_metadata(chunks, file_metadata)
        record.total_chunks += len(chunks)
        await self._persist_mysql_file_set_status(record)

        self._touch(record, "embedding")
        await self._persist_mysql_ingestion_job_update(job_id=job_id, stage="embedding", progress_percent=60)
        file_info.status = "embedding"
        await self._persist_mysql_file_status(file_info)
        embeddings = await self.embedder.embed_documents([chunk.text for chunk in chunks])

        self._touch(record, "indexing")
        await self._persist_mysql_ingestion_job_update(job_id=job_id, stage="indexing", progress_percent=80)
        file_info.status = "indexing"
        await self._persist_mysql_file_status(file_info)
        await self.vector_store.upsert_chunks(chunks, embeddings)
        await self._persist_mysql_chunks(chunks)

        record.indexed_chunks += len(chunks)
        file_info.status = "ready"
        self._touch(record)
        await self._persist_mysql_file_status(file_info)
        await self._persist_mysql_file_set_status(record)

    def get_status(self, file_set_id: str) -> RagFileSetStatusResponse:
        """Return current status for a file set."""
        record = self._records[file_set_id]
        progress = self._progress(record)
        return RagFileSetStatusResponse(
            fileSetId=record.file_set_id,
            jobId=self._job_id_for_file_set(record.file_set_id),
            status=record.status,
            progress=progress,
            indexedChunks=record.indexed_chunks,
            totalChunks=record.total_chunks,
            files=record.files,
            errors=record.errors,
        )

    async def get_status_async(self, file_set_id: str) -> RagFileSetStatusResponse:
        """Return file-set status, preferring MySQL metadata when available."""
        if self.mysql_store is not None:
            mysql_status = await self.mysql_store.get_file_set_status(file_set_id)
            if mysql_status is not None:
                return self._file_set_status_from_mysql(mysql_status)
        return self.get_status(file_set_id)

    async def get_ingestion_job(self, job_id: str) -> dict[str, Any] | None:
        """Return one ingestion-job state, preferring MySQL when available."""
        if self.mysql_store is not None and hasattr(self.mysql_store, "get_ingestion_job"):
            job = await self.mysql_store.get_ingestion_job(job_id)
            if job is not None:
                return job
        for job in self._ingestion_jobs.values():
            if job.get("jobId") == job_id:
                return dict(job)
        return None

    async def retry_ingestion_job(self, job_id: str) -> dict[str, Any] | None:
        """Mark a failed job as queued for retry; worker execution lands in P3 queue backends."""
        job = await self.get_ingestion_job(job_id)
        if job is None:
            return None
        current_status = str(job.get("status") or "")
        if current_status not in {"failed", "partial_failed", "cancelled"}:
            raise ValueError(f"Job is not retryable: {current_status}")
        retry_count = int(job.get("retry_count") or job.get("retryCount") or 0) + 1
        if self.mysql_store is not None and hasattr(self.mysql_store, "update_ingestion_job"):
            await self.mysql_store.update_ingestion_job(
                job_id=job_id,
                status="pending",
                stage="retry_queued",
                progress_percent=0,
                retry_count=retry_count,
                metadata={**dict(job.get("metadata") or {}), "retryRequested": True},
            )
        if job_id in self._ingestion_jobs:
            self._ingestion_jobs[job_id].update(
                {"status": "pending", "stage": "retry_queued", "retryCount": retry_count}
            )
        return await self.get_ingestion_job(job_id)

    async def cancel_ingestion_job(self, job_id: str) -> dict[str, Any] | None:
        """Mark an ingestion job cancelled when it has not already finished."""
        job = await self.get_ingestion_job(job_id)
        if job is None:
            return None
        current_status = str(job.get("status") or "")
        if current_status in {"succeeded", "partial_failed", "failed", "cancelled"}:
            return job
        if self.mysql_store is not None and hasattr(self.mysql_store, "update_ingestion_job"):
            await self.mysql_store.update_ingestion_job(
                job_id=job_id,
                status="cancelled",
                stage="cancelled",
                progress_percent=int(job.get("progress_percent") or job.get("progressPercent") or 0),
            )
        if job_id in self._ingestion_jobs:
            self._ingestion_jobs[job_id].update({"status": "cancelled", "stage": "cancelled"})
        return await self.get_ingestion_job(job_id)

    def get_vector_store(self) -> VectorStore:
        """Expose the vector store for retrieval services."""
        return self.vector_store

    def get_stats(self) -> dict[str, Any]:
        """Return local RAG accounting and operational stats."""
        total_files = sum(len(record.files) for record in self._records.values())
        failed_files = sum(
            1 for record in self._records.values() for file in record.files if file.status == "failed"
        )
        return {
            "fileSets": len(self._records),
            "knowledgeBases": len(self._knowledge_bases),
            "files": total_files,
            "failedFiles": failed_files,
            "indexedChunks": sum(record.indexed_chunks for record in self._records.values()),
            "totalChunks": sum(record.total_chunks for record in self._records.values()),
            "activeJobs": sum(1 for job in self._ingestion_jobs.values() if job["status"] == "running"),
            "jobs": len(self._ingestion_jobs),
            "provider": settings.rag_vector_provider,
            "stateStore": "sqlite" if self.state_store else "memory",
        }

    async def create_knowledge_base_from_file_set(
        self,
        *,
        file_set_id: str,
        name: str,
        description: str | None = None,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeBaseInfo:
        """Promote an indexed file set into a persistent knowledge base.

        Production deployments can run multiple workers or restart between upload
        and promotion, so MySQL metadata is used as fallback when process-local
        state does not contain the file set.
        """
        record = self._records.get(file_set_id)
        if record is None and self.mysql_store is not None:
            mysql_record = await self.mysql_store.get_file_set_metadata(file_set_id)
            if mysql_record is not None:
                record = FileSetRecord(
                    file_set_id=file_set_id,
                    conversation_id=mysql_record.get("conversation_id"),
                    status=mysql_record.get("status") or "pending",
                    created_at=mysql_record.get("created_at") or datetime.now(UTC),
                    updated_at=mysql_record.get("updated_at") or datetime.now(UTC),
                    indexed_chunks=int(mysql_record.get("indexed_chunks") or 0),
                    total_chunks=int(mysql_record.get("total_chunks") or 0),
                    expires_at=mysql_record.get("expires_time"),
                    temporary=bool(mysql_record.get("temporary", True)),
                    knowledge_base_id=mysql_record.get("knowledge_base_id"),
                    tenant_id=mysql_record.get("tenant_id"),
                    owner_id=mysql_record.get("owner_id"),
                    api_key_id=mysql_record.get("api_key_id"),
                    metadata=mysql_record.get("metadata") or {},
                )
                self._records[file_set_id] = record
        if record is None:
            raise KeyError(file_set_id)
        if record.status not in {"ready", "partial_ready"} or record.indexed_chunks <= 0:
            raise ValueError("File set is not ready for knowledge base creation")

        knowledge_base_id = f"kb_{uuid4().hex}"
        now = datetime.now(UTC)
        resolved_metadata = metadata or {}
        resolved_tenant_id = tenant_id or record.tenant_id
        resolved_owner_id = owner_id or record.owner_id
        resolved_api_key_id = api_key_id or record.api_key_id
        chunk_metadata = {
            "tenant_id": resolved_tenant_id,
            "tenantId": resolved_tenant_id,
            "owner_id": resolved_owner_id,
            "ownerId": resolved_owner_id,
            "api_key_id": resolved_api_key_id,
            "apiKeyId": resolved_api_key_id,
        }
        tagged_chunks = await self.vector_store.tag_file_set_as_knowledge_base(
            file_set_id=file_set_id,
            knowledge_base_id=knowledge_base_id,
            metadata={key: value for key, value in chunk_metadata.items() if value is not None},
        )
        if tagged_chunks <= 0:
            raise ValueError("File set has no indexed chunks")

        kb = KnowledgeBaseRecord(
            knowledge_base_id=knowledge_base_id,
            name=name,
            description=description,
            source_file_set_id=file_set_id,
            created_at=now,
            updated_at=now,
            tenant_id=resolved_tenant_id,
            owner_id=resolved_owner_id,
            api_key_id=resolved_api_key_id,
            metadata=resolved_metadata,
        )
        self._knowledge_bases[knowledge_base_id] = kb
        record.temporary = False
        record.knowledge_base_id = knowledge_base_id
        record.tenant_id = resolved_tenant_id
        record.owner_id = resolved_owner_id
        record.api_key_id = resolved_api_key_id
        record.updated_at = now
        self._persist_state()

        # MySQL 持久化
        if self.mysql_store is not None:
            try:
                await self.mysql_store.save_knowledge_base(
                    knowledge_base_id=knowledge_base_id,
                    name=name,
                    source_file_set_id=file_set_id,
                    status="ready",
                    description=description,
                    tenant_id=resolved_tenant_id,
                    owner_id=resolved_owner_id,
                    api_key_id=resolved_api_key_id,
                    vector_provider=settings.rag_vector_provider,
                    vector_collection=self._vector_collection_name(),
                    embedding_provider=get_embedding_profile().provider,
                    embedding_model=get_embedding_profile().model,
                    embedding_dimension=get_embedding_profile().dimension,
                    embedding_base_url=get_embedding_profile().base_url,
                    metadata=resolved_metadata,
                )
                await self.mysql_store.update_file_set_kb_binding(file_set_id, knowledge_base_id)
                await self.mysql_store.update_chunks_knowledge_base(
                    file_set_id=file_set_id,
                    knowledge_base_id=knowledge_base_id,
                    metadata={key: value for key, value in chunk_metadata.items() if value is not None},
                )
            except Exception as exc:
                print(f"[RAG] MySQL persist knowledge base warning: {exc}")

        return self._knowledge_base_info(kb)

    async def get_knowledge_base_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> KnowledgeBaseInfo | None:
        """按名称查找知识库。优先查 MySQL，回退查内存。"""
        if self.mysql_store is not None:
            kb_dict = await self.mysql_store.get_knowledge_base_by_name(
                name, tenant_id=tenant_id, owner_id=owner_id, api_key_id=api_key_id,
            )
            if kb_dict is not None:
                return KnowledgeBaseInfo(
                    knowledgeBaseId=kb_dict["knowledge_base_id"],
                    name=kb_dict["name"],
                    description=kb_dict.get("description"),
                    sourceFileSetId=kb_dict["source_file_set_id"],
                    status=kb_dict.get("status", "ready"),
                    createdAt=kb_dict.get("created_at") or datetime.now(UTC),
                    updatedAt=kb_dict.get("updated_at") or datetime.now(UTC),
                    tenantId=kb_dict.get("tenant_id"),
                    ownerId=kb_dict.get("owner_id"),
                    apiKeyId=kb_dict.get("api_key_id"),
                    metadata=kb_dict.get("metadata") or {},
                )

        for kb in self._knowledge_bases.values():
            if kb.name != name:
                continue
            if tenant_id is not None and kb.tenant_id != tenant_id:
                continue
            if owner_id is not None and kb.owner_id != owner_id:
                continue
            if api_key_id is not None and kb.api_key_id != api_key_id:
                continue
            return self._knowledge_base_info(kb)
        return None

    async def check_name_conflict(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
    ) -> bool:
        """检查同作用域下知识库名称是否冲突。"""
        if self.mysql_store is not None:
            exists = await self.mysql_store.check_name_exists(
                name, tenant_id=tenant_id, owner_id=owner_id,
            )
            if exists:
                return True

        for kb in self._knowledge_bases.values():
            if kb.name == name:
                if tenant_id is not None and kb.tenant_id != tenant_id:
                    continue
                if owner_id is not None and kb.owner_id != owner_id:
                    continue
                return True
        return False

    async def resolve_knowledge_base_names(
        self,
        names: list[str],
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """解析知识库名称为 (name, knowledge_base_id) 列表。

        Raises ValueError 如果任何名称不存在。
        """
        results: list[tuple[str, str]] = []
        for name in names:
            kb_info = await self.get_knowledge_base_by_name(
                name, tenant_id=tenant_id, owner_id=owner_id, api_key_id=api_key_id,
            )
            if kb_info is None:
                raise ValueError(f"Knowledge base name not found: {name}")
            results.append((name, kb_info.knowledge_base_id))
        return results

    def list_knowledge_bases(
        self,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> list[KnowledgeBaseInfo]:
        """List persistent knowledge bases, optionally filtered by permission metadata."""
        records = list(self._knowledge_bases.values())
        if tenant_id is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        if owner_id is not None:
            records = [record for record in records if record.owner_id == owner_id]
        if api_key_id is not None:
            records = [record for record in records if record.api_key_id == api_key_id]
        return [self._knowledge_base_info(record) for record in records]

    async def list_knowledge_bases_async(
        self,
        *,
        tenant_id: str | None = None,
        owner_id: str | None = None,
        api_key_id: str | None = None,
    ) -> list[KnowledgeBaseInfo]:
        """List knowledge bases, preferring MySQL metadata when available."""
        if self.mysql_store is not None:
            rows = await self.mysql_store.list_knowledge_bases(
                tenant_id=tenant_id,
                owner_id=owner_id,
                api_key_id=api_key_id,
            )
            return [self._knowledge_base_info_from_mysql(row) for row in rows]
        return self.list_knowledge_bases(
            tenant_id=tenant_id,
            owner_id=owner_id,
            api_key_id=api_key_id,
        )

    async def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        """Delete a persistent knowledge base and its indexed chunks."""
        kb = self._knowledge_bases.pop(knowledge_base_id, None)
        kb_source_file_set_id: str | None = kb.source_file_set_id if kb else None
        if kb is None and self.mysql_store is not None:
            kb_dict = await self.mysql_store.get_knowledge_base_by_id(knowledge_base_id)
            if kb_dict is None:
                raise KeyError(knowledge_base_id)
            kb_source_file_set_id = kb_dict.get("source_file_set_id")
        elif kb is None:
            raise KeyError(knowledge_base_id)

        await self.vector_store.delete_knowledge_base(knowledge_base_id)
        if self.mysql_store is not None:
            await self.mysql_store.delete_knowledge_base(knowledge_base_id)
        record = self._records.get(kb_source_file_set_id or "")
        if record and record.knowledge_base_id == knowledge_base_id:
            record.knowledge_base_id = None
            record.temporary = True
            self._touch(record)
        self._persist_state()

    async def cleanup_expired_file_sets(self, now: datetime | None = None) -> int:
        """Delete expired temporary file sets and their chunks."""
        current_time = now or datetime.now(UTC)
        expired_ids = [
            record.file_set_id
            for record in self._records.values()
            if record.temporary
            and record.knowledge_base_id is None
            and record.expires_at is not None
            and record.expires_at <= current_time
        ]
        for file_set_id in expired_ids:
            await self.vector_store.delete_file_set(file_set_id)
            self._records.pop(file_set_id, None)
        if expired_ids:
            self._persist_state()
        return len(expired_ids)

    async def _persist_mysql_file_set(self, record: FileSetRecord) -> None:
        """Persist initial file-set metadata when MySQL is available."""
        if self.mysql_store is None:
            return
        try:
            await self.mysql_store.save_file_set(
                file_set_id=record.file_set_id,
                conversation_id=record.conversation_id,
                status=record.status,
                indexed_chunks=record.indexed_chunks,
                total_chunks=record.total_chunks,
                temporary=record.temporary,
                knowledge_base_id=record.knowledge_base_id,
                tenant_id=record.tenant_id,
                owner_id=record.owner_id,
                api_key_id=record.api_key_id,
                metadata=record.metadata,
                expires_time=record.expires_at,
            )
        except Exception as exc:
            print(f"[RAG] MySQL persist file set warning: {exc}")

    async def _persist_mysql_file_set_status(self, record: FileSetRecord) -> None:
        """Persist file-set status/counter transitions when MySQL is available."""
        if self.mysql_store is None:
            return
        try:
            await self.mysql_store.update_file_set_status(
                file_set_id=record.file_set_id,
                status=record.status,
                indexed_chunks=record.indexed_chunks,
                total_chunks=record.total_chunks,
                temporary=record.temporary,
                knowledge_base_id=record.knowledge_base_id,
                metadata=record.metadata,
            )
        except Exception as exc:
            print(f"[RAG] MySQL update file set warning: {exc}")

    async def _persist_mysql_ingestion_job_create(
        self,
        *,
        job_id: str,
        record: FileSetRecord,
        status: str = "running",
        progress_percent: int = 5,
    ) -> None:
        """Persist initial ingestion-job metadata when MySQL is available."""
        if self.mysql_store is None or not hasattr(self.mysql_store, "create_ingestion_job"):
            return
        try:
            await self.mysql_store.create_ingestion_job(
                job_id=job_id,
                file_set_id=record.file_set_id,
                knowledge_base_id=record.knowledge_base_id,
                tenant_id=record.tenant_id,
                owner_id=record.owner_id,
                api_key_id=record.api_key_id,
                status=status,
                stage="uploaded",
                progress_percent=progress_percent,
                metadata=record.metadata,
            )
        except Exception as exc:
            print(f"[RAG] MySQL create ingestion job warning: {exc}")

    async def _persist_mysql_ingestion_job_update(
        self,
        *,
        job_id: str,
        status: str | None = None,
        stage: str | None = None,
        progress_percent: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist ingestion-job state transitions when MySQL is available."""
        if self.mysql_store is None or not hasattr(self.mysql_store, "update_ingestion_job"):
            return
        try:
            await self.mysql_store.update_ingestion_job(
                job_id=job_id,
                status=status,
                stage=stage,
                progress_percent=progress_percent,
                error_code=error_code,
                error_message=error_message,
                metadata=metadata,
            )
        except Exception as exc:
            print(f"[RAG] MySQL update ingestion job warning: {exc}")

    async def _persist_mysql_file(
        self,
        *,
        record: FileSetRecord,
        file_info: RagFileInfo,
        input_file: IngestFile,
    ) -> None:
        """Persist uploaded source-file metadata when MySQL is available."""
        if self.mysql_store is None:
            return
        try:
            await self.mysql_store.save_file(
                file_id=file_info.file_id,
                file_set_id=record.file_set_id,
                filename=file_info.filename,
                mime_type=file_info.mime_type,
                file_size=file_info.size,
                status=file_info.status,
                metadata={**record.metadata, **input_file.metadata},
            )
        except Exception as exc:
            print(f"[RAG] MySQL persist file warning: {exc}")

    async def _persist_mysql_file_status(self, file_info: RagFileInfo) -> None:
        """Persist source-file processing status transitions when MySQL is available."""
        if self.mysql_store is None:
            return
        try:
            await self.mysql_store.update_file_status(
                file_id=file_info.file_id,
                status=file_info.status,
                mime_type=file_info.mime_type,
                error_code=file_info.error_code,
                error_message=file_info.error_message,
            )
        except Exception as exc:
            print(f"[RAG] MySQL update file warning: {exc}")

    async def _persist_mysql_chunks(self, chunks: list[RagChunk]) -> None:
        """Persist chunk metadata after vector indexing succeeds."""
        if self.mysql_store is None or not chunks:
            return
        profile = get_embedding_profile()
        try:
            await self.mysql_store.save_chunks(
                chunks=chunks,
                vector_provider=settings.rag_vector_provider,
                vector_collection=self._vector_collection_name(),
                embedding_provider=profile.provider,
                embedding_model=profile.model,
                embedding_dimension=profile.dimension,
            )
        except Exception as exc:
            print(f"[RAG] MySQL persist chunks warning: {exc}")

    @staticmethod
    def _vector_collection_name() -> str | None:
        if settings.rag_vector_provider == "qdrant":
            return settings.rag_qdrant_collection
        return None

    def _persist_state(self) -> None:
        """Persist a restart-safe snapshot when a state store is configured."""
        if self.state_store is None:
            return

        chunks: list[dict[str, Any]] = []
        if isinstance(self.vector_store, LocalVectorStore):
            chunks = self.vector_store.dump_records()

        profile = get_embedding_profile()
        self.state_store.save(
            {
                "version": 2,
                "embeddingProfile": {
                    "provider": profile.provider,
                    "model": profile.model,
                    "dimension": profile.dimension,
                    "base_url": profile.base_url,
                },
                "fileSets": [self._file_set_record_payload(record) for record in self._records.values()],
                "knowledgeBases": [
                    self._knowledge_base_record_payload(record)
                    for record in self._knowledge_bases.values()
                ],
                "ingestionJobs": list(self._ingestion_jobs.values()),
                "chunks": chunks,
            }
        )

    def _load_state(self) -> None:
        """Restore a persisted local snapshot if available.

        加载时校验嵌入模型维度一致性：如果 snapshot 中记录的维度与当前
        embedder 不匹配，清除旧向量数据并打印警告（而非静默降级）。
        """
        if self.state_store is None:
            return

        snapshot = self.state_store.load()
        if not snapshot:
            return

        # ---- 偏差检测：校验嵌入模型一致性 ----
        stored_profile = snapshot.get("embeddingProfile")
        if stored_profile and isinstance(stored_profile, dict):
            stored_dimension = stored_profile.get("dimension")
            if stored_dimension is not None:
                warnings = validate_dimension_compatibility(stored_dimension)
                for warning in warnings:
                    print(f"[RAG WARNING] {warning}")

        self._records = {
            record.file_set_id: record
            for record in (
                self._file_set_record_from_payload(item)
                for item in snapshot.get("fileSets", [])
                if isinstance(item, dict)
            )
        }
        self._knowledge_bases = {
            record.knowledge_base_id: record
            for record in (
                self._knowledge_base_record_from_payload(item)
                for item in snapshot.get("knowledgeBases", [])
                if isinstance(item, dict)
            )
        }
        self._ingestion_jobs = {
            str(item["jobId"]): dict(item)
            for item in snapshot.get("ingestionJobs", [])
            if isinstance(item, dict) and item.get("jobId")
        }
        if isinstance(self.vector_store, LocalVectorStore):
            raw_chunks = snapshot.get("chunks", [])
            if isinstance(raw_chunks, list):
                # 维度不匹配时跳过加载旧向量
                profile = get_embedding_profile()
                skip_vectors = False
                if stored_profile and isinstance(stored_profile, dict):
                    stored_dim = stored_profile.get("dimension")
                    if stored_dim is not None and stored_dim != profile.dimension:
                        skip_vectors = True
                        print(
                            f"[RAG WARNING] Skipping {len(raw_chunks)} stored vectors "
                            f"(stored dimension {stored_dim} != current {profile.dimension}). "
                            f"Please re-ingest documents with the current embedding provider."
                        )
                if skip_vectors:
                    self.vector_store.load_records([])
                else:
                    self.vector_store.load_records([item for item in raw_chunks if isinstance(item, dict)])

    def _build_parser(self) -> DocumentParser:
        """Build the document parser based on RAG_PARSER_PROVIDER setting."""
        provider = settings.rag_parser_provider
        if provider == "mineru":
            return HybridDocumentParser(
                mineru_base_url=settings.mineru_base_url,
                mineru_api_key=settings.mineru_api_key,
                mineru_timeout_seconds=settings.mineru_timeout_seconds,
                mineru_fallback_to_local=settings.mineru_fallback_to_local,
            )
        if provider == "local":
            return LocalDocumentParser()
        raise ValueError(f"Unsupported RAG_PARSER_PROVIDER: {provider}")

    @staticmethod
    def _build_embedder() -> EmbeddingProvider:
        """通过嵌入工厂获取全局单例 embedder。"""
        return get_embedder()

    @staticmethod
    def _error_code_for_status(status: RagFileStatus) -> str:
        if status == "parsing":
            return "parse_failed"
        if status == "chunking":
            return "chunk_failed"
        if status == "embedding":
            return "embedding_failed"
        if status == "indexing":
            return "index_failed"
        return "ingestion_failed"

    @staticmethod
    def _normalize_file(file: IngestFile | tuple[str, bytes]) -> IngestFile:
        if isinstance(file, IngestFile):
            return file

        filename, content = file
        return IngestFile(filename=filename, content=content)

    @staticmethod
    def _validate_file_size(file: IngestFile) -> None:
        max_bytes = settings.rag_max_upload_size_mb * 1024 * 1024
        if len(file.content) > max_bytes:
            raise ValueError(
                f"File {file.filename} exceeds max size "
                f"{settings.rag_max_upload_size_mb} MB"
            )

    @staticmethod
    def _apply_chunk_metadata(chunks: list[RagChunk], metadata: dict[str, Any]) -> None:
        for chunk in chunks:
            chunk.metadata.update(metadata)

    @staticmethod
    def _file_set_record_payload(record: FileSetRecord) -> dict[str, Any]:
        return {
            "fileSetId": record.file_set_id,
            "conversationId": record.conversation_id,
            "status": record.status,
            "files": [file.model_dump(by_alias=True) for file in record.files],
            "createdAt": record.created_at.isoformat(),
            "updatedAt": record.updated_at.isoformat(),
            "errors": record.errors,
            "indexedChunks": record.indexed_chunks,
            "totalChunks": record.total_chunks,
            "expiresAt": record.expires_at.isoformat() if record.expires_at else None,
            "temporary": record.temporary,
            "knowledgeBaseId": record.knowledge_base_id,
            "tenantId": record.tenant_id,
            "ownerId": record.owner_id,
            "apiKeyId": record.api_key_id,
            "metadata": record.metadata,
        }

    @classmethod
    def _file_set_record_from_payload(cls, payload: dict[str, Any]) -> FileSetRecord:
        return FileSetRecord(
            file_set_id=str(payload["fileSetId"]),
            conversation_id=payload.get("conversationId"),
            status=payload.get("status", "failed"),
            files=[RagFileInfo(**item) for item in payload.get("files", []) if isinstance(item, dict)],
            created_at=cls._parse_datetime(payload.get("createdAt")),
            updated_at=cls._parse_datetime(payload.get("updatedAt")),
            errors=list(payload.get("errors") or []),
            indexed_chunks=int(payload.get("indexedChunks") or 0),
            total_chunks=int(payload.get("totalChunks") or 0),
            expires_at=cls._parse_optional_datetime(payload.get("expiresAt")),
            temporary=bool(payload.get("temporary", True)),
            knowledge_base_id=payload.get("knowledgeBaseId"),
            tenant_id=payload.get("tenantId"),
            owner_id=payload.get("ownerId"),
            api_key_id=payload.get("apiKeyId"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _knowledge_base_record_payload(record: KnowledgeBaseRecord) -> dict[str, Any]:
        return {
            "knowledgeBaseId": record.knowledge_base_id,
            "name": record.name,
            "sourceFileSetId": record.source_file_set_id,
            "status": record.status,
            "description": record.description,
            "createdAt": record.created_at.isoformat(),
            "updatedAt": record.updated_at.isoformat(),
            "tenantId": record.tenant_id,
            "ownerId": record.owner_id,
            "apiKeyId": record.api_key_id,
            "metadata": record.metadata,
        }

    @classmethod
    def _knowledge_base_record_from_payload(cls, payload: dict[str, Any]) -> KnowledgeBaseRecord:
        return KnowledgeBaseRecord(
            knowledge_base_id=str(payload["knowledgeBaseId"]),
            name=str(payload.get("name") or "Untitled"),
            source_file_set_id=str(payload["sourceFileSetId"]),
            status=str(payload.get("status") or "ready"),
            description=payload.get("description"),
            created_at=cls._parse_datetime(payload.get("createdAt")),
            updated_at=cls._parse_datetime(payload.get("updatedAt")),
            tenant_id=payload.get("tenantId"),
            owner_id=payload.get("ownerId"),
            api_key_id=payload.get("apiKeyId"),
            metadata=dict(payload.get("metadata") or {}),
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        parsed = RagIngestionService._parse_optional_datetime(value)
        return parsed or datetime.now(UTC)

    @staticmethod
    def _parse_optional_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _knowledge_base_info(record: KnowledgeBaseRecord) -> KnowledgeBaseInfo:
        return KnowledgeBaseInfo(
            knowledgeBaseId=record.knowledge_base_id,
            name=record.name,
            description=record.description,
            sourceFileSetId=record.source_file_set_id,
            status=record.status,
            createdAt=record.created_at,
            updatedAt=record.updated_at,
            tenantId=record.tenant_id,
            ownerId=record.owner_id,
            apiKeyId=record.api_key_id,
            metadata=record.metadata,
        )

    @staticmethod
    def _knowledge_base_info_from_mysql(payload: dict[str, Any]) -> KnowledgeBaseInfo:
        return KnowledgeBaseInfo(
            knowledgeBaseId=payload["knowledge_base_id"],
            name=payload["name"],
            description=payload.get("description"),
            sourceFileSetId=payload["source_file_set_id"],
            status=payload.get("status", "ready"),
            createdAt=payload.get("created_at") or datetime.now(UTC),
            updatedAt=payload.get("updated_at") or datetime.now(UTC),
            tenantId=payload.get("tenant_id"),
            ownerId=payload.get("owner_id"),
            apiKeyId=payload.get("api_key_id"),
            metadata=payload.get("metadata") or {},
        )

    @staticmethod
    def _file_set_status_from_mysql(payload: dict[str, Any]) -> RagFileSetStatusResponse:
        status = payload.get("status", "failed")
        indexed_chunks = int(payload.get("indexed_chunks") or 0)
        total_chunks = int(payload.get("total_chunks") or 0)
        if status == "ready":
            progress = 100
        elif status == "failed":
            progress = 0
        elif total_chunks:
            progress = min(99, int(indexed_chunks / total_chunks * 100))
        else:
            progress = 0
        files = [
            RagFileInfo(
                fileId=file_payload["file_id"],
                filename=file_payload["filename"],
                mimeType=file_payload.get("mime_type"),
                size=int(file_payload.get("size") or 0),
                status=file_payload.get("status", "failed"),
                errorCode=file_payload.get("error_code"),
                errorMessage=file_payload.get("error_message"),
            )
            for file_payload in payload.get("files", [])
            if isinstance(file_payload, dict)
        ]
        errors = [file.error_message or file.error for file in files if file.status == "failed"]
        return RagFileSetStatusResponse(
            fileSetId=payload["file_set_id"],
            jobId=payload.get("job_id"),
            status=status,
            progress=progress,
            indexedChunks=indexed_chunks,
            totalChunks=total_chunks,
            files=files,
            errors=[error for error in errors if error],
        )

    @staticmethod
    def _metadata_string(metadata: dict[str, Any], snake_key: str, camel_key: str) -> str | None:
        value = metadata.get(snake_key) or metadata.get(camel_key)
        return str(value) if value is not None else None

    @staticmethod
    def _touch(record: FileSetRecord, status: RagFileStatus | None = None) -> None:
        if status is not None:
            record.status = status
        record.updated_at = datetime.now(UTC)

    @staticmethod
    def _progress(record: FileSetRecord) -> int:
        if record.status == "ready":
            return 100
        if record.status == "failed":
            return 0
        if record.total_chunks:
            return min(99, int(record.indexed_chunks / record.total_chunks * 100))
        return 0

    def _job_id_for_file_set(self, file_set_id: str) -> str | None:
        for job in self._ingestion_jobs.values():
            if job.get("fileSetId") == file_set_id:
                value = job.get("jobId")
                return str(value) if value is not None else None
        return None

    def _finalize_status(self, record: FileSetRecord) -> None:
        if record.indexed_chunks > 0 and record.errors:
            self._touch(record, "partial_ready")
        elif record.indexed_chunks > 0:
            self._touch(record, "ready")
        else:
            self._touch(record, "failed")


rag_ingestion_service = RagIngestionService(
    state_store=SQLiteRagStateStore(Path(settings.rag_storage_dir) / "rag.db")
)


def set_mysql_store_for_ingestion(mysql_store: Any) -> None:
    """注入 MySQL 持久化存储到全局 ingestion service 实例。"""
    rag_ingestion_service.mysql_store = mysql_store
