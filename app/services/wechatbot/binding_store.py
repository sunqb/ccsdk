"""Mode A-2 automatic WeChat user binding store backed by MySQL."""
from __future__ import annotations

import hashlib
import json
import secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

from .message_router import RouteMode, build_default_rag_scope


class WeChatBindingError(Exception):
    """Base class for expected binding failures."""


class BindTokenInvalidError(WeChatBindingError):
    """The bind token does not exist or has been revoked."""


class BindTokenExpiredError(WeChatBindingError):
    """The bind token is expired."""


class BindTokenUsedError(WeChatBindingError):
    """The bind token has already been used."""


class WeChatAlreadyBoundError(WeChatBindingError):
    """The current WeChat user is already bound."""


@dataclass
class WeChatUserBinding:
    """A persisted WeChat-to-SaaS identity binding."""

    id: int | None
    bot_instance_id: str
    user_id_hash: str
    tenant_id: str
    app_user_id: str
    default_mode: RouteMode | None = None
    rag_scope: dict[str, str | list[str] | None] = field(default_factory=dict)
    enabled: bool = True
    bind_source: str = "token"
    last_seen_at: datetime | None = None


@dataclass
class BindTokenCreated:
    """One-time bind token returned to the authenticated SaaS user."""

    token: str
    token_preview: str
    expires_at: datetime
    bind_command: str


@dataclass
class BindTokenRecord:
    """Stored bind token metadata without the plaintext token."""

    id: int | None
    token_hash: str
    token_preview: str
    tenant_id: str
    app_user_id: str
    bot_instance_id: str
    default_mode: RouteMode | None = None
    rag_scope: dict[str, str | list[str] | None] = field(default_factory=dict)
    expires_at: datetime | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    used_by_user_id_hash: str | None = None


def _utcnow_naive() -> datetime:
    """Return a UTC timestamp suitable for MySQL DATETIME."""
    return datetime.now(UTC).replace(tzinfo=None)


def hash_bind_token(token: str) -> str:
    """Hash a bind token before storing or looking it up."""
    return hashlib.sha256(token.strip().upper().encode()).hexdigest()


def generate_bind_token() -> str:
    """Generate a short human-typeable bind token."""
    alphabet = string.ascii_uppercase + string.digits
    return "WX-" + "".join(secrets.choice(alphabet) for _ in range(6))


def normalize_mode(value: str | None) -> RouteMode | None:
    if not value:
        return None
    value = value.strip().lower()
    if value == "rag":
        return RouteMode.RAG
    if value == "agent":
        return RouteMode.AGENT
    return None


def _normalize_rag_scope(value: Any) -> dict[str, str | list[str] | None]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class EnvWeChatBindingStore:
    """Compatibility store backed by WECHATBOT_USER_TENANT_MAP."""

    async def get_binding(self, bot_instance_id: str, user_id_hash: str) -> WeChatUserBinding | None:
        entry = settings.wechatbot_user_tenant_map.get(f"sha256:{user_id_hash}")
        if entry is None:
            return None

        tenant_id = settings.wechatbot_default_tenant_id
        app_user_id: str | None = None
        default_mode: RouteMode | None = None
        rag_scope: dict[str, str | list[str] | None] = {}

        if isinstance(entry, str):
            tenant_id = entry.strip() or tenant_id
        elif isinstance(entry, dict):
            tenant_id = str(entry.get("tenantId") or entry.get("tenant_id") or tenant_id).strip()
            app_user_id_raw = entry.get("appUserId") or entry.get("app_user_id")
            app_user_id = str(app_user_id_raw).strip() if app_user_id_raw else None
            default_mode = normalize_mode(entry.get("defaultMode") or entry.get("default_mode"))
            rag_scope = _normalize_rag_scope(entry.get("ragScope") or entry.get("rag_scope"))

        if not rag_scope:
            tenant_scope = settings.wechatbot_tenant_rag_scope_map.get(tenant_id)
            if isinstance(tenant_scope, dict):
                rag_scope = tenant_scope
        if not rag_scope:
            rag_scope = build_default_rag_scope()

        return WeChatUserBinding(
            id=None,
            bot_instance_id=bot_instance_id,
            user_id_hash=user_id_hash,
            tenant_id=tenant_id,
            app_user_id=app_user_id or user_id_hash,
            default_mode=default_mode,
            rag_scope=rag_scope,
            bind_source="env",
        )


class DbWeChatBindingStore:
    """MySQL-backed binding store using the shared DB_DSN connection string."""

    def __init__(
        self,
        dsn: str | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._owns_engine = False
        self._engine = None
        if session_factory is not None:
            self._session_factory = session_factory
            return

        resolved_dsn = (dsn or settings.db_dsn).strip()
        if not resolved_dsn:
            raise RuntimeError("DB_DSN is required for WeChatBot DB binding store")
        if resolved_dsn.startswith("sqlite"):
            raise RuntimeError("WeChatBot DB binding store requires MySQL DB_DSN, not SQLite")

        self._engine = create_async_engine(
            resolved_dsn,
            pool_size=5,
            max_overflow=10,
            pool_recycle=3600,
            echo=False,
        )
        self._owns_engine = True
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def get_binding(self, bot_instance_id: str, user_id_hash: str) -> WeChatUserBinding | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, bot_instance_id, user_id_hash, tenant_id, app_user_id,
                           default_mode, rag_scope_json, status AS enabled,
                           bind_source, last_seen_time AS last_seen_at
                    FROM e_wechatbot_user_binding
                    WHERE bot_instance_id = :bot_instance_id
                      AND user_id_hash = :user_id_hash
                      AND status = 1
                      AND is_delete = 1
                    """
                ),
                {"bot_instance_id": bot_instance_id, "user_id_hash": user_id_hash},
            )
            row = result.mappings().first()
        return self._binding_from_row(row) if row else None

    async def create_bind_token(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str,
        default_mode: RouteMode | None = None,
        rag_scope: dict[str, str | list[str] | None] | None = None,
        ttl_seconds: int | None = None,
    ) -> BindTokenCreated:
        token = generate_bind_token()
        now = _utcnow_naive()
        expires_at = now + timedelta(seconds=ttl_seconds or settings.wechatbot_bind_token_ttl_seconds)
        token_preview = token[-6:]
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO e_wechatbot_bind_token(
                        token_hash, token_preview, tenant_id, app_user_id, bot_instance_id,
                        default_mode, rag_scope_json, expires_time,
                        create_by, create_time, update_by, update_time, is_delete
                    ) VALUES (
                        :token_hash, :token_preview, :tenant_id, :app_user_id, :bot_instance_id,
                        :default_mode, :rag_scope_json, :expires_at,
                        :create_by, :created_at, :update_by, :updated_at, 1
                    )
                    """
                ),
                {
                    "token_hash": hash_bind_token(token),
                    "token_preview": token_preview,
                    "tenant_id": tenant_id,
                    "app_user_id": app_user_id,
                    "bot_instance_id": bot_instance_id,
                    "default_mode": default_mode.value if default_mode else None,
                    "rag_scope_json": json.dumps(rag_scope or {}, ensure_ascii=False),
                    "expires_at": expires_at,
                    "create_by": app_user_id,
                    "created_at": now,
                    "update_by": app_user_id,
                    "updated_at": now,
                },
            )
            await session.commit()
        return BindTokenCreated(
            token=token,
            token_preview=token_preview,
            expires_at=expires_at.replace(tzinfo=UTC),
            bind_command=f"/bind {token}",
        )

    async def bind_with_token(self, bot_instance_id: str, user_id_hash: str, token: str) -> WeChatUserBinding:
        now = _utcnow_naive()
        token_hash = hash_bind_token(token)
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.execute(
                    text(
                        """
                        SELECT id
                        FROM e_wechatbot_user_binding
                        WHERE bot_instance_id = :bot_instance_id
                          AND user_id_hash = :user_id_hash
                          AND status = 1
                          AND is_delete = 1
                        LIMIT 1
                        """
                    ),
                    {"bot_instance_id": bot_instance_id, "user_id_hash": user_id_hash},
                )
                if existing.first():
                    raise WeChatAlreadyBoundError()

                result = await session.execute(
                    text(
                        """
                        SELECT id, tenant_id, app_user_id, bot_instance_id, default_mode, rag_scope_json,
                               expires_time AS expires_at, used_time AS used_at, revoked_time AS revoked_at
                        FROM e_wechatbot_bind_token
                        WHERE token_hash = :token_hash
                          AND is_delete = 1
                        ORDER BY id DESC
                        LIMIT 1
                        FOR UPDATE
                        """
                    ),
                    {"token_hash": token_hash},
                )
                row = result.mappings().first()
                if not row or row["revoked_at"] is not None:
                    raise BindTokenInvalidError()
                if row["used_at"] is not None:
                    raise BindTokenUsedError()
                if row["expires_at"] < now:
                    raise BindTokenExpiredError()

                rag_scope_json = row["rag_scope_json"] or {}
                if not isinstance(rag_scope_json, str):
                    rag_scope_json = json.dumps(rag_scope_json, ensure_ascii=False)
                await session.execute(
                    text(
                        """
                        INSERT INTO e_wechatbot_user_binding(
                            bot_instance_id, user_id_hash, tenant_id, app_user_id, default_mode,
                            rag_scope_json, status, bind_source, last_seen_time,
                            create_by, create_time, update_by, update_time, is_delete
                        ) VALUES (
                            :bot_instance_id, :user_id_hash, :tenant_id, :app_user_id, :default_mode,
                            :rag_scope_json, 1, 'token', :last_seen_at,
                            :create_by, :created_at, :update_by, :updated_at, 1
                        )
                        """
                    ),
                    {
                        "bot_instance_id": bot_instance_id,
                        "user_id_hash": user_id_hash,
                        "tenant_id": row["tenant_id"],
                        "app_user_id": row["app_user_id"],
                        "default_mode": row["default_mode"],
                        "rag_scope_json": rag_scope_json,
                        "create_by": row["app_user_id"],
                        "created_at": now,
                        "update_by": row["app_user_id"],
                        "updated_at": now,
                        "last_seen_at": now,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE e_wechatbot_bind_token
                        SET used_time = :used_at,
                            used_by_user_id_hash = :used_by_user_id_hash,
                            update_by = :update_by,
                            update_time = :update_time
                        WHERE id = :id
                        """
                    ),
                    {
                        "used_at": now,
                        "used_by_user_id_hash": user_id_hash,
                        "update_by": row["app_user_id"],
                        "update_time": now,
                        "id": row["id"],
                    },
                )
        binding = await self.get_binding(bot_instance_id, user_id_hash)
        if binding is None:
            raise BindTokenInvalidError()
        return binding

    async def unbind(self, bot_instance_id: str, user_id_hash: str) -> bool:
        now = _utcnow_naive()
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE e_wechatbot_user_binding
                    SET status = 2,
                        unbound_time = :unbound_at,
                        update_by = :update_by,
                        update_time = :updated_at
                    WHERE bot_instance_id = :bot_instance_id
                      AND user_id_hash = :user_id_hash
                      AND status = 1
                      AND is_delete = 1
                    """
                ),
                {
                    "unbound_at": now,
                    "update_by": user_id_hash,
                    "updated_at": now,
                    "bot_instance_id": bot_instance_id,
                    "user_id_hash": user_id_hash,
                },
            )
            await session.commit()
            return result.rowcount > 0

    async def touch_last_seen(self, bot_instance_id: str, user_id_hash: str) -> None:
        now = _utcnow_naive()
        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE e_wechatbot_user_binding
                    SET last_seen_time = :last_seen_at,
                        update_by = :update_by,
                        update_time = :updated_at
                    WHERE bot_instance_id = :bot_instance_id
                      AND user_id_hash = :user_id_hash
                      AND status = 1
                      AND is_delete = 1
                    """
                ),
                {
                    "last_seen_at": now,
                    "update_by": user_id_hash,
                    "updated_at": now,
                    "bot_instance_id": bot_instance_id,
                    "user_id_hash": user_id_hash,
                },
            )
            await session.commit()

    async def list_bindings(self, tenant_id: str | None = None, app_user_id: str | None = None) -> list[WeChatUserBinding]:
        where = []
        params: dict[str, Any] = {}
        if tenant_id:
            where.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if app_user_id:
            where.append("app_user_id = :app_user_id")
            params["app_user_id"] = app_user_id
        where_sql = " AND " + " AND ".join(where) if where else ""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT id, bot_instance_id, user_id_hash, tenant_id, app_user_id,
                           default_mode, rag_scope_json, status AS enabled,
                           bind_source, last_seen_time AS last_seen_at
                    FROM e_wechatbot_user_binding
                    WHERE is_delete = 1 {where_sql}
                    ORDER BY id DESC
                    LIMIT 200
                    """
                ),
                params,
            )
            rows = result.mappings().all()
        return [self._binding_from_row(row) for row in rows]

    async def disable_binding(self, binding_id: int) -> bool:
        now = _utcnow_naive()
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE e_wechatbot_user_binding
                    SET status = 2,
                        unbound_time = :unbound_at,
                        update_by = :update_by,
                        update_time = :updated_at
                    WHERE id = :id
                      AND status = 1
                      AND is_delete = 1
                    """
                ),
                {"unbound_at": now, "update_by": "admin", "updated_at": now, "id": binding_id},
            )
            await session.commit()
            return result.rowcount > 0

    def _binding_from_row(self, row: Any) -> WeChatUserBinding:
        rag_scope = _normalize_rag_scope(row["rag_scope_json"])
        if not rag_scope:
            tenant_scope = settings.wechatbot_tenant_rag_scope_map.get(row["tenant_id"])
            rag_scope = tenant_scope if isinstance(tenant_scope, dict) else build_default_rag_scope()
        return WeChatUserBinding(
            id=row["id"],
            bot_instance_id=row["bot_instance_id"],
            user_id_hash=row["user_id_hash"],
            tenant_id=row["tenant_id"],
            app_user_id=row["app_user_id"],
            default_mode=normalize_mode(row["default_mode"]),
            rag_scope=rag_scope,
            enabled=bool(row["enabled"]),
            bind_source=row["bind_source"] or "token",
            last_seen_at=row["last_seen_at"],
        )


class CompositeWeChatBindingStore:
    """Resolve DB first, then env fallback."""

    def __init__(self) -> None:
        self.db = DbWeChatBindingStore()
        self.env = EnvWeChatBindingStore()

    async def get_binding(self, bot_instance_id: str, user_id_hash: str) -> WeChatUserBinding | None:
        binding = await self.db.get_binding(bot_instance_id, user_id_hash)
        return binding or await self.env.get_binding(bot_instance_id, user_id_hash)

    async def touch_last_seen(self, bot_instance_id: str, user_id_hash: str) -> None:
        await self.db.touch_last_seen(bot_instance_id, user_id_hash)

    def __getattr__(self, name: str):
        return getattr(self.db, name)


_binding_store = None


def get_binding_store():
    """Return the configured binding store."""
    global _binding_store
    if _binding_store is not None:
        return _binding_store
    store = settings.wechatbot_binding_store
    if store == "env":
        _binding_store = EnvWeChatBindingStore()
    elif store == "db":
        _binding_store = DbWeChatBindingStore()
    else:
        _binding_store = CompositeWeChatBindingStore()
    return _binding_store


def set_binding_store_for_tests(store) -> None:
    """Inject a binding store in tests."""
    global _binding_store
    _binding_store = store


def reset_binding_store_for_tests() -> None:
    """Reset singleton in tests after mutating settings."""
    global _binding_store
    _binding_store = None
