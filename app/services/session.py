"""
会话管理服务
"""
import uuid
import asyncio
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Session:
    """
    会话信息

    每个会话通过唯一的 id 标识。会话隔离规则：
    - 不传 conversationId：自动生成新 UUID，每次请求独立
    - 传不同 conversationId：不同会话，相互隔离
    - 传相同 conversationId：共享会话，用于继续对话（预期行为）
    """
    id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    cwd: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def touch(self):
        """更新最后活跃时间"""
        self.last_active = datetime.now()


class SessionManager:
    """
    会话管理器

    注意事项：
    1. 会话存储在内存中，服务重启后丢失
    2. 多 Worker 部署时，会话无法跨 Worker 共享
    3. 如需持久化或分布式支持，应使用 Redis 等外部存储
    """

    def __init__(self, ttl_minutes: int = 60):
        self._sessions: dict[str, Session] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def create_session(self, cwd: Optional[str] = None) -> Session:
        """创建新会话，自动生成唯一 ID"""
        async with self._lock:
            session_id = str(uuid.uuid4())
            session = Session(id=session_id, cwd=cwd)
            self._sessions[session_id] = session
            return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """获取已有会话"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.touch()
            return session

    async def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None
    ) -> Session:
        """
        获取或创建会话

        - session_id 为 None：创建新会话（独立）
        - session_id 存在且能找到：返回已有会话（继续对话）
        - session_id 存在但找不到：创建新会话（该 ID 首次使用）
        """
        if session_id:
            session = await self.get_session(session_id)
            if session:
                # 更新 cwd 如果提供了新的
                if cwd and session.cwd != cwd:
                    session.cwd = cwd
                return session
            # session_id 提供了但会话不存在，用该 ID 创建
            async with self._lock:
                session = Session(id=session_id, cwd=cwd)
                self._sessions[session_id] = session
                return session
        # 未提供 session_id，生成新的
        return await self.create_session(cwd=cwd)

    async def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    async def cleanup_expired(self) -> int:
        """清理过期会话"""
        async with self._lock:
            now = datetime.now()
            expired = [
                sid for sid, session in self._sessions.items()
                if now - session.last_active > self._ttl
            ]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    async def list_sessions(self) -> list[Session]:
        """列出所有会话"""
        async with self._lock:
            return list(self._sessions.values())

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_sessions": len(self._sessions),
            "ttl_minutes": self._ttl.total_seconds() / 60
        }


# 全局会话管理器实例
session_manager = SessionManager()
