"""Local productionization helpers for RAG services."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(slots=True)
class RagConcurrencyGuard:
    """Small in-process concurrency limiter for deterministic local tests."""

    limit: int
    active: int = 0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self.limit > 0 and self.active >= self.limit:
            raise RuntimeError("RAG concurrency limit exceeded")

        self.active += 1
        try:
            yield
        finally:
            self.active = max(0, self.active - 1)


def build_provider_info(
    *,
    active_provider: str,
    qdrant_url: str | None = None,
    qdrant_collection: str | None = None,
    qdrant_create_collection: bool | None = None,
    pgvector_dsn: str | None = None,
    milvus_uri: str | None = None,
) -> dict[str, object]:
    """Return configured vector-provider capabilities without connecting externally."""
    providers = [
        {
            "name": "local",
            "available": True,
            "configured": True,
            "active": active_provider == "local",
            "mode": "in_memory",
        },
        {
            "name": "qdrant",
            "available": bool(qdrant_url),
            "configured": bool(qdrant_url),
            "active": active_provider == "qdrant",
            "mode": "external_vector_db",
            "collection": qdrant_collection,
            "createCollection": qdrant_create_collection,
            "capabilities": {
                "denseVectorSearch": True,
                "payloadFilter": True,
                "keywordSearch": "payload_scan_bm25",
                "hybridSearch": "retriever_fusion",
            },
        },
        {
            "name": "pgvector",
            "available": False,
            "configured": bool(pgvector_dsn),
            "active": active_provider == "pgvector",
            "mode": "placeholder",
        },
        {
            "name": "milvus",
            "available": False,
            "configured": bool(milvus_uri),
            "active": active_provider == "milvus",
            "mode": "placeholder",
        },
    ]
    return {"activeProvider": active_provider, "providers": providers}
