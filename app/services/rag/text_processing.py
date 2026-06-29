"""Shared text tokenization for RAG keyword retrieval.

Provides Chinese-aware tokenization (jieba) with stopword filtering, and
gracefully degrades to a regex tokenizer when jieba is unavailable so the
keyword path never hard-fails on a missing optional dependency.
"""
from __future__ import annotations

import re
from functools import lru_cache

# 拉丁/数字 token：保留 bge-m3、v2.m3 这类带连字符/点的词
# 中文：连续汉字片段，交给 jieba 二次切分
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*|[\u4e00-\u9fff]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 中文常见停用词（精简高频集，可按需扩充）
_CN_STOPWORDS: frozenset[str] = frozenset(
    {
        "的", "了", "和", "是", "在", "我", "有", "也", "就", "都", "而", "及",
        "与", "或", "一个", "没有", "我们", "你们", "他们", "这个", "那个",
        "这些", "那些", "什么", "怎么", "可以", "因为", "所以", "如果", "但是",
        "一种", "一些", "对于", "关于", "通过", "进行", "已经", "还是", "以及",
        "之后", "之前", "以上", "以下", "请问", "如何", "这样", "那样", "吗",
        "呢", "啊", "吧", "把", "被", "让", "给", "向", "从", "到", "为",
    }
)

# 英文常见停用词
_EN_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in",
        "on", "at", "for", "by", "with", "as", "is", "are", "was", "were",
        "be", "been", "being", "this", "that", "these", "those", "it", "its",
        "i", "we", "you", "he", "she", "they", "them", "his", "her", "their",
        "do", "does", "did", "can", "could", "should", "would", "will", "shall",
        "what", "how", "why", "when", "where", "which", "who", "whom", "about",
        "into", "from", "than", "so", "such", "not", "no", "yes",
    }
)

_STOPWORDS: frozenset[str] = _CN_STOPWORDS | _EN_STOPWORDS

# jieba 为可选依赖：未安装时降级为正则逐字切分，保持向后兼容
try:  # pragma: no cover - import guard
    import jieba

    jieba.initialize()
    _JIEBA_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import/init failure degrades gracefully
    jieba = None  # type: ignore[assignment]
    _JIEBA_AVAILABLE = False


def jieba_available() -> bool:
    """Return whether jieba Chinese segmentation is active."""
    return _JIEBA_AVAILABLE


@lru_cache(maxsize=4096)
def _cut_cjk(segment: str) -> tuple[str, ...]:
    """Segment a pure-CJK run; cached because query tokens repeat often."""
    if _JIEBA_AVAILABLE:
        tokens = [tok for tok in jieba.cut(segment, cut_all=False) if tok.strip()]
        return tuple(tokens) if tokens else (segment,)
    # 降级：逐字切分（与历史行为一致）
    return tuple(segment)


def tokenize(text: str, *, remove_stopwords: bool | None = None) -> list[str]:
    """Tokenize mixed Chinese/English text into normalized lowercase tokens.

    - 拉丁/数字按词切分并小写；
    - 中文优先用 jieba 分词，未安装时降级逐字切分；
    - 停用词过滤：``remove_stopwords=None`` 时读取配置
      ``RAG_REMOVE_STOPWORDS``（默认开启），显式传入 ``True``/``False``
      可覆盖配置。
    """
    if not text:
        return []

    if remove_stopwords is None:
        remove_stopwords = _stopwords_enabled()

    tokens: list[str] = []
    for match in _SEGMENT_RE.finditer(text):
        chunk = match.group(0)
        if _CJK_RUN_RE.fullmatch(chunk):
            tokens.extend(_cut_cjk(chunk))
        else:
            tokens.append(chunk.lower())

    if not remove_stopwords:
        return tokens

    return [tok for tok in tokens if tok and tok not in _STOPWORDS and not _is_noise(tok)]


def _stopwords_enabled() -> bool:
    """Read the stopword-filtering switch from settings, defaulting to on."""
    try:
        from ...config import settings

        return bool(settings.rag_remove_stopwords)
    except Exception:  # noqa: BLE001 - never let config import break tokenization
        return True


def _is_noise(token: str) -> bool:
    """Drop single-character latin tokens that carry little signal."""
    return len(token) == 1 and token.isascii() and not token.isalnum()
