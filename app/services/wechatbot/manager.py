"""
WeChat Bot 生命周期管理模块

负责：
- Bot 实例的创建、启动、停止、重登录
- 状态管理（未登录/登录中/已登录/运行中/已停止/异常）
- 与 Adapter 配合处理 SDK 回调
- 消息路由与处理协调
"""
import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.config import settings
from .message_router import RouteMode, route_message
from .audit import get_audit_logger
from .metrics import get_wechatbot_metrics

if TYPE_CHECKING:
    from .adapter import WeChatBotAdapter
    from .runner import MessageProcessor

logger = logging.getLogger(__name__)


class BotStatus(str, Enum):
    """Bot 运行状态"""
    STOPPED = "stopped"           # 已停止
    STARTING = "starting"         # 启动中
    LOGGING_IN = "logging_in"     # 登录中（等待扫码）
    LOGGED_IN = "logged_in"       # 已登录（可收发消息）
    RUNNING = "running"           # 运行中
    ERROR = "error"               # 异常


@dataclass
class BotState:
    """Bot 运行时状态"""
    status: BotStatus = BotStatus.STOPPED
    qrcode_url: str | None = None
    login_message: str | None = None
    error_message: str | None = None
    started_at: float | None = None
    login_at: float | None = None


class WeChatBotManager:
    """
    WeChat Bot 生命周期管理器

    封装 Bot 的启动、停止、重登录等操作，并与 Adapter 配合处理消息回调。
    """

    def __init__(self):
        self._state = BotState()
        self._adapter: "WeChatBotAdapter | None" = None
        self._message_processor: "MessageProcessor | None" = None
        self._session_manager = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._message_semaphore = asyncio.Semaphore(settings.wechatbot_max_concurrent_messages)

    @property
    def state(self) -> BotState:
        """获取当前 Bot 状态"""
        return self._state

    @property
    def is_running(self) -> bool:
        """检查 Bot 是否正在运行"""
        return self._state.status in {BotStatus.LOGGING_IN, BotStatus.LOGGED_IN, BotStatus.RUNNING}

    def set_adapter(self, adapter: "WeChatBotAdapter") -> None:
        """设置 Adapter 实例"""
        self._adapter = adapter

    def _get_session_manager(self):
        """获取会话管理器（延迟导入）"""
        if self._session_manager is None:
            from .session import get_wechat_session_manager
            self._session_manager = get_wechat_session_manager()
        return self._session_manager

    def _get_message_processor(self) -> "MessageProcessor":
        """获取消息处理器（延迟导入）"""
        if self._message_processor is None:
            from .runner import get_message_processor
            self._message_processor = get_message_processor()
        return self._message_processor

    async def start(self, force_login: bool = False) -> dict:
        """
        启动 Bot（发起登录流程）

        Returns:
            dict: 包含 qrcode_url 等信息的响应
        """
        if self.is_running:
            return {
                "status": self._state.status.value,
                "message": "Bot 已经在运行中",
                "qrcode_url": self._state.qrcode_url,
            }

        self._state.status = BotStatus.STARTING
        self._state.error_message = None
        self._state.login_message = "正在启动登录流程"

        try:
            if self._adapter is None:
                from .adapter import WeChatBotAdapter
                self._adapter = WeChatBotAdapter()
                self._adapter.set_manager(self)

            self._state.status = BotStatus.LOGGING_IN
            self._state.login_message = "登录流程已启动，等待二维码或复用本地凭证"

            result = await self._adapter.start_login(force=force_login)

            self._state.qrcode_url = result.get("qrcode_url")
            if self._state.status == BotStatus.RUNNING:
                message = "Bot 已运行，已复用本地登录凭证或登录已完成"
            elif self._state.status == BotStatus.LOGGED_IN:
                message = "Bot 已登录，正在启动消息循环"
            elif self._state.qrcode_url:
                message = "请扫码登录"
            else:
                message = "登录流程已启动，等待二维码或复用本地凭证"
            self._state.login_message = message
            return {
                "status": self._state.status.value,
                "message": message,
                "qrcode_url": self._state.qrcode_url,
            }

        except Exception as e:
            logger.exception("WeChatBot 启动失败")
            self._state.status = BotStatus.ERROR
            self._state.error_message = str(e)
            return {
                "status": self._state.status.value,
                "message": f"启动失败: {e}",
                "qrcode_url": None,
            }

    async def stop(self) -> dict:
        """
        停止 Bot

        Returns:
            dict: 停止操作的结果
        """
        if not self.is_running and self._state.status == BotStatus.STOPPED:
            return {
                "status": self._state.status.value,
                "message": "Bot 未运行",
            }

        try:
            if self._adapter:
                await self._adapter.stop()

            self._state.status = BotStatus.STOPPED
            self._state.qrcode_url = None
            self._state.started_at = None
            self._state.login_at = None

            logger.info("WeChatBot 已停止")
            return {
                "status": self._state.status.value,
                "message": "Bot 已停止",
            }

        except Exception as e:
            logger.exception("WeChatBot 停止失败")
            self._state.status = BotStatus.ERROR
            self._state.error_message = str(e)
            return {
                "status": self._state.status.value,
                "message": f"停止失败: {e}",
            }

    async def relogin(self, force: bool = False) -> dict:
        """
        重新发起登录（无需重启 Bot）

        Returns:
            dict: 包含 qrcode_url 的响应
        """
        if force or self.is_running:
            await self.stop()
        return await self.start(force_login=force)

    async def send_message(self, user_id: str, text: str) -> dict:
        """发送运维测试消息。"""
        if not self._adapter or not self._adapter.is_connected:
            return {"success": False, "error": "Bot 未连接"}
        return await self._adapter.send_message(user_id, text)

    async def get_qrcode(self) -> dict:
        """
        获取当前登录二维码（如果正在等待扫码）

        Returns:
            dict: 二维码信息
        """
        if self._state.status != BotStatus.LOGGING_IN:
            return {
                "status": self._state.status.value,
                "message": self._state.login_message or "当前不需要扫码",
                "qrcode_url": None,
            }

        return {
            "status": self._state.status.value,
            "message": self._state.login_message or "等待扫码中",
            "qrcode_url": self._state.qrcode_url,
        }

    async def get_status(self) -> dict:
        """
        获取 Bot 详细状态

        Returns:
            dict: 完整状态信息
        """
        session_stats = {}
        try:
            session_mgr = self._get_session_manager()
            session_stats = session_mgr.get_stats()
        except Exception:
            pass

        return {
            "enabled": settings.wechatbot_enabled,
            "status": self._state.status.value,
            "qrcode_url": self._state.qrcode_url,
            "login_message": self._state.login_message,
            "error_message": self._state.error_message,
            "started_at": self._state.started_at,
            "login_at": self._state.login_at,
            "sessions": session_stats,
        }

    def on_login_success(self) -> None:
        """登录成功回调（由 Adapter 调用）"""
        import time
        self._state.status = BotStatus.LOGGED_IN
        self._state.login_at = time.time()
        self._state.qrcode_url = None
        self._state.login_message = "登录成功，正在启动消息循环"
        self._state.error_message = None
        logger.info("WeChatBot 登录成功")

    def on_bot_started(self) -> None:
        """Bot 启动完成回调（由 Adapter 调用）"""
        import time
        if self._state.status == BotStatus.LOGGED_IN:
            self._state.status = BotStatus.RUNNING
            self._state.started_at = time.time()
            self._state.login_message = "Bot 已运行"
            self._state.error_message = None
            logger.info("WeChatBot 已启动并开始处理消息")

    def on_qrcode_ready(self, qrcode_url: str) -> None:
        """二维码已生成，等待用户扫码。"""
        self._state.status = BotStatus.LOGGING_IN
        self._state.qrcode_url = qrcode_url
        self._state.login_message = "请扫码登录"
        self._state.error_message = None
        logger.info("WeChatBot 登录二维码已生成")

    def on_qrcode_scanned(self) -> None:
        """二维码已扫码，但尚未确认登录。"""
        if self._state.status != BotStatus.RUNNING:
            self._state.status = BotStatus.LOGGING_IN
        self._state.login_message = "二维码已扫码，等待手机确认"
        self._state.error_message = None
        logger.info("WeChatBot 二维码已扫码，等待确认")

    def on_qrcode_expired(self) -> None:
        """单次二维码过期；SDK 可能仍会刷新二维码继续登录。"""
        if self._state.status != BotStatus.RUNNING:
            self._state.status = BotStatus.LOGGING_IN
        self._state.qrcode_url = None
        self._state.login_message = "二维码已过期，等待刷新二维码"
        logger.warning("WeChatBot 登录二维码已过期，等待 SDK 刷新")

    def on_error(self, error: str) -> None:
        """错误回调（由 Adapter 调用）"""
        self._state.status = BotStatus.ERROR
        self._state.error_message = error
        self._state.login_message = f"登录或运行异常: {error}"
        logger.error(f"WeChatBot 错误: {error}")

    async def handle_message(self, user_id: str, text: str) -> str:
        """
        处理收到的消息（核心消息处理入口）

        流程：
        1. 限流检查
        2. 审计日志记录
        3. 指标埋点
        4. 路由决策（命令解析）
        5. 会话管理
        6. 调用消息处理器
        7. 发送回复
        8. 记录完成状态

        Args:
            user_id: 发送消息的用户 ID
            text: 消息文本

        Returns:
            str: 回复文本
        """
        start_time = time.time()
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        allowed_user_ids = set(settings.wechatbot_allowed_user_ids)
        if allowed_user_ids and user_id not in allowed_user_ids:
            logger.warning("拒绝未授权微信用户消息: user_hash=%s", user_id_hash)
            return "当前微信用户未被授权使用机器人。"

        async with self._message_semaphore:
            return await self._handle_message_inner(user_id, text, start_time, user_id_hash)

    async def _handle_message_inner(
        self,
        user_id: str,
        text: str,
        start_time: float,
        user_id_hash: str,
    ) -> str:
        """在全局并发限制内处理单条消息。"""

        # 初始化组件
        session_mgr = self._get_session_manager()
        processor = self._get_message_processor()
        audit_logger = get_audit_logger()
        metrics = get_wechatbot_metrics()

        # 1. 限流检查（增强版，支持 burst 和 window 两种限流）
        allowed, limit_type = session_mgr.check_rate_limit(
            user_id,
            max_messages=settings.wechatbot_rate_limit_per_user,
            window_seconds=float(settings.wechatbot_rate_limit_window),
            burst_limit=settings.wechatbot_rate_limit_burst,
        )

        if not allowed:
            # 记录限流审计日志
            audit_logger.log_rate_limited(
                user_id=user_id,
                conversation_id="",
                message_type="text",
            )

            # 记录限流指标
            metrics.record_rate_limit(user_id_hash)

            return "发送消息太频繁，请稍后再试。" if limit_type == "window" else "发送消息太快了，请稍后再试。"

        # 2. 创建审计条目
        audit_entry = audit_logger.log_received(
            user_id=user_id,
            conversation_id="",  # 暂不确定，先留空
            message_type="text",
            content=text,
        )

        # 3. 记录消息接收指标
        metrics.record_message_received("text")

        try:
            # 4. 路由决策
            default_mode = RouteMode.RAG if settings.wechatbot_default_mode == "rag" else RouteMode.AGENT
            decision = route_message(
                text=text,
                user_id=user_id,
                default_mode=default_mode,
            )

            # 更新审计条目的 conversation_id
            audit_entry.conversation_id = decision.conversation_id

            # 5. 会话管理
            session = session_mgr.get_or_create_session(
                user_id=user_id,
                conversation_id=decision.conversation_id,
                default_mode=default_mode.value,
            )
            session_mgr.record_message(user_id)

            # 6. 处理 RESET 命令
            if decision.mode == RouteMode.RESET:
                session_mgr.reset_session(user_id)
                audit_logger.log_completed(audit_entry, response_preview="会话已重置", processing_time_ms=0.0)
                return "会话已重置，可以开始新对话了。"

            # 7. 调用消息处理器
            await self._send_typing(user_id)
            try:
                reply_text = await processor.process(decision, session)
            finally:
                await self._stop_typing(user_id)

            # 9. 记录完成状态
            processing_time_ms = (time.time() - start_time) * 1000
            audit_logger.log_completed(
                audit_entry,
                response_preview=reply_text[:100] if reply_text else "",
                processing_time_ms=processing_time_ms,
            )
            metrics.record_message_completed(
                message_type="text",
                processing_time_ms=processing_time_ms,
                success=True,
            )

            return reply_text

        except Exception as e:
            processing_time_ms = (time.time() - start_time) * 1000
            logger.exception(f"消息处理失败: {e}")

            # 记录失败状态
            audit_logger.log_failed(
                audit_entry,
                error_message=f"{type(e).__name__}: {str(e)[:200]}",
                processing_time_ms=processing_time_ms,
            )
            metrics.record_message_completed(
                message_type="text",
                processing_time_ms=processing_time_ms,
                success=False,
            )
            metrics.record_error(type(e).__name__, "text")

            return "处理消息时出现错误，请稍后再试。"

    async def _send_typing(self, user_id: str) -> None:
        """SDK 支持时发送 typing 状态，失败不影响主流程。"""
        if not self._adapter or not self._adapter.is_connected:
            return
        try:
            await self._adapter.send_typing(user_id)
        except Exception:
            logger.debug("发送 typing 状态失败", exc_info=True)

    async def _stop_typing(self, user_id: str) -> None:
        """SDK 支持时停止 typing 状态，失败不影响主流程。"""
        if not self._adapter or not self._adapter.is_connected:
            return
        try:
            await self._adapter.stop_typing(user_id)
        except Exception:
            logger.debug("停止 typing 状态失败", exc_info=True)


# 全局单例
_wechatbot_manager: WeChatBotManager | None = None


def get_wechatbot_manager() -> WeChatBotManager:
    """获取全局 WeChatBotManager 实例"""
    global _wechatbot_manager
    if _wechatbot_manager is None:
        _wechatbot_manager = WeChatBotManager()
    return _wechatbot_manager
