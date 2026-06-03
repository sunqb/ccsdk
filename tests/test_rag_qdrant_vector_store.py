"""Qdrant vector store provider tests."""
from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx
import pytest

from app.services.rag.chunker import RagChunk
from app.services.rag.qdrant_vector_store import QdrantVectorStore


def _collection_payload(vector_size: int = 3) -> dict[str, object]:
    return {
        "result": {
            "config": {
                "params": {
                    "vectors": {
                        "size": vector_size,
                        "distance": "Cosine",
                    }
                }
            }
        }
    }


@pytest.mark.asyncio
async def test_qdrant_vector_store_upsert_search_and_read() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else {}
        requests.append((request.method, request.url.path, body))

        if request.method == "GET" and request.url.path == "/collections/rag_test":
            return httpx.Response(404, json={"status": "not_found"})
        if request.method == "PUT" and request.url.path == "/collections/rag_test":
            assert body == {"vectors": {"size": 3, "distance": "Cosine"}}
            return httpx.Response(200, json={"result": True})
        if request.method == "PUT" and request.url.path == "/collections/rag_test/points":
            points = body["points"]
            assert len(points) == 1
            assert points[0]["vector"] == [0.1, 0.2, 0.3]
            assert points[0]["payload"]["chunk_id"] == "chunk_1"
            assert points[0]["payload"]["file_set_id"] == "fs_1"
            return httpx.Response(200, json={"result": {"status": "completed"}})
        if request.method == "POST" and request.url.path == "/collections/rag_test/points/search":
            assert body["limit"] == 5
            assert body["filter"] == QdrantVectorStore._filter_from_sources(
                [{"type": "file_set", "id": "fs_1"}]
            )
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "id": "point_1",
                            "score": 0.99,
                            "payload": {
                                "chunk_id": "chunk_1",
                                "chunk_index": 0,
                                "chunk_text": "Refunds are available within 30 days.",
                                "token_count": 6,
                                "source_file_id": "file_1",
                                "file_set_id": "fs_1",
                                "filename": "policy.md",
                            },
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/collections/rag_test/points":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "payload": {
                                "chunk_id": "chunk_1",
                                "chunk_index": 0,
                                "chunk_text": "Refunds are available within 30 days.",
                                "token_count": 6,
                                "source_file_id": "file_1",
                                "file_set_id": "fs_1",
                            }
                        }
                    ]
                },
            )
        return httpx.Response(500, json={"unexpected": str(request.url)})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://qdrant")
    store = QdrantVectorStore(
        url="http://qdrant",
        collection="rag_test",
        vector_size=3,
        client=client,
    )
    chunk = RagChunk(
        chunk_id="chunk_1",
        chunk_index=0,
        text="Refunds are available within 30 days.",
        token_count=6,
        metadata={"file_set_id": "fs_1", "filename": "policy.md"},
        source_file_id="file_1",
    )

    await store.upsert_chunks([chunk], [[0.1, 0.2, 0.3]])
    results = await store.vector_search(
        [0.1, 0.2, 0.3],
        sources=[{"type": "file_set", "id": "fs_1"}],
        top_k=5,
    )
    read_chunk = await store.get_chunk("chunk_1")

    assert results
    assert results[0].chunk_id == "chunk_1"
    assert results[0].score == 0.99
    assert results[0].metadata["filename"] == "policy.md"
    assert read_chunk is not None
    assert read_chunk.chunk_id == "chunk_1"
    assert ("PUT", "/collections/rag_test", {"vectors": {"size": 3, "distance": "Cosine"}}) in requests
    await client.aclose()


@pytest.mark.asyncio
async def test_qdrant_vector_store_validates_existing_collection_dimension() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/collections/rag_test":
            return httpx.Response(200, json=_collection_payload(vector_size=4))
        return httpx.Response(500, json={"unexpected": str(request.url)})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://qdrant")
    store = QdrantVectorStore(
        url="http://qdrant",
        collection="rag_test",
        vector_size=3,
        client=client,
    )

    with pytest.raises(ValueError, match="dimension mismatch"):
        await store.upsert_chunks([], [])

    await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qdrant_vector_store_integration_when_enabled() -> None:
    if os.getenv("RUN_QDRANT_INTEGRATION") != "1":
        pytest.skip("Set RUN_QDRANT_INTEGRATION=1 to run Qdrant integration test")

    url = os.getenv("RAG_QDRANT_URL", "http://10.2.128.40:6333")
    collection = f"rag_chunks_it_{uuid4().hex}"
    store = QdrantVectorStore(
        url=url,
        collection=collection,
        vector_size=3,
        api_key=os.getenv("RAG_QDRANT_API_KEY") or None,
    )
    chunk = RagChunk(
        chunk_id=f"chunk_{uuid4().hex}",
        chunk_index=0,
        text="Qdrant integration smoke text",
        token_count=4,
        metadata={"file_set_id": "fs_integration", "filename": "integration.md"},
        source_file_id="file_integration",
    )

    try:
        await store.upsert_chunks([chunk], [[1.0, 0.0, 0.0]])
        results = await store.vector_search(
            [1.0, 0.0, 0.0],
            sources=[{"type": "file_set", "id": "fs_integration"}],
            top_k=1,
        )
        assert results
        assert results[0].chunk_id == chunk.chunk_id
    finally:
        await store.delete_file_set("fs_integration")
        await store.aclose()
