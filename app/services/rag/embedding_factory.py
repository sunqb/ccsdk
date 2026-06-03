"""嵌入模型工厂 — 单点真值 (Single Source of Truth)。

本模块是系统中唯一实例化 EmbeddingProvider 的地方。
所有需要 embedder 的模块必须通过 get_embedder() 获取，
禁止自行 new LocalHashEmbeddingProvider() 或 OpenAICompatibleEmbeddingProvider()。

设计原则（系统控制论 — 偏移修正策略）：
- Layer 1: 单点真值 — embedder 只实例化一次，维度信息集中管理
- Layer 2: 启动偏差检测 — health_check() 在服务启动时校验一致性
- Layer 3: 运行时偏差防护 — vector_store 写入/检索时校验维度
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...config import settings
from .embeddings import (
    EmbeddingProvider,
    LocalHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """嵌入模型画像 — 记录当前 embedder 的元信息，用于一致性校验。"""
    provider: str
    model: str
    dimension: int
    base_url: str | None = None


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: EmbeddingProvider | None = None
_profile: EmbeddingProfile | None = None


def get_embedder() -> EmbeddingProvider:
    """获取全局 embedder 单例。首次调用时根据配置创建。"""
    global _instance, _profile
    if _instance is not None:
        return _instance

    _instance, _profile = _create_embedder()
    return _instance


def get_embedding_profile() -> EmbeddingProfile:
    """获取当前 embedder 的画像信息（provider、model、dimension）。"""
    if _profile is None:
        get_embedder()  # 触发初始化
    assert _profile is not None
    return _profile


def _create_embedder() -> tuple[EmbeddingProvider, EmbeddingProfile]:
    """根据配置创建 embedder 实例和对应的画像信息。"""
    provider = settings.rag_embedding_provider

    if provider == "openai_compatible":
        base_url = settings.rag_embedding_base_url
        api_key = settings.rag_embedding_api_key
        model = settings.rag_embedding_model
        if not base_url:
            raise ValueError(
                "RAG_EMBEDDING_BASE_URL is required when "
                "RAG_EMBEDDING_PROVIDER=openai_compatible"
            )
        embedder = OpenAICompatibleEmbeddingProvider(
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        # 远程模型的维度在 health_check 时探测
        profile = EmbeddingProfile(
            provider=provider,
            model=model,
            dimension=0,  # 占位，health_check 后填充
            base_url=base_url,
        )
        return embedder, profile

    if provider == "local":
        model = "local_hash"
        dimension = 256
        embedder = LocalHashEmbeddingProvider(dimensions=dimension)
        profile = EmbeddingProfile(
            provider=provider,
            model=model,
            dimension=dimension,
        )
        return embedder, profile

    raise ValueError(f"Unsupported RAG_EMBEDDING_PROVIDER: {provider}")


async def health_check() -> EmbeddingProfile:
    """启动时偏差检测：校验 embedder 可达性并探测真实维度。

    Returns:
        EmbeddingProfile: 含真实维度的画像

    Raises:
        RuntimeError: embedder 不可达
    """
    global _profile

    embedder = get_embedder()
    profile = get_embedding_profile()

    # 探测真实维度
    try:
        sample = await embedder.embed_query("health_check")
        actual_dimension = len(sample)
    except Exception as exc:
        raise RuntimeError(
            f"Embedding provider health check failed "
            f"(provider={profile.provider}, model={profile.model}, "
            f"base_url={profile.base_url}): {exc}"
        ) from exc

    # 更新画像中的维度
    _profile = EmbeddingProfile(
        provider=profile.provider,
        model=profile.model,
        dimension=actual_dimension,
        base_url=profile.base_url,
    )

    return _profile


def validate_dimension_compatibility(stored_dimension: int | None) -> list[str]:
    """校验当前 embedder 维度与历史存储维度是否一致。

    Returns:
        list[str]: 警告信息列表（空列表表示一致）
    """
    warnings: list[str] = []
    if stored_dimension is None:
        return warnings

    profile = get_embedding_profile()
    if profile.dimension != stored_dimension:
        warnings.append(
            f"Embedding dimension mismatch: current embedder produces "
            f"{profile.dimension}-dim vectors, but stored data uses "
            f"{stored_dimension}-dim vectors. This will cause incorrect "
            f"search results. Please clear RAG storage or switch back to "
            f"the original embedding provider."
        )
    return warnings


def reset() -> None:
    """重置单例（仅用于测试）。"""
    global _instance, _profile
    _instance = None
    _profile = None
