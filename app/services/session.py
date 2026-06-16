"""
会话管理服务

支持三种存储后端（SESSION_STORE 环境变量）：
- memory：纯内存，重启后丢失，适合测试
- file：持久化到本地 JSON 文件，重启后自动恢复，适合单机部署
- db：持久化到数据库，支持多 Worker，适合生产环境（存储逻辑待实现）
"""
import uuid
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session 数据模型
# ---------------------------------------------------------------------------

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
        self.last_active = datetime.now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "cwd": self.cwd,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        s = cls(id=data["id"], cwd=data.get("cwd"), metadata=data.get("metadata", {}))
        s.created_at = datetime.fromisoformat(data["created_at"])
        s.last_active = datetime.fromisoformat(data["last_active"])
        return s


# ---------------------------------------------------------------------------
# 存储后端抽象
# ---------------------------------------------------------------------------

class SessionBackend(ABC):
    """存储后端接口，所有后端必须实现此接口"""

    @abstractmethod
    async def load(self, session_id: str) -> Optional[Session]:
        """从持久层加载单个会话，不存在时返回 None"""

    @abstractmethod
    async def save(self, session: Session) -> None:
        """持久化单个会话（新增或更新）"""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """删除单个会话"""

    @abstractmethod
    async def load_all(self) -> list[Session]:
        """启动时批量加载所有会话（仅 file/db 后端有意义）"""

    @abstractmethod
    async def delete_many(self, session_ids: list[str]) -> None:
        """批量删除（用于过期清理）"""


# ---------------------------------------------------------------------------
# memory 后端：无操作，数据仅存在 SessionManager._cache
# ---------------------------------------------------------------------------

class MemoryBackend(SessionBackend):
    """纯内存后端，所有持久化操作均为空操作"""

    async def load(self, session_id: str) -> Optional[Session]:
        return None

    async def save(self, session: Session) -> None:
        pass

    async def delete(self, session_id: str) -> None:
        pass

    async def load_all(self) -> list[Session]:
        return []

    async def delete_many(self, session_ids: list[str]) -> None:
        pass


# ---------------------------------------------------------------------------
# file 后端：整体读写一个 JSON 文件
# ---------------------------------------------------------------------------

class FileBackend(SessionBackend):
    """本地 JSON 文件后端，适合单机部署"""

    def __init__(self, file_path: str):
        self._path = Path(file_path)
        self._cache: dict[str, Session] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            self._loaded = True
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for item in data.get("sessions", []):
                s = Session.from_dict(item)
                self._cache[s.id] = s
        except Exception as e:
            logger.warning(f"[FileBackend] 加载 session 文件失败: {e}")
        self._loaded = True

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"sessions": [s.to_dict() for s in self._cache.values()]}
            self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[FileBackend] 写入 session 文件失败: {e}")

    async def load(self, session_id: str) -> Optional[Session]:
        self._ensure_loaded()
        return self._cache.get(session_id)

    async def save(self, session: Session) -> None:
        self._ensure_loaded()
        self._cache[session.id] = session
        self._flush()

    async def delete(self, session_id: str) -> None:
        self._ensure_loaded()
        self._cache.pop(session_id, None)
        self._flush()

    async def load_all(self) -> list[Session]:
        self._ensure_loaded()
        return list(self._cache.values())

    async def delete_many(self, session_ids: list[str]) -> None:
        self._ensure_loaded()
        for sid in session_ids:
            self._cache.pop(sid, None)
        if session_ids:
            self._flush()


# ---------------------------------------------------------------------------
# db 后端：骨架实现，存储逻辑待补充
# ---------------------------------------------------------------------------

class DbBackend(SessionBackend):
    """
    数据库后端，适合多 Worker 生产部署。

    TODO: 实现具体的数据库存储逻辑。
    建议字段：
        session_id   VARCHAR(64) PRIMARY KEY
        cwd          TEXT
        metadata     TEXT (JSON)
        created_at   DATETIME
        last_active  DATETIME

    可选方案：
    - SQLAlchemy（异步）+ MySQL/PostgreSQL
    - tortoise-orm
    - 直接使用项目已有的数据库连接池
    """

    def __init__(self, dsn: str):
        # TODO: 初始化数据库连接池，dsn 示例：mysql+asyncmy://user:pass@host/db
        self._dsn = dsn
        logger.warning("[DbBackend] 数据库后端尚未实现，session 数据不会被持久化")

    async def load(self, session_id: str) -> Optional[Session]:
        # TODO: SELECT * FROM <session_table> WHERE session_id = ?
        assert session_id is not None
        return None

    async def save(self, session: Session) -> None:
        # TODO: INSERT INTO <session_table> ... ON DUPLICATE KEY UPDATE ...
        assert session is not None

    async def delete(self, session_id: str) -> None:
        # TODO: DELETE FROM <session_table> WHERE session_id = ?
        assert session_id is not None

    async def load_all(self) -> list[Session]:
        # TODO: SELECT * FROM <session_table>（可加 last_active 过滤）
        return []

    async def delete_many(self, session_ids: list[str]) -> None:
        # TODO: DELETE FROM <session_table> WHERE session_id IN (...)
        assert session_ids is not None


# ---------------------------------------------------------------------------
# SessionManager：统一入口，与后端解耦
# ---------------------------------------------------------------------------

class SessionManager:
    """
    会话管理器，内存缓存 + 可插拔存储后端。

    内存缓存保证单进程内的读性能；后端负责跨重启/跨 Worker 的持久化。
    """

    def __init__(self, backend: SessionBackend, ttl_minutes: int = 60):
        self._cache: dict[str, Session] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()
        self._backend = backend

    async def initialize(self) -> None:
        """启动时从后端批量加载已有 session 到内存缓存"""
        sessions = await self._backend.load_all()
        for s in sessions:
            self._cache[s.id] = s
        logger.info(f"[SessionManager] 已从后端加载 {len(sessions)} 个 session")

    async def create_session(self, cwd: Optional[str] = None) -> Session:
        async with self._lock:
            session = Session(id=str(uuid.uuid4()), cwd=cwd)
            self._cache[session.id] = session
        await self._backend.save(session)
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            session = self._cache.get(session_id)
        if session is None:
            # 缓存未命中时回源（db 模式跨 Worker 场景）
            session = await self._backend.load(session_id)
            if session:
                async with self._lock:
                    self._cache[session.id] = session
        if session:
            session.touch()
        return session

    async def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        cwd: Optional[str] = None,
        *,
        default_cwd: Optional[str] = None,
    ) -> Session:
        if session_id:
            session = await self.get_session(session_id)
            if session:
                # 续聊时保持已有 cwd，避免 RAG/普通 Agent 切换时工作目录漂移导致 resume 失效
                if cwd is not None and session.cwd != cwd:
                    session.cwd = cwd
                    await self._backend.save(session)
                elif session.cwd is None and default_cwd is not None:
                    session.cwd = default_cwd
                    await self._backend.save(session)
                return session
            initial_cwd = cwd if cwd is not None else default_cwd
            async with self._lock:
                session = Session(id=session_id, cwd=initial_cwd)
                self._cache[session_id] = session
            await self._backend.save(session)
            return session
        return await self.create_session(cwd=cwd if cwd is not None else default_cwd)

    async def update_session_metadata(self, session_id: str, metadata: dict) -> None:
        """更新 metadata 并同步到后端"""
        async with self._lock:
            session = self._cache.get(session_id)
            if session:
                session.metadata.update(metadata)
        if session:
            await self._backend.save(session)

    async def delete_session(self, session_id: str) -> bool:
        async with self._lock:
            existed = session_id in self._cache
            self._cache.pop(session_id, None)
        if existed:
            await self._backend.delete(session_id)
        return existed

    async def cleanup_expired(self) -> int:
        async with self._lock:
            now = datetime.now()
            expired = [sid for sid, s in self._cache.items() if now - s.last_active > self._ttl]
            for sid in expired:
                del self._cache[sid]
        if expired:
            await self._backend.delete_many(expired)
        return len(expired)

    async def list_sessions(self) -> list[Session]:
        async with self._lock:
            return list(self._cache.values())

    def get_stats(self) -> dict:
        return {
            "total_sessions": len(self._cache),
            "ttl_minutes": self._ttl.total_seconds() / 60,
            "store": type(self._backend).__name__,
        }


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def _build_backend(store: str, file_path: str, db_dsn: str) -> SessionBackend:
    if store == "file":
        return FileBackend(file_path)
    if store == "db":
        return DbBackend(db_dsn)
    return MemoryBackend()


def _create_session_manager() -> SessionManager:
    from ..config import settings
    backend = _build_backend(
        store=settings.session_store,
        file_path=settings.session_file_path,
        db_dsn=settings.session_db_dsn,
    )
    return SessionManager(backend=backend)


# 全局会话管理器实例
session_manager = _create_session_manager()
