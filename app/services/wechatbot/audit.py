"""
WeChat Bot 审计日志模块

负责：
- 记录所有消息处理的审计日志
- 追踪消息状态、耗时、错误摘要
- 日志中不出现明文 user_id
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class MessageDirection(str, Enum):
    """消息方向"""
    INBOUND = "inbound"   # 用户发来的消息
    OUTBOUND = "outbound"  # 机器人回复


class MessageStatus(str, Enum):
    """消息处理状态"""
    RECEIVED = "received"       # 已接收
    PROCESSING = "processing"   # 处理中
    COMPLETED = "completed"      # 处理完成
    FAILED = "failed"            # 处理失败
    RATE_LIMITED = "rate_limited"  # 被限流
    IGNORED = "ignored"          # 被忽略（媒体策略）


@dataclass
class AuditEntry:
    """审计日志条目"""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    event_type: str = "message"  # message, media, command, error
    user_id_hash: str = ""       # 脱敏后的 user_id
    conversation_id: str = ""
    tenant_id: str | None = None
    app_user_id: str | None = None
    direction: MessageDirection = MessageDirection.INBOUND
    status: MessageStatus = MessageStatus.RECEIVED
    message_type: str = "text"   # text, image, voice, file, video
    content_preview: str = ""     # 内容预览（脱敏）
    processing_time_ms: float = 0.0
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        d = asdict(self)
        d["direction"] = self.direction.value
        d["status"] = self.status.value
        return d

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class AuditLogger:
    """
    审计日志记录器

    记录微信消息处理的完整审计日志。
    日志中不出现明文 user_id，仅记录哈希值。
    """

    def __init__(self):
        self._enabled = settings.wechatbot_audit_enabled
        self._log_messages = []  # 内存缓存，生产环境建议使用数据库或日志服务

    def set_enabled(self, enabled: bool) -> None:
        """设置是否启用审计日志"""
        self._enabled = enabled

    def log_received(
        self,
        user_id: str,
        conversation_id: str,
        message_type: str,
        content: str,
        tenant_id: str | None = None,
        app_user_id: str | None = None,
    ) -> AuditEntry:
        """
        记录消息接收

        Args:
            user_id: 用户 ID（明文）
            conversation_id: 会话 ID
            message_type: 消息类型
            content: 消息内容

        Returns:
            AuditEntry: 审计条目
        """
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        entry = AuditEntry(
            event_type="message",
            user_id_hash=user_id_hash,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            message_type=message_type,
            content_preview=content[:100] if settings.wechatbot_audit_log_content_preview and content else "",
        )

        self._log_entry(entry)
        return entry

    def log_media_received(
        self,
        user_id: str,
        conversation_id: str,
        message_type: str,
        file_name: str | None = None,
        tenant_id: str | None = None,
        app_user_id: str | None = None,
    ) -> AuditEntry:
        """
        记录媒体消息接收

        Args:
            user_id: 用户 ID（明文）
            conversation_id: 会话 ID
            message_type: 消息类型
            file_name: 文件名

        Returns:
            AuditEntry: 审计条目
        """
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        entry = AuditEntry(
            event_type="media",
            user_id_hash=user_id_hash,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            message_type=message_type,
            content_preview=file_name[:50] if settings.wechatbot_audit_log_content_preview and file_name else "",
            extra={"file_name": file_name} if file_name else {},
        )

        self._log_entry(entry)
        return entry

    def log_processing_start(self, entry: AuditEntry) -> None:
        """标记开始处理"""
        entry.status = MessageStatus.PROCESSING
        entry.processing_time_ms = 0.0
        self._log_entry(entry)

    def log_completed(
        self,
        entry: AuditEntry,
        response_preview: str = "",
        processing_time_ms: float = 0.0,
    ) -> None:
        """
        记录处理完成

        Args:
            entry: 审计条目
            response_preview: 回复预览
            processing_time_ms: 处理耗时（毫秒）
        """
        entry.status = MessageStatus.COMPLETED
        entry.direction = MessageDirection.OUTBOUND
        entry.processing_time_ms = processing_time_ms
        entry.content_preview = response_preview[:100] if settings.wechatbot_audit_log_content_preview and response_preview else ""
        self._log_entry(entry)

    def log_failed(
        self,
        entry: AuditEntry,
        error_message: str,
        processing_time_ms: float = 0.0,
    ) -> None:
        """
        记录处理失败

        Args:
            entry: 审计条目
            error_message: 错误信息
            processing_time_ms: 处理耗时（毫秒）
        """
        entry.status = MessageStatus.FAILED
        entry.error_message = error_message[:200]  # 截断
        entry.processing_time_ms = processing_time_ms
        self._log_entry(entry)

    def log_rate_limited(
        self,
        user_id: str,
        conversation_id: str,
        message_type: str,
        tenant_id: str | None = None,
        app_user_id: str | None = None,
    ) -> AuditEntry:
        """
        记录限流

        Args:
            user_id: 用户 ID（明文）
            conversation_id: 会话 ID
            message_type: 消息类型

        Returns:
            AuditEntry: 审计条目
        """
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        entry = AuditEntry(
            event_type="message",
            user_id_hash=user_id_hash,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RATE_LIMITED,
            message_type=message_type,
            error_message="rate_limit_exceeded",
        )

        self._log_entry(entry)
        return entry

    def log_ignored(
        self,
        user_id: str,
        conversation_id: str,
        message_type: str,
        reason: str,
        tenant_id: str | None = None,
        app_user_id: str | None = None,
    ) -> AuditEntry:
        """
        记录忽略的消息

        Args:
            user_id: 用户 ID（明文）
            conversation_id: 会话 ID
            message_type: 消息类型
            reason: 忽略原因

        Returns:
            AuditEntry: 审计条目
        """
        import hashlib
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

        entry = AuditEntry(
            event_type="message",
            user_id_hash=user_id_hash,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.IGNORED,
            message_type=message_type,
            error_message=reason,
        )

        self._log_entry(entry)
        return entry

    def log_bind_token_created(
        self,
        *,
        token_preview: str,
        tenant_id: str,
        app_user_id: str,
        expires_at: str,
    ) -> AuditEntry:
        """记录绑定码创建事件；不记录明文 token。"""
        entry = AuditEntry(
            event_type="bind_token_created",
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.COMPLETED,
            message_type="bind_token",
            extra={"token_preview": token_preview, "expires_at": expires_at},
        )
        self._log_entry(entry)
        return entry

    def log_bind_success(self, *, user_id_hash: str, tenant_id: str, app_user_id: str) -> AuditEntry:
        """记录微信绑定成功事件。"""
        entry = AuditEntry(
            event_type="bind_success",
            user_id_hash=user_id_hash,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.COMPLETED,
            message_type="bind",
        )
        self._log_entry(entry)
        return entry

    def log_bind_failed(self, *, user_id_hash: str, reason: str) -> AuditEntry:
        """记录微信绑定失败事件；不记录明文 token。"""
        entry = AuditEntry(
            event_type="bind_failed",
            user_id_hash=user_id_hash,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.FAILED,
            message_type="bind",
            error_message=reason[:200],
        )
        self._log_entry(entry)
        return entry

    def log_unbind(
        self,
        *,
        user_id_hash: str,
        tenant_id: str,
        app_user_id: str | None = None,
    ) -> AuditEntry:
        """记录微信解绑事件。"""
        entry = AuditEntry(
            event_type="unbind",
            user_id_hash=user_id_hash,
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.COMPLETED,
            message_type="unbind",
        )
        self._log_entry(entry)
        return entry

    def _log_entry(self, entry: AuditEntry) -> None:
        """
        内部方法：记录审计条目

        Args:
            entry: 审计条目
        """
        if not self._enabled:
            return

        try:
            # 记录到日志
            log_data = entry.to_json()
            logger.info(f"AUDIT: {log_data}")

            # 内存缓存（生产环境可能需要批量写入数据库）
            self._log_messages.append(entry)

            # 限制内存缓存大小
            if len(self._log_messages) > 10000:
                self._log_messages = self._log_messages[-5000:]

        except Exception as e:
            logger.warning(f"审计日志记录失败: {e}")

    def get_recent_entries(
        self,
        user_id_hash: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """
        获取最近的审计条目

        Args:
            user_id_hash: 过滤特定用户（可选）
            limit: 返回数量限制

        Returns:
            list[AuditEntry]: 审计条目列表
        """
        entries = self._log_messages

        if user_id_hash:
            entries = [e for e in entries if e.user_id_hash == user_id_hash]

        return entries[-limit:]

    def get_stats(self) -> dict:
        """
        获取审计统计信息

        Returns:
            dict: 统计信息
        """
        total = len(self._log_messages)
        by_status = {}
        by_type = {}

        for entry in self._log_messages:
            status = entry.status.value
            msg_type = entry.message_type

            by_status[status] = by_status.get(status, 0) + 1
            by_type[msg_type] = by_type.get(msg_type, 0) + 1

        return {
            "total_entries": total,
            "by_status": by_status,
            "by_message_type": by_type,
        }


# 全局单例
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """获取全局审计日志记录器"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


class AuditContext:
    """
    审计上下文管理器

    用于自动记录处理耗时和状态
    """

    def __init__(
        self,
        audit_logger: AuditLogger,
        entry: AuditEntry,
    ):
        self._audit_logger = audit_logger
        self._entry = entry
        self._start_time: float | None = None

    def __enter__(self) -> "AuditContext":
        self._start_time = time.time()
        self._audit_logger.log_processing_start(self._entry)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed_ms = (time.time() - self._start_time) * 1000 if self._start_time else 0

        if exc_type is not None:
            self._audit_logger.log_failed(
                self._entry,
                error_message=f"{exc_type.__name__}: {exc_val}",
                processing_time_ms=elapsed_ms,
            )
        else:
            self._audit_logger.log_completed(
                self._entry,
                processing_time_ms=elapsed_ms,
            )
