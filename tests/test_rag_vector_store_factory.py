"""Vector store factory tests."""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.rag.embedding_factory import reset as reset_embedding_factory
from app.services.rag.qdrant_vector_store import QdrantVectorStore
from app.services.rag.vector_store import LocalVectorStore
from app.services.rag.vector_store_factory import get_vector_store, reset as reset_vector_store_factory


def _reset_factories() -> None:
    reset_vector_store_factory()
    reset_embedding_factory()


def test_vector_store_factory_builds_local_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rag_vector_provider", "local")
    _reset_factories()

    store = get_vector_store()

    assert isinstance(store, LocalVectorStore)
    assert get_vector_store() is store


def test_vector_store_factory_builds_qdrant_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rag_vector_provider", "qdrant")
    monkeypatch.setattr(settings, "rag_qdrant_url", "http://qdrant:6333")
    monkeypatch.setattr(settings, "rag_qdrant_api_key", None)
    monkeypatch.setattr(settings, "rag_qdrant_collection", "rag_chunks_test")
    monkeypatch.setattr(settings, "rag_qdrant_timeout_seconds", 5.0)
    monkeypatch.setattr(settings, "rag_qdrant_create_collection", True)
    monkeypatch.setattr(settings, "rag_embedding_provider", "local")
    monkeypatch.setattr(settings, "rag_embedding_model", "local_hash")
    _reset_factories()

    store = get_vector_store()

    assert isinstance(store, QdrantVectorStore)
    assert store.url == "http://qdrant:6333"
    assert store.collection == "rag_chunks_test"
    assert store.vector_size == 256


def test_vector_store_factory_requires_qdrant_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rag_vector_provider", "qdrant")
    monkeypatch.setattr(settings, "rag_qdrant_url", None)
    monkeypatch.setattr(settings, "rag_embedding_provider", "local")
    monkeypatch.setattr(settings, "rag_embedding_model", "local_hash")
    _reset_factories()

    with pytest.raises(ValueError, match="RAG_QDRANT_URL"):
        get_vector_store()


def test_vector_store_factory_rejects_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rag_vector_provider", "unknown")
    _reset_factories()

    with pytest.raises(ValueError, match="Unsupported RAG_VECTOR_PROVIDER"):
        get_vector_store()
