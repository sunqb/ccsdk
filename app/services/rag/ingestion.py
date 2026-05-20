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
from .embeddings import EmbeddingProvider, LocalHashEmbeddingProvider
from .parser import TextDocumentParser
from .state_store import SQLiteRagStateStore
from .vector_store import LocalVectorStore, VectorStore


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
    provided, local metadata and local-vector chunks are snapshotted to SQLite
    after successful state transitions so managed knowledge bases survive
    process restarts.
    """

    def __init__(
        self,
        *,
        parser: TextDocumentParser | None = None,
        chunker: TextChunker | None = None,
        embedder: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        state_store: SQLiteRagStateStore | None = None,
    ) -> None:
        self.parser = parser or TextDocumentParser()
        self.chunker = chunker or TextChunker(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        self.embedder = embedder or LocalHashEmbeddingProvider()
        self.vector_store = vector_store or LocalVectorStore()
        self.state_store = state_store
        self._records: dict[str, FileSetRecord] = {}
        self._knowledge_bases: dict[str, KnowledgeBaseRecord] = {}
        self._ingestion_jobs: dict[str, dict[str, Any]] = {}
        self._load_state()

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

            try:
                await self._ingest_single_file(
                    record=record,
                    file_info=file_info,
                    input_file=input_file,
                    metadata=metadata or {},
                )
            except Exception as exc:  # noqa: BLE001 - capture per-file ingestion failures
                file_info.status = "failed"
                file_info.error = str(exc)
                record.errors.append(f"{input_file.filename}: {exc}")
                self._touch(record)

        self._finalize_status(record)
        self._ingestion_jobs[job_id]["status"] = "completed" if record.indexed_chunks else "failed"
        self._ingestion_jobs[job_id]["updatedAt"] = datetime.now(UTC).isoformat()
        self._persist_state()
        return UploadFileResponse(
            fileSetId=record.file_set_id,
            status=record.status,
            conversationId=record.conversation_id,
            files=record.files,
        )

    async def _ingest_single_file(
        self,
        *,
        record: FileSetRecord,
        file_info: RagFileInfo,
        input_file: IngestFile,
        metadata: dict[str, Any],
    ) -> None:
        self._touch(record, "parsing")
        file_info.status = "parsing"

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

        self._touch(record, "chunking")
        file_info.status = "chunking"
        chunks = self.chunker.chunk_document(document, source_file_id=file_info.file_id)
        if not chunks:
            raise ValueError("No indexable text content")

        self._apply_chunk_metadata(chunks, file_metadata)
        record.total_chunks += len(chunks)

        self._touch(record, "embedding")
        file_info.status = "embedding"
        embeddings = await self.embedder.embed_documents([chunk.text for chunk in chunks])

        self._touch(record, "indexing")
        file_info.status = "indexing"
        await self.vector_store.upsert_chunks(chunks, embeddings)

        record.indexed_chunks += len(chunks)
        file_info.status = "ready"
        self._touch(record)

    def get_status(self, file_set_id: str) -> RagFileSetStatusResponse:
        """Return current status for a file set."""
        record = self._records[file_set_id]
        progress = self._progress(record)
        return RagFileSetStatusResponse(
            fileSetId=record.file_set_id,
            status=record.status,
            progress=progress,
            indexedChunks=record.indexed_chunks,
            totalChunks=record.total_chunks,
            files=record.files,
            errors=record.errors,
        )

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
        """Promote an indexed file set into a persistent in-memory knowledge base."""
        record = self._records[file_set_id]
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
        return self._knowledge_base_info(kb)

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

    async def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        """Delete a persistent knowledge base and its indexed chunks."""
        kb = self._knowledge_bases.pop(knowledge_base_id)
        await self.vector_store.delete_knowledge_base(knowledge_base_id)
        record = self._records.get(kb.source_file_set_id)
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

    def _persist_state(self) -> None:
        """Persist a restart-safe snapshot when a state store is configured."""
        if self.state_store is None:
            return

        chunks: list[dict[str, Any]] = []
        if isinstance(self.vector_store, LocalVectorStore):
            chunks = self.vector_store.dump_records()

        self.state_store.save(
            {
                "version": 1,
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
        """Restore a persisted local snapshot if available."""
        if self.state_store is None:
            return

        snapshot = self.state_store.load()
        if not snapshot:
            return

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
                self.vector_store.load_records([item for item in raw_chunks if isinstance(item, dict)])

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
