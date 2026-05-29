"""Mode A SaaS behavior tests for the WeChatBot entrypoint."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.wechatbot.adapter import WeChatBotAdapter
from app.services.wechatbot.binding_store import (
    BindTokenCreated,
    BindTokenExpiredError,
    BindTokenInvalidError,
    BindTokenUsedError,
    WeChatAlreadyBoundError,
    WeChatUserBinding,
    generate_bind_token,
    get_binding_store,
    hash_bind_token,
    normalize_mode,
    reset_binding_store_for_tests,
    set_binding_store_for_tests,
)
from app.services.wechatbot.manager import WeChatBotManager
from app.services.wechatbot.message_router import RouteMode, route_message
from app.services.wechatbot.session import WeChatSessionManager
from app.services.wechatbot.tenant import resolve_tenant_context, resolve_tenant_context_async
from datetime import UTC, datetime, timedelta


class InMemoryWeChatBindingStore:
    """Test double for the MySQL-backed binding store."""

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], WeChatUserBinding] = {}
        self._tokens: dict[str, dict] = {}
        self._next_id = 1

    async def get_binding(self, bot_instance_id: str, user_id_hash: str) -> WeChatUserBinding | None:
        binding = self._bindings.get((bot_instance_id, user_id_hash))
        return binding if binding and binding.enabled else None

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
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds or settings.wechatbot_bind_token_ttl_seconds)
        self._tokens[hash_bind_token(token)] = {
            "tenant_id": tenant_id,
            "app_user_id": app_user_id,
            "bot_instance_id": bot_instance_id,
            "default_mode": default_mode.value if default_mode else None,
            "rag_scope": rag_scope or {},
            "expires_at": expires_at,
            "used_at": None,
            "revoked_at": None,
            "used_by_user_id_hash": None,
        }
        return BindTokenCreated(
            token=token,
            token_preview=token[-6:],
            expires_at=expires_at,
            bind_command=f"/bind {token}",
        )

    async def bind_with_token(self, bot_instance_id: str, user_id_hash: str, token: str) -> WeChatUserBinding:
        if await self.get_binding(bot_instance_id, user_id_hash):
            raise WeChatAlreadyBoundError()

        record = self._tokens.get(hash_bind_token(token))
        if not record or record["revoked_at"] is not None:
            raise BindTokenInvalidError()
        if record["used_at"] is not None:
            raise BindTokenUsedError()
        if record["expires_at"] < datetime.now(UTC):
            raise BindTokenExpiredError()

        binding = WeChatUserBinding(
            id=self._next_id,
            bot_instance_id=bot_instance_id,
            user_id_hash=user_id_hash,
            tenant_id=record["tenant_id"],
            app_user_id=record["app_user_id"],
            default_mode=normalize_mode(record["default_mode"]),
            rag_scope=record["rag_scope"],
            enabled=True,
            bind_source="token",
            last_seen_at=datetime.now(UTC),
        )
        self._next_id += 1
        self._bindings[(bot_instance_id, user_id_hash)] = binding
        record["used_at"] = datetime.now(UTC)
        record["used_by_user_id_hash"] = user_id_hash
        return binding

    async def unbind(self, bot_instance_id: str, user_id_hash: str) -> bool:
        binding = self._bindings.get((bot_instance_id, user_id_hash))
        if not binding or not binding.enabled:
            return False
        binding.enabled = False
        return True

    async def touch_last_seen(self, bot_instance_id: str, user_id_hash: str) -> None:
        binding = self._bindings.get((bot_instance_id, user_id_hash))
        if binding and binding.enabled:
            binding.last_seen_at = datetime.now(UTC)

    async def list_bindings(self, tenant_id: str | None = None, app_user_id: str | None = None) -> list[WeChatUserBinding]:
        items = list(self._bindings.values())
        if tenant_id:
            items = [item for item in items if item.tenant_id == tenant_id]
        if app_user_id:
            items = [item for item in items if item.app_user_id == app_user_id]
        return sorted(items, key=lambda item: item.id or 0, reverse=True)

    async def disable_binding(self, binding_id: int) -> bool:
        for binding in self._bindings.values():
            if binding.id == binding_id and binding.enabled:
                binding.enabled = False
                return True
        return False


@pytest.fixture(autouse=True)
def _reset_wechatbot_settings():
    """Keep tests isolated from local .env WeChatBot settings."""
    original = {
        "wechatbot_allowed_user_ids": settings.wechatbot_allowed_user_ids,
        "wechatbot_default_tenant_id": settings.wechatbot_default_tenant_id,
        "wechatbot_bot_instance_id": settings.wechatbot_bot_instance_id,
        "wechatbot_require_user_tenant": settings.wechatbot_require_user_tenant,
        "wechatbot_user_tenant_map": settings.wechatbot_user_tenant_map,
        "wechatbot_tenant_rag_scope_map": settings.wechatbot_tenant_rag_scope_map,
        "wechatbot_default_mode": settings.wechatbot_default_mode,
        "wechatbot_default_rag_scope": settings.wechatbot_default_rag_scope,
        "wechatbot_default_knowledge_base_id": settings.wechatbot_default_knowledge_base_id,
        "wechatbot_default_knowledge_base_name": settings.wechatbot_default_knowledge_base_name,
        "wechatbot_default_file_set_id": settings.wechatbot_default_file_set_id,
        "wechatbot_rate_limit_per_user": settings.wechatbot_rate_limit_per_user,
        "wechatbot_rate_limit_burst": settings.wechatbot_rate_limit_burst,
        "wechatbot_rate_limit_window": settings.wechatbot_rate_limit_window,
        "wechatbot_binding_store": settings.wechatbot_binding_store,
        "wechatbot_bind_token_ttl_seconds": settings.wechatbot_bind_token_ttl_seconds,
        "wechatbot_enabled": settings.wechatbot_enabled,
    }
    settings.wechatbot_allowed_user_ids = []
    settings.wechatbot_default_tenant_id = "default"
    settings.wechatbot_bot_instance_id = "default"
    settings.wechatbot_require_user_tenant = False
    settings.wechatbot_user_tenant_map = {}
    settings.wechatbot_tenant_rag_scope_map = {}
    settings.wechatbot_default_mode = "agent"
    settings.wechatbot_default_rag_scope = None
    settings.wechatbot_default_knowledge_base_id = None
    settings.wechatbot_default_knowledge_base_name = None
    settings.wechatbot_default_file_set_id = None
    settings.wechatbot_rate_limit_per_user = 20
    settings.wechatbot_rate_limit_burst = 5
    settings.wechatbot_rate_limit_window = 60
    settings.wechatbot_binding_store = "db"
    settings.wechatbot_bind_token_ttl_seconds = 600
    settings.wechatbot_enabled = True
    set_binding_store_for_tests(InMemoryWeChatBindingStore())

    yield

    for key, value in original.items():
        setattr(settings, key, value)
    reset_binding_store_for_tests()


def _hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def test_resolve_tenant_context_supports_hash_mapping_and_scope_precedence() -> None:
    user_id = "wxid_prod_user"
    user_hash = _hash_user_id(user_id)
    settings.wechatbot_bot_instance_id = "main-bot"
    settings.wechatbot_user_tenant_map = {
        f"sha256:{user_hash}": {
            "tenantId": "tenant-a",
            "appUserId": "app-user-a",
            "defaultMode": "rag",
            "ragScope": {"knowledgeBaseId": "kb-user"},
        }
    }
    settings.wechatbot_tenant_rag_scope_map = {
        "tenant-a": {"knowledgeBaseId": "kb-tenant"}
    }
    settings.wechatbot_default_knowledge_base_id = "kb-default"

    context = resolve_tenant_context(user_id)

    assert context is not None
    assert context.mapped is True
    assert context.tenant_id == "tenant-a"
    assert context.app_user_id == "app-user-a"
    assert context.default_mode == RouteMode.RAG
    assert context.rag_scope == {"knowledgeBaseId": "kb-user"}
    assert context.rate_limit_key == f"tenant-a:main-bot:{user_hash}"
    assert context.space_id == "tenant-a"


def test_resolve_tenant_context_requires_mapping_when_configured() -> None:
    settings.wechatbot_require_user_tenant = True
    settings.wechatbot_default_tenant_id = "public"

    assert resolve_tenant_context("wxid_unmapped") is None


def test_route_message_keeps_tenant_in_conversation_id_and_bound_rag_scope() -> None:
    user_id = "wxid_tenant_a"
    user_hash = _hash_user_id(user_id)
    scope = {"fileSetId": "fs-a"}

    decision = route_message(
        text="/rag 退款政策是什么",
        user_id=user_id,
        default_mode=RouteMode.AGENT,
        tenant_id="tenant-a",
        bot_instance_id="bot-1",
        app_user_id="app-user-a",
        rag_scope=scope,
    )

    assert decision.mode == RouteMode.RAG
    assert decision.message == "退款政策是什么"
    assert decision.conversation_id == f"wechat:tenant-a:bot-1:{user_hash}"
    assert decision.rag_scope == scope
    assert decision.space_id == "tenant-a"
    assert decision.app_user_id == "app-user-a"


def test_session_manager_isolates_same_wechat_user_by_tenant() -> None:
    user_id = "wxid_shared"
    user_hash = _hash_user_id(user_id)
    manager = WeChatSessionManager()

    session_a = manager.get_or_create_session(
        user_id=user_id,
        conversation_id=f"wechat:tenant-a:bot:{user_hash}",
        tenant_id="tenant-a",
        bot_instance_id="bot",
    )
    session_b = manager.get_or_create_session(
        user_id=user_id,
        conversation_id=f"wechat:tenant-b:bot:{user_hash}",
        tenant_id="tenant-b",
        bot_instance_id="bot",
    )

    assert session_a is not session_b
    assert manager.get_stats()["total_sessions"] == 2

    manager.record_message(user_id, tenant_id="tenant-a", bot_instance_id="bot")
    assert session_a.message_count == 1
    assert session_b.message_count == 0

    assert manager.reset_session(user_id, tenant_id="tenant-a", bot_instance_id="bot") is True
    assert manager.get_session_by_user_id(user_id, tenant_id="tenant-a", bot_instance_id="bot") is None
    assert manager.get_session_by_user_id(user_id, tenant_id="tenant-b", bot_instance_id="bot") is session_b


@pytest.mark.asyncio
async def test_manager_passes_tenant_context_to_processor() -> None:
    user_id = "wxid_agent"
    settings.wechatbot_bot_instance_id = "bot-1"
    settings.wechatbot_user_tenant_map = {
        user_id: {
            "tenantId": "tenant-a",
            "appUserId": "app-user-a",
            "defaultMode": "agent",
        }
    }

    class FakeProcessor:
        def __init__(self) -> None:
            self.decision = None
            self.session = None

        async def process(self, decision, session) -> str:
            self.decision = decision
            self.session = session
            return "ok"

    processor = FakeProcessor()
    manager = WeChatBotManager()
    manager._session_manager = WeChatSessionManager()
    manager._message_processor = processor

    reply = await manager.handle_message(user_id, "hello")

    assert reply == "ok"
    assert processor.decision.tenant_id == "tenant-a"
    assert processor.decision.app_user_id == "app-user-a"
    assert processor.decision.space_id == "tenant-a"
    assert processor.session.tenant_id == "tenant-a"
    assert processor.session.app_user_id == "app-user-a"
    assert processor.session.bot_instance_id == "bot-1"
    assert processor.session.message_count == 1


@pytest.mark.asyncio
async def test_db_binding_store_token_lifecycle_and_async_resolution() -> None:
    settings.wechatbot_bot_instance_id = "bot-1"
    store = get_binding_store()
    token = await store.create_bind_token(
        tenant_id="tenant-db",
        app_user_id="app-user-db",
        bot_instance_id="bot-1",
        default_mode=RouteMode.RAG,
        rag_scope={"knowledgeBaseId": "kb-db"},
        ttl_seconds=600,
    )

    user_id = "wxid_bound_db"
    user_hash = _hash_user_id(user_id)
    binding = await store.bind_with_token("bot-1", user_hash, token.token.lower())

    assert token.bind_command == f"/bind {token.token}"
    assert binding.tenant_id == "tenant-db"
    assert binding.app_user_id == "app-user-db"
    assert binding.default_mode == RouteMode.RAG
    assert binding.rag_scope == {"knowledgeBaseId": "kb-db"}

    context = await resolve_tenant_context_async(user_id)
    assert context is not None
    assert context.mapped is True
    assert context.tenant_id == "tenant-db"
    assert context.app_user_id == "app-user-db"
    assert context.default_mode == RouteMode.RAG


@pytest.mark.asyncio
async def test_manager_bind_me_unbind_commands() -> None:
    settings.wechatbot_bot_instance_id = "bot-1"
    settings.wechatbot_require_user_tenant = True
    store = get_binding_store()
    token = await store.create_bind_token(
        tenant_id="tenant-cmd",
        app_user_id="app-user-cmd",
        bot_instance_id="bot-1",
    )

    manager = WeChatBotManager()
    manager._session_manager = WeChatSessionManager()
    user_id = "wxid_cmd"

    assert "尚未绑定" in await manager.handle_message(user_id, "/me")
    assert "你还没有绑定系统账号" in await manager.handle_message(user_id, "hello")

    bind_reply = await manager.handle_message(user_id, f"/bind {token.token}")
    assert "绑定成功" in bind_reply
    assert "tenant-cmd" in bind_reply

    me_reply = await manager.handle_message(user_id, "/me")
    assert "当前微信已绑定" in me_reply
    assert "app-user-cmd" in me_reply

    unbind_reply = await manager.handle_message(user_id, "/unbind")
    assert "已解除当前微信绑定" in unbind_reply
    assert "尚未绑定" in await manager.handle_message(user_id, "/me")


@pytest.mark.asyncio
async def test_adapter_text_bind_reaches_manager_when_unbound() -> None:
    settings.wechatbot_bot_instance_id = "bot-1"
    settings.wechatbot_require_user_tenant = True
    store = get_binding_store()
    token = await store.create_bind_token(
        tenant_id="tenant-adapter",
        app_user_id="app-user-adapter",
        bot_instance_id="bot-1",
    )

    class FakeMediaHandler:
        def is_media_message(self, message_type: str) -> bool:
            return False

    class CapturingAdapter(WeChatBotAdapter):
        def __init__(self) -> None:
            self._manager = None
            self.sent: list[tuple[str, str]] = []

        @property
        def is_connected(self) -> bool:
            return True

        def _get_media_handler(self):
            return FakeMediaHandler()

        async def send_message(self, user_id: str, text: str) -> dict:
            self.sent.append((user_id, text))
            return {"success": True}

    manager = WeChatBotManager()
    manager._session_manager = WeChatSessionManager()
    adapter = CapturingAdapter()
    adapter.set_manager(manager)

    await adapter._handle_message_async("wxid_adapter", "text", f"/bind {token.token}", {})

    assert adapter.sent
    assert "绑定成功" in adapter.sent[-1][1]
    binding = await store.get_binding("bot-1", _hash_user_id("wxid_adapter"))
    assert binding is not None
    assert binding.tenant_id == "tenant-adapter"


def test_wechatbot_binding_api_creates_lists_and_disables_tokens() -> None:
    client = TestClient(app)

    create_response = client.post(
        "/wechatbot/bind-tokens",
        json={
            "tenant_id": "tenant-api",
            "app_user_id": "app-user-api",
            "default_mode": "agent",
            "rag_scope": {"fileSetId": "fs-api"},
            "ttl_seconds": 600,
        },
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["token"].startswith("WX-")
    assert body["bindCommand"] == f"/bind {body['token']}"

    user_hash = _hash_user_id("wxid_api")
    import asyncio

    asyncio.run(get_binding_store().bind_with_token("default", user_hash, body["token"]))

    list_response = client.get("/wechatbot/bindings?tenantId=tenant-api&appUserId=app-user-api")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["userIdHash"] == user_hash

    delete_response = client.delete(f"/wechatbot/bindings/{items[0]['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True


def test_wechatbot_binding_api_accepts_camel_case_request() -> None:
    client = TestClient(app)

    response = client.post(
        "/wechatbot/bind-tokens",
        json={
            "tenantId": "tenant-camel",
            "appUserId": "app-user-camel",
            "defaultMode": "rag",
            "ragScope": {"knowledgeBaseId": "kb-camel"},
            "ttlSeconds": 600,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"].startswith("WX-")
    assert body["bindCommand"] == f"/bind {body['token']}"
