"""Embedding providers for the RAG MVP."""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[^\W\s]", flags=re.UNICODE)


class EmbeddingProvider(ABC):
    """Abstract embedding provider interface."""

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple document texts."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a query text."""


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local hashing embeddings for development and tests.

    This provider is intentionally simple and dependency-free. It is not meant
    to provide production-grade semantic quality, but it gives a stable vector
    interface for the MVP pipeline before a real provider is configured.
    """

    def __init__(self, dimensions: int = 256):
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than 0")
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple document texts."""
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a query text."""
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return self._normalize(vector)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible remote embedding provider."""

    default_base_url = "https://api.openai.com/v1"

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ):
        if not model:
            raise ValueError("model must not be empty")
        self.model = model
        self.base_url = self._normalize_base_url(base_url or self.default_base_url)
        self.api_key = api_key
        self.timeout = timeout
        self._client = client

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple document texts using a remote provider."""
        if not texts:
            return []
        return await self._request_embeddings(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a query text using a remote provider."""
        embeddings = await self._request_embeddings([text])
        return embeddings[0]

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/embeddings"):
            normalized = normalized[: -len("/embeddings")]
        return normalized

    async def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"model": self.model, "input": texts}
        client = self._client
        if client is not None:
            return await self._post_embeddings(client, payload, headers, should_close=False)

        async with httpx.AsyncClient(timeout=self.timeout) as owned_client:
            return await self._post_embeddings(owned_client, payload, headers, should_close=True)

    async def _post_embeddings(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        headers: dict[str, str],
        *,
        should_close: bool,
    ) -> list[list[float]]:
        try:
            response = await client.post(
                f"{self.base_url}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Embedding provider returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(f"Embedding provider request failed: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

        return self._parse_embeddings_response(body)

    @staticmethod
    def _parse_embeddings_response(body: Any) -> list[list[float]]:
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise RuntimeError("Embedding provider response must include a data array")

        items = sorted(
            body["data"],
            key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
        )
        embeddings: list[list[float]] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise RuntimeError("Embedding provider response item is missing embedding")
            embeddings.append([float(value) for value in item["embedding"]])
        return embeddings
