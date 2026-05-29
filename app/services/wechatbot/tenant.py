"""Mode A SaaS tenant resolution for the single WeChatBot runtime."""
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

from .message_router import RouteMode, build_default_rag_scope

logger = logging.getLogger(__name__)


def hash_user_id(user_id: str) -> str:
    """Return the short hash used throughout WeChatBot logs and IDs."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


@dataclass
class WeChatTenantContext:
    """Resolved SaaS identity for a WeChat message in Mode A."""

    tenant_id: str
    bot_instance_id: str
    user_id_hash: str
    app_user_id: str | None = None
    default_mode: RouteMode | None = None
    rag_scope: dict[str, str | list[str] | None] = field(default_factory=dict)
    mapped: bool = False

    @property
    def rate_limit_key(self) -> str:
        return f"{self.tenant_id}:{self.bot_instance_id}:{self.user_id_hash}"

    @property
    def space_id(self) -> str:
        return self.tenant_id


def _context_from_binding(binding) -> WeChatTenantContext:
    return WeChatTenantContext(
        tenant_id=binding.tenant_id,
        bot_instance_id=binding.bot_instance_id,
        user_id_hash=binding.user_id_hash,
        app_user_id=binding.app_user_id,
        default_mode=binding.default_mode,
        rag_scope=binding.rag_scope,
        mapped=True,
    )


def _normalize_mode(value: Any) -> RouteMode | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "rag":
        return RouteMode.RAG
    if normalized == "agent":
        return RouteMode.AGENT
    return None


def _normalize_rag_scope(value: Any) -> dict[str, str | list[str] | None]:
    return value if isinstance(value, dict) else {}


def resolve_tenant_context(user_id: str) -> WeChatTenantContext | None:
    """Resolve tenant/app-user context from env JSON mapping.

    Mapping keys may be raw WeChat user IDs or `sha256:{user_id_hash}`.
    """
    user_id_hash = hash_user_id(user_id)
    mapping = settings.wechatbot_user_tenant_map
    raw_entry = mapping.get(user_id)
    hashed_entry = mapping.get(f"sha256:{user_id_hash}")
    entry = raw_entry if raw_entry is not None else hashed_entry
    mapped = entry is not None

    if not mapped and settings.wechatbot_require_user_tenant:
        logger.warning("拒绝未绑定租户的微信用户: user_hash=%s", user_id_hash)
        return None

    tenant_id = settings.wechatbot_default_tenant_id
    app_user_id: str | None = None
    default_mode: RouteMode | None = None
    rag_scope: dict[str, str | list[str] | None] = {}

    if isinstance(entry, str):
        tenant_id = entry.strip() or tenant_id
    elif isinstance(entry, dict):
        tenant_id = str(entry.get("tenantId") or entry.get("tenant_id") or tenant_id).strip() or tenant_id
        app_user_id_raw = entry.get("appUserId") or entry.get("app_user_id")
        app_user_id = str(app_user_id_raw).strip() if app_user_id_raw else None
        default_mode = _normalize_mode(entry.get("defaultMode") or entry.get("default_mode"))
        rag_scope = _normalize_rag_scope(entry.get("ragScope") or entry.get("rag_scope"))

    tenant_scope = settings.wechatbot_tenant_rag_scope_map.get(tenant_id)
    if not rag_scope and isinstance(tenant_scope, dict):
        rag_scope = tenant_scope
    if not rag_scope:
        rag_scope = build_default_rag_scope()

    return WeChatTenantContext(
        tenant_id=tenant_id,
        bot_instance_id=settings.wechatbot_bot_instance_id,
        user_id_hash=user_id_hash,
        app_user_id=app_user_id,
        default_mode=default_mode,
        rag_scope=rag_scope,
        mapped=mapped,
    )


async def resolve_tenant_context_async(user_id: str) -> WeChatTenantContext | None:
    """Resolve tenant context using DB binding first, then env/default fallback."""
    user_id_hash = hash_user_id(user_id)

    if settings.wechatbot_binding_store != "env":
        from .binding_store import get_binding_store

        store = get_binding_store()
        binding = await store.get_binding(settings.wechatbot_bot_instance_id, user_id_hash)
        if binding is not None:
            await store.touch_last_seen(settings.wechatbot_bot_instance_id, user_id_hash)
            return _context_from_binding(binding)

    return resolve_tenant_context(user_id)
