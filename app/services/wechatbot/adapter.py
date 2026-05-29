"""
WeChat Bot SDK 适配器模块

负责：
- SDK 的延迟导入（wechatbot-sdk 可选）
- 回调函数的注册
- 与 WeChat iLink Bot 服务的连接管理
- 消息类型路由（文本/媒体）
"""
import asyncio
import hashlib
import inspect
import logging
from typing import TYPE_CHECKING

from app.config import settings

from .tenant import resolve_tenant_context_async

if TYPE_CHECKING:
    from .manager import WeChatBotManager

logger = logging.getLogger(__name__)


class WeChatBotAdapter:
    """
    WeChat Bot SDK 适配器

    封装 wechatbot-sdk 的导入和回调注册。
    当 WECHATBOT_ENABLED=false 或 SDK 未安装时，提供友好的降级处理。
    """

    def __init__(self, *, cred_path: str | None = None):
        self._bot = None
        self._manager = None
        self._cred_path = cred_path
        self._sdk_available = False
        self._media_handler = None
        self._login_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._qr_future: asyncio.Future | None = None
        self._check_sdk()

    def _check_sdk(self) -> None:
        """检查目标 wechatbot SDK 是否可用。"""
        try:
            import wechatbot  # type: ignore  # noqa: F401
            self._sdk_available = True
            logger.info("wechatbot SDK 可用")
        except ImportError:
            self._sdk_available = False
            logger.warning(
                "wechatbot SDK 未安装，WeChatBot 功能不可用。"
                "请运行: pip install 'cc-agent-sdk[wechatbot]' 来安装。"
            )

    def set_manager(self, manager: "WeChatBotManager") -> None:
        """设置 Manager 实例"""
        self._manager = manager

    async def start_login(self, force: bool = False) -> dict:
        """
        发起登录流程，获取二维码

        Returns:
            dict: 包含 qrcode_url 或错误信息
        """
        if not self._sdk_available:
            raise RuntimeError(
                "wechatbot SDK 未安装或不可用。"
                "请运行: pip install 'cc-agent-sdk[wechatbot]' 来安装。"
            )

        try:
            from wechatbot import WeChatBot

            # 创建 Bot 客户端
            self._bot = self._create_bot(WeChatBot)

            # 注册回调
            self._register_callbacks()

            # 发起登录。真实 SDK 的 login() 会阻塞到扫码确认，所以后台执行，
            # 当前接口只等待二维码回调，便于 /wechatbot/start 立即返回二维码。
            loop = asyncio.get_running_loop()
            self._qr_future = loop.create_future()
            self._login_task = asyncio.create_task(self._login_and_start(force=force))

            try:
                qrcode_url = await asyncio.wait_for(self._qr_future, timeout=15.0)
            except TimeoutError:
                # 如果本地已有有效凭证，login 可能不会产生二维码而是直接进入 start。
                qrcode_url = None

            return {
                "qrcode_url": qrcode_url,
                "login_token": None,
            }

        except Exception as e:
            logger.exception("登录失败")
            raise RuntimeError(f"登录失败: {e}") from e

    async def _login_and_start(self, force: bool = False) -> None:
        """后台完成登录；成功后启动 SDK 长轮询。"""
        try:
            await self._bot.login(force=force)
            if self._manager:
                self._manager.on_login_success()
            if hasattr(self._bot, "start"):
                self._start_task = asyncio.create_task(self._start_bot_loop())
                if self._manager:
                    self._manager.on_bot_started()
        except Exception as exc:
            logger.exception("WeChatBot 登录流程异常")
            if self._qr_future and not self._qr_future.done():
                self._qr_future.set_exception(exc)
            if self._manager:
                self._manager.on_error(str(exc))

    def _create_bot(self, bot_cls):
        """按目标 SDK README 的参数创建 Bot，兼容不同构造签名。"""
        kwargs = {
            "base_url": settings.wechatbot_base_url,
            "cred_path": self._cred_path or settings.wechatbot_cred_path,
            "on_qr_url": self._on_qr_url,
            "on_scanned": self._on_scanned,
            "on_expired": self._on_expired,
            "on_error": self._on_error,
        }
        try:
            signature = inspect.signature(bot_cls)
            supported = {k: v for k, v in kwargs.items() if k in signature.parameters}
            return bot_cls(**supported)
        except (TypeError, ValueError):
            return bot_cls(**kwargs)

    async def _start_bot_loop(self) -> None:
        """后台启动 SDK 消息循环。"""
        try:
            await self._bot.start()
            if self._manager:
                self._manager.on_bot_started()
        except Exception as exc:
            logger.exception("WeChatBot 消息循环异常")
            if self._manager:
                self._manager.on_error(str(exc))

    @staticmethod
    def _extract_attr(obj, *names: str):
        if isinstance(obj, dict):
            for name in names:
                if name in obj:
                    return obj[name]
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    def _register_callbacks(self) -> None:
        """注册 SDK 回调函数"""
        if self._bot is None:
            return

        if hasattr(self._bot, "on_login_success"):
            self._bot.on_login_success(self._on_login_success)
        if hasattr(self._bot, "on_bot_started"):
            self._bot.on_bot_started(self._on_bot_started)
        if hasattr(self._bot, "on_message"):
            self._bot.on_message(self._on_message_sdk)
        if hasattr(self._bot, "on_error"):
            self._bot.on_error(self._on_error)

    def _on_qr_url(self, qrcode_url: str) -> None:
        """二维码 URL 回调。"""
        if self._manager:
            self._manager.on_qrcode_ready(qrcode_url)
        if self._qr_future and not self._qr_future.done():
            self._qr_future.set_result(qrcode_url)

    def _on_scanned(self, data=None) -> None:
        """扫码成功回调；此时尚未拿到服务端凭证，不等于登录成功。"""
        if self._manager:
            self._manager.on_qrcode_scanned()

    def _on_expired(self, data=None) -> None:
        """单次二维码过期回调；SDK 可能会刷新二维码继续登录。"""
        if self._manager:
            self._manager.on_qrcode_expired()

    def _on_login_success(self, data: dict) -> None:
        """登录成功回调"""
        logger.info("收到登录成功事件")
        if self._manager:
            self._manager.on_login_success()

    def _on_bot_started(self, data: dict) -> None:
        """Bot 启动完成回调"""
        logger.info("收到 Bot 启动完成事件")
        if self._manager:
            self._manager.on_bot_started()

    def _get_media_handler(self):
        """获取媒体处理器（延迟导入）"""
        if self._media_handler is None:
            from .media_handler import get_media_handler
            self._media_handler = get_media_handler()
        return self._media_handler

    async def _on_message_sdk(self, message) -> None:
        """处理真实 SDK 的 IncomingMessage 对象。"""
        user_id = getattr(message, "user_id", "")
        message_type = str(getattr(message, "type", "text"))
        text = getattr(message, "text", "") or ""

        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        logger.info("收到微信消息: user_hash=%s, type=%s", user_id_hash, message_type)

        raw_message = self._message_to_raw_dict(message)
        await self._handle_message_async(user_id, message_type, text, raw_message)

    def _message_to_raw_dict(self, message) -> dict:
        """将 SDK 消息对象转换为内部处理使用的 dict。"""
        raw = getattr(message, "raw", {}) or {}
        message_type = str(getattr(message, "type", "text"))
        result = dict(raw) if isinstance(raw, dict) else {}
        result.setdefault("url", self._extract_media_url(message, message_type))
        result.setdefault("file_name", self._extract_file_name(message))
        result.setdefault("file_size", self._extract_file_size(message))
        return result

    @staticmethod
    def _extract_media_url(message, message_type: str) -> str | None:
        collection_name = {
            "image": "images",
            "voice": "voices",
            "file": "files",
            "video": "videos",
        }.get(message_type)
        if not collection_name:
            return None
        items = getattr(message, collection_name, None) or []
        if not items:
            return None
        media = getattr(items[0], "media", None)
        return getattr(items[0], "url", None) or getattr(media, "url", None)

    @staticmethod
    def _extract_file_name(message) -> str | None:
        files = getattr(message, "files", None) or []
        return getattr(files[0], "file_name", None) if files else None

    @staticmethod
    def _extract_file_size(message) -> int | None:
        files = getattr(message, "files", None) or []
        return getattr(files[0], "size", None) if files else None

    def _on_message(self, message: dict) -> None:
        """
        收到消息回调

        Args:
            message: 消息字典，包含 user_id, text, type 等字段
        """
        user_id = message.get("user_id", "")
        message_type = message.get("type", "text")
        text = message.get("text", "")

        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        logger.info("收到微信消息: user_hash=%s, type=%s", user_id_hash, message_type)

        if self._manager:
            # 异步处理消息（不阻塞回调线程）
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._handle_message_async(user_id, message_type, text, message))
                else:
                    loop.run_until_complete(self._handle_message_async(user_id, message_type, text, message))
            except Exception as e:
                logger.exception(f"处理消息失败: {e}")

    async def _handle_message_async(self, user_id: str, message_type: str, text: str, raw_message: dict) -> None:
        """
        异步处理消息

        Args:
            user_id: 用户 ID
            message_type: 消息类型
            text: 消息文本
            raw_message: 原始消息字典
        """
        import time

        from .audit import get_audit_logger
        from .metrics import get_wechatbot_metrics

        start_time = time.time()
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        audit_logger = get_audit_logger()
        metrics = get_wechatbot_metrics()
        media_handler = self._get_media_handler()

        allowed_user_ids = set(settings.wechatbot_allowed_user_ids)
        if allowed_user_ids and user_id not in allowed_user_ids:
            logger.warning("拒绝未授权微信媒体消息: user_hash=%s", user_id_hash)
            if self.is_connected:
                await self.send_message(user_id, "当前微信用户未被授权使用机器人。")
            return

        # 检查是否为媒体消息
        if not media_handler.is_media_message(message_type):
            # 文本消息统一交给 manager 处理，确保未绑定用户仍可执行 /bind、/help、/me。
            if self._manager:
                response = await self._manager.handle_message(user_id, text)
                if response and self.is_connected:
                    await self.send_message(user_id, response)
            return

        tenant_context = await resolve_tenant_context_async(user_id)
        if tenant_context is None:
            if self.is_connected:
                await self.send_message(user_id, "你还没有绑定系统账号。请先发送 /bind 绑定码。")
            return

        conversation_id = (
            f"wechat:{tenant_context.tenant_id}:"
            f"{tenant_context.bot_instance_id}:{tenant_context.user_id_hash}"
        )

        if media_handler.is_media_message(message_type):
            # 构建媒体消息对象
            from .media_handler import MediaMessage
            media = MediaMessage(
                user_id=user_id,
                message_type=message_type,
                text=text,
                file_url=raw_message.get("url"),
                file_name=raw_message.get("file_name") or raw_message.get("filename"),
                file_size=raw_message.get("file_size") or raw_message.get("size"),
                mime_type=raw_message.get("mime_type") or raw_message.get("content_type"),
                raw=raw_message,
            )

            # 记录媒体消息审计日志
            audit_entry = audit_logger.log_media_received(
                user_id=user_id,
                conversation_id=conversation_id,
                message_type=message_type,
                file_name=media.file_name,
                tenant_id=tenant_context.tenant_id,
                app_user_id=tenant_context.app_user_id,
            )

            # 记录媒体消息指标
            metrics.record_message_received(message_type)

            try:
                response = await media_handler.handle_media(media)

                # 记录处理完成
                processing_time_ms = (time.time() - start_time) * 1000
                policy = settings.wechatbot_media_policy

                if response:
                    audit_logger.log_completed(
                        audit_entry,
                        response_preview=response[:100],
                        processing_time_ms=processing_time_ms,
                    )
                    metrics.record_media_handled(message_type, policy, success=True)
                    await self.send_message(user_id, response)
                else:
                    audit_logger.log_ignored(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_type=message_type,
                        reason="no_response",
                        tenant_id=tenant_context.tenant_id,
                        app_user_id=tenant_context.app_user_id,
                    )

            except Exception as e:
                processing_time_ms = (time.time() - start_time) * 1000
                logger.exception(f"媒体消息处理失败: {e}")

                audit_logger.log_failed(
                    audit_entry,
                    error_message=f"{type(e).__name__}: {str(e)[:200]}",
                    processing_time_ms=processing_time_ms,
                )
                metrics.record_media_handled(message_type, settings.wechatbot_media_policy, success=False)
                metrics.record_error(type(e).__name__, message_type)

                if self.is_connected:
                    await self.send_message(user_id, f"处理{media_handler._get_type_name(message_type)}时出现错误，请稍后再试。")

    def _on_error(self, error) -> None:
        """错误回调"""
        error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        logger.error(f"收到错误事件: {error_msg}")
        if self._manager:
            self._manager.on_error(error_msg)

    async def stop(self) -> None:
        """停止 Bot"""
        if self._bot is not None:
            try:
                if self._login_task and not self._login_task.done():
                    self._login_task.cancel()
                if self._start_task and not self._start_task.done():
                    self._start_task.cancel()
                result = self._bot.stop()
                if inspect.isawaitable(result):
                    await result
            except Exception as e:
                logger.warning(f"停止 Bot 时出现警告: {e}")
            finally:
                self._bot = None
                self._login_task = None
                self._start_task = None
                self._qr_future = None

    async def send_message(self, user_id: str, text: str) -> dict:
        """
        发送消息给用户

        Args:
            user_id: 用户 ID
            text: 消息文本

        Returns:
            dict: 发送结果
        """
        if not self._sdk_available or self._bot is None:
            return {"success": False, "error": "Bot 未连接"}

        try:
            # 按配置的分块大小拆分消息
            chunk_size = settings.wechatbot_reply_chunk_size
            chunks = self._split_text(text, chunk_size)

            results = []
            for index, chunk in enumerate(chunks):
                result = await self._send_chunk(user_id, chunk)
                results.append(result)
                if index < len(chunks) - 1 and settings.wechatbot_reply_chunk_interval_seconds > 0:
                    await asyncio.sleep(settings.wechatbot_reply_chunk_interval_seconds)

            return {"success": True, "chunks_sent": len(chunks), "results": results}

        except Exception as e:
            logger.exception(f"发送消息失败: {e}")
            return {"success": False, "error": str(e)}

    async def _send_chunk(self, user_id: str, chunk: str):
        """兼容目标 SDK 的 reply/send_message 发送接口。"""
        if hasattr(self._bot, "send"):
            return await self._bot.send(user_id, chunk)
        if hasattr(self._bot, "send_message"):
            try:
                return await self._bot.send_message(user_id, chunk)
            except TypeError:
                return await self._bot.send_message({"user_id": user_id, "text": chunk})
        raise RuntimeError("当前 SDK 不支持 send/send_message")

    async def send_typing(self, user_id: str) -> None:
        """如果 SDK 支持，则发送正在输入状态。"""
        if not self._bot or not hasattr(self._bot, "send_typing"):
            return
        result = self._bot.send_typing(user_id)
        if inspect.isawaitable(result):
            await result

    async def stop_typing(self, user_id: str) -> None:
        """如果 SDK 支持，则停止正在输入状态。"""
        if not self._bot or not hasattr(self._bot, "stop_typing"):
            return
        result = self._bot.stop_typing(user_id)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _split_text(text: str, chunk_size: int) -> list[str]:
        """
        将文本拆分为小块

        Args:
            text: 原始文本
            chunk_size: 每块最大字符数

        Returns:
            list[str]: 拆分后的文本块列表
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 <= chunk_size:
                current_chunk += (line + "\n") if current_chunk else line
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # 如果单行本身就超过 chunk_size，按字符拆分
                while len(line) > chunk_size:
                    chunks.append(line[:chunk_size])
                    line = line[chunk_size:]
                current_chunk = line

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    @property
    def is_connected(self) -> bool:
        """检查 Bot 是否已连接"""
        return self._bot is not None and self._sdk_available
