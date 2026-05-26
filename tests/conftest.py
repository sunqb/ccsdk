"""Test configuration — isolate embedding provider to local hash.

All tests must use LocalHashEmbeddingProvider to avoid:
1. Remote API calls (BGE-M3) slowing down tests
2. Network flakiness causing false failures
3. Dimension mismatch between factory singleton and test expectations
"""
import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _force_local_embedding():
    """Force all tests to use local hash embedding provider.

    This resets the embedding_factory singleton and overrides the
    RAG_EMBEDDING_PROVIDER env var for the entire test session.
    """
    os.environ["RAG_EMBEDDING_PROVIDER"] = "local"
    os.environ.pop("RAG_EMBEDDING_BASE_URL", None)
    os.environ.pop("RAG_EMBEDDING_API_KEY", None)
    os.environ["RAG_EMBEDDING_MODEL"] = "local_hash"

    # Mutate the existing settings singleton in place. Several modules import
    # `settings` directly, so replacing app.config.settings would not update
    # those references.
    from app.config import settings
    settings.rag_embedding_provider = "local"
    settings.rag_embedding_model = "local_hash"
    settings.rag_embedding_base_url = None
    settings.rag_embedding_api_key = None

    # Reset the factory singleton so it rebuilds from the mutated settings.
    from app.services.rag.embedding_factory import get_embedder, reset
    reset()
    local_embedder = get_embedder()

    # Keep module-level service singletons aligned with the test embedder.
    from app.services.rag import ingestion as _ingestion_mod
    from app.services.rag import retriever as _retriever_mod
    _ingestion_mod.rag_ingestion_service.embedder = local_embedder
    _retriever_mod.rag_retriever.embedder = local_embedder

    yield

    # Cleanup: no need to restore, session is ending
