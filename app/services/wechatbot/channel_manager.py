"""Mode B per-user WeChatBot channel manager.

Mode A keeps a single shared Bot runtime. Mode B reuses the same SDK adapter and
message pipeline, but gives each SaaS user an isolated credential file and
runtime manager, so each user can bind/login their own WeChat channel.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from app.config import settings

from .manager import WeChatBotManager


@dataclass(frozen=True)
class WeChatBotChannelKey:
    """Stable identity for a Mode B per-user WeChat channel."""

    tenant_id: str
    app_user_id: str
    bot_instance_id: str

    @property
    def value(self) -> str:
        return f"{self.tenant_id}:{self.app_user_id}:{self.bot_instance_id}"


class WeChatBotChannelManager:
    """Manage per-user WeChatBot runtimes for Mode B."""

    def __init__(self) -> None:
        self._channels: dict[str, WeChatBotManager] = {}

    def _key(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str | None = None,
    ) -> WeChatBotChannelKey:
        return WeChatBotChannelKey(
            tenant_id=tenant_id.strip(),
            app_user_id=app_user_id.strip(),
            bot_instance_id=(bot_instance_id or settings.wechatbot_bot_instance_id).strip() or "default",
        )

    def _cred_path(self, key: WeChatBotChannelKey) -> str:
        digest = hashlib.sha256(key.value.encode()).hexdigest()[:24]
        return os.path.join(settings.wechatbot_credentials_dir, "mode_b", f"{digest}.json")

    def get_channel(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str | None = None,
    ) -> WeChatBotManager:
        key = self._key(
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            bot_instance_id=bot_instance_id,
        )
        if key.value not in self._channels:
            self._channels[key.value] = WeChatBotManager(
                tenant_id=key.tenant_id,
                app_user_id=key.app_user_id,
                bot_instance_id=key.bot_instance_id,
                cred_path=self._cred_path(key),
            )
        return self._channels[key.value]

    async def start_channel(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str | None = None,
        force_login: bool = False,
    ) -> dict:
        channel = self.get_channel(
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            bot_instance_id=bot_instance_id,
        )
        return await channel.start(force_login=force_login)

    async def stop_channel(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str | None = None,
    ) -> dict:
        channel = self.get_channel(
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            bot_instance_id=bot_instance_id,
        )
        return await channel.stop()

    async def get_channel_status(
        self,
        *,
        tenant_id: str,
        app_user_id: str,
        bot_instance_id: str | None = None,
    ) -> dict:
        channel = self.get_channel(
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            bot_instance_id=bot_instance_id,
        )
        return await channel.get_status()

    async def stop_all(self) -> None:
        for channel in list(self._channels.values()):
            await channel.stop()


_channel_manager: WeChatBotChannelManager | None = None


def get_wechatbot_channel_manager() -> WeChatBotChannelManager:
    """Return the global Mode B channel manager."""
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = WeChatBotChannelManager()
    return _channel_manager

