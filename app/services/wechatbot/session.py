"""
WeChat Bot 会话管理模块

负责：
- 微信 user_id 到 conversationId 的映射
- 会话元数据存储（最后活跃时间、消息计数等）
- 会话重置
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _hash_user_id(user_id: str) -> str:
    """生成日志使用的微信用户哈希。"""
    import hashlib

    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


@dataclass
class WeChatSession:
    """微信会话元数据"""
    user_id: str                    # 微信用户 ID（明文）
    user_id_hash: str               # 微信用户 ID 哈希（用于日志）
    conversation_id: str            # 映射到的 conversationId
    tenant_id: str = "default"       # SaaS 租户 ID（Mode A）
    app_user_id: str | None = None   # 业务用户 ID（可选）
    bot_instance_id: str = "default"
    space_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    message_count: int = 0          # 累计消息数
    default_mode: str = "agent"     # 默认模式
    last_error: str | None = None   # 最近一次错误


class WeChatSessionManager:
    """
    微信会话管理器

    维护 user_id -> conversationId 的映射，
    并记录会话元数据用于观测和限流。
    """

    def __init__(self):
        # session_key -> WeChatSession. Mode A uses
        # tenant_id:bot_instance_id:user_id_hash to keep tenant state isolated.
        self._sessions: dict[str, WeChatSession] = {}
        # conversation_id -> session_key（反向索引）
        self._conversation_index: dict[str, str] = {}
        # 简单内存存储，生产环境建议使用 Redis
        # 限流：rate_limit_key -> (timestamp, count)
        self._rate_limit: dict[str, list[float]] = defaultdict(list)

    def get_or_create_session(
        self,
        user_id: str,
        conversation_id: str,
        default_mode: str = "agent",
        tenant_id: str = "default",
        app_user_id: str | None = None,
        bot_instance_id: str = "default",
        space_id: str | None = None,
    ) -> WeChatSession:
        """
        获取或创建会话

        Args:
            user_id: 微信用户 ID
            conversation_id: conversationId
            default_mode: 默认模式

        Returns:
            WeChatSession: 会话对象
        """
        user_id_hash = _hash_user_id(user_id)
        session_key = self.build_session_key(
            tenant_id=tenant_id,
            bot_instance_id=bot_instance_id,
            user_id_hash=user_id_hash,
        )

        if session_key not in self._sessions:
            session = WeChatSession(
                user_id=user_id,
                user_id_hash=user_id_hash,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                app_user_id=app_user_id,
                bot_instance_id=bot_instance_id,
                space_id=space_id,
                default_mode=default_mode,
            )
            self._sessions[session_key] = session
            self._conversation_index[conversation_id] = session_key

            logger.info(f"创建新微信会话: user_hash={user_id_hash}, conv={conversation_id}")
        else:
            session = self._sessions[session_key]
            # 更新最后活跃时间
            session.last_active_at = time.time()
            previous_conversation_id = session.conversation_id
            session.conversation_id = conversation_id
            session.tenant_id = tenant_id
            session.app_user_id = app_user_id
            session.bot_instance_id = bot_instance_id
            session.space_id = space_id
            session.default_mode = default_mode
            if previous_conversation_id != conversation_id:
                self._conversation_index.pop(previous_conversation_id, None)
            self._conversation_index[conversation_id] = session_key

        return session

    @staticmethod
    def build_session_key(tenant_id: str, bot_instance_id: str, user_id_hash: str) -> str:
        """Build the tenant-scoped in-memory session key for Mode A."""
        return f"{tenant_id}:{bot_instance_id}:{user_id_hash}"

    def _session_key_for_user(
        self,
        user_id: str,
        tenant_id: str = "default",
        bot_instance_id: str = "default",
    ) -> str:
        return self.build_session_key(
            tenant_id=tenant_id,
            bot_instance_id=bot_instance_id,
            user_id_hash=_hash_user_id(user_id),
        )

    def get_session_by_user_id(
        self,
        user_id: str,
        tenant_id: str = "default",
        bot_instance_id: str = "default",
    ) -> WeChatSession | None:
        """通过 user_id 获取会话"""
        return self._sessions.get(self._session_key_for_user(user_id, tenant_id, bot_instance_id))

    def get_session_by_conversation_id(self, conversation_id: str) -> WeChatSession | None:
        """通过 conversationId 获取会话"""
        session_key = self._conversation_index.get(conversation_id)
        if session_key:
            return self._sessions.get(session_key)
        return None

    def reset_session(
        self,
        user_id: str,
        tenant_id: str = "default",
        bot_instance_id: str = "default",
    ) -> bool:
        """
        重置会话（删除指定用户的会话数据）

        Args:
            user_id: 微信用户 ID

        Returns:
            bool: 是否成功重置
        """
        session_key = self._session_key_for_user(user_id, tenant_id, bot_instance_id)
        if session_key not in self._sessions:
            logger.warning("尝试重置不存在的会话: user_hash=%s", _hash_user_id(user_id))
            return False

        session = self._sessions[session_key]
        conversation_id = session.conversation_id

        # 清理索引
        del self._conversation_index[conversation_id]
        del self._sessions[session_key]

        # 清理当前租户维度的限流记录
        self._rate_limit.pop(session_key, None)

        logger.info(f"重置会话: user_hash={session.user_id_hash}, conv={conversation_id}")
        return True

    def record_message(
        self,
        user_id: str,
        tenant_id: str = "default",
        bot_instance_id: str = "default",
    ) -> None:
        """
        记录用户发送消息

        Args:
            user_id: 微信用户 ID
        """
        session = self.get_session_by_user_id(user_id, tenant_id, bot_instance_id)
        if session:
            session.message_count += 1
            session.last_active_at = time.time()

    def record_error(
        self,
        user_id: str,
        error: str,
        tenant_id: str = "default",
        bot_instance_id: str = "default",
    ) -> None:
        """
        记录最近一次错误

        Args:
            user_id: 微信用户 ID
            error: 错误信息
        """
        session = self.get_session_by_user_id(user_id, tenant_id, bot_instance_id)
        if session:
            session.last_error = error[:200]  # 截断

    def check_rate_limit(
        self,
        user_id: str,
        max_messages: int = 20,
        window_seconds: float = 60.0,
        burst_limit: int = 5,
    ) -> tuple[bool, str | None]:
        """
        检查用户是否超过限流阈值

        支持两种限流：
        1. 滑动窗口限流：限制一段时间内的总消息数
        2. 突发限流：限制短时间内的连续消息数

        Args:
            user_id: 微信用户 ID
            max_messages: 窗口内最大消息数
            window_seconds: 时间窗口（秒）
            burst_limit: 突发限制（短时间内的最大连续消息数）

        Returns:
            tuple[bool, str | None]: (是否在限制内, 限流类型)
                                    - (True, None) 表示通过
                                    - (False, "window") 表示窗口限流
                                    - (False, "burst") 表示突发限流
        """
        now = time.time()
        window_start = now - window_seconds
        burst_window = 5.0  # 5秒内的消息视为"突发"

        # 清理过期记录
        if user_id in self._rate_limit:
            self._rate_limit[user_id] = [
                ts for ts in self._rate_limit[user_id]
                if ts > window_start
            ]
        else:
            self._rate_limit[user_id] = []

        # 检查突发限制（最近 5 秒内的消息数）
        burst_start = now - burst_window
        recent_messages = [ts for ts in self._rate_limit[user_id] if ts > burst_start]

        if len(recent_messages) >= burst_limit:
            logger.warning("微信用户触发突发限流: user_hash=%s, burst=%s", _hash_user_id(user_id), burst_limit)
            return False, "burst"

        # 检查窗口限制
        if len(self._rate_limit[user_id]) >= max_messages:
            logger.warning(
                "微信用户触发窗口限流: user_hash=%s, max=%s, window=%ss",
                _hash_user_id(user_id),
                max_messages,
                window_seconds,
            )
            return False, "window"

        # 记录本次消息
        self._rate_limit[user_id].append(now)
        return True, None

    def get_stats(self) -> dict:
        """
        获取会话统计信息

        Returns:
            dict: 统计信息
        """
        tenants = {s.tenant_id for s in self._sessions.values()}
        return {
            "total_sessions": len(self._sessions),
            "active_sessions": sum(
                1 for s in self._sessions.values()
                if time.time() - s.last_active_at < 3600
            ),
            "tenants": sorted(tenants),
        }


# 全局单例
_wechat_session_manager: WeChatSessionManager | None = None


def get_wechat_session_manager() -> WeChatSessionManager:
    """获取全局 WeChatSessionManager 实例"""
    global _wechat_session_manager
    if _wechat_session_manager is None:
        _wechat_session_manager = WeChatSessionManager()
    return _wechat_session_manager
