"""Vector store factory for RAG providers."""
from __future__ import annotations

from collections.abc import Callable

from ...config import settings
from .embedding_factory import get_embedding_profile
from .qdrant_vector_store import QdrantVectorStore
from .vector_store import LocalVectorStore, VectorStore

_instance: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the configured global VectorStore singleton."""
    global _instance
    if _instance is not None:
        return _instance

    provider = settings.rag_vector_provider.strip().lower()
    try:
        builder = _VECTOR_STORE_BUILDERS[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported RAG_VECTOR_PROVIDER: {provider}") from exc

    _instance = builder()
    return _instance


def reset() -> None:
    """Reset the factory singleton for tests."""
    global _instance
    _instance = None


def _build_local_vector_store() -> VectorStore:
    return LocalVectorStore()


def _build_qdrant_vector_store() -> VectorStore:
    if not settings.rag_qdrant_url:
        raise ValueError("RAG_QDRANT_URL is required when RAG_VECTOR_PROVIDER=qdrant")

    vector_size = _resolve_embedding_dimension()
    if vector_size <= 0:
        raise ValueError(
            "Embedding dimension is unknown; run embedding health_check() before using Qdrant "
            "or configure a model with a known dimension"
        )
    return QdrantVectorStore(
        url=settings.rag_qdrant_url,
        api_key=settings.rag_qdrant_api_key,
        collection=settings.rag_qdrant_collection,
        vector_size=vector_size,
        timeout_seconds=settings.rag_qdrant_timeout_seconds,
        create_collection=settings.rag_qdrant_create_collection,
    )


def _resolve_embedding_dimension() -> int:
    """Return the current embedding dimension without hardcoding vector stores.

    OpenAI-compatible providers learn their real dimension during health_check().
    During module import that check may not have run yet, so use well-known model
    defaults as a startup fallback and keep Qdrant's collection validation as the
    final compatibility guard.
    """
    profile = get_embedding_profile()
    if profile.dimension > 0:
        return profile.dimension

    model = profile.model.lower()
    known_dimensions = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "bge-m3": 1024,
        "bge-m3:latest": 1024,
    }
    return known_dimensions.get(model, 0)


def _unsupported_external_provider(provider: str) -> Callable[[], VectorStore]:
    def _builder() -> VectorStore:
        raise ValueError(f"RAG_VECTOR_PROVIDER={provider} is not implemented yet")

    return _builder


_VECTOR_STORE_BUILDERS: dict[str, Callable[[], VectorStore]] = {
    "local": _build_local_vector_store,
    "qdrant": _build_qdrant_vector_store,
    "pgvector": _unsupported_external_provider("pgvector"),
    "milvus": _unsupported_external_provider("milvus"),
}
