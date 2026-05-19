"""
用户虚拟化空间管理。
"""
import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_IGNORE_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}


@dataclass(frozen=True)
class VirtualSpace:
    """单个用户空间及其中一个会话的虚拟化路径。"""

    id: str
    session_id: str
    root: Path
    workspace: Path
    skills_dir: Path
    home_dir: Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _as_bool(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_id(raw: str) -> str:
    value = (raw or "").strip() or "session"
    safe = _SAFE_ID_RE.sub("_", value).strip("._-") or "session"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{safe[:96]}-{digest}"


def _resolve_from_source(path_value: str, source_root: Path) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return source_root / path


def _copy_path(source: Path, dest: Path) -> None:
    if not source.exists():
        logger.warning("[VirtualSpace] source path not found: %s", source)
        return

    if source.is_dir():
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.copytree(
            source,
            dest,
            ignore=shutil.ignore_patterns(*_IGNORE_NAMES, "*.pyc", "*.pyo"),
        )
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.is_dir():
        shutil.rmtree(dest)
    shutil.copy2(source, dest)


def _apply_sandbox_owner(root: Path) -> None:
    if not _as_bool(settings.sandbox_enabled):
        return

    uid = settings.sandbox_uid
    gid = settings.sandbox_gid

    try:
        for current_root, dirs, files in os.walk(root):
            current_path = Path(current_root)
            os.chown(current_path, uid, gid)
            current_path.chmod(0o755)
            for name in dirs:
                path = current_path / name
                os.chown(path, uid, gid)
                path.chmod(0o755)
            for name in files:
                path = current_path / name
                os.chown(path, uid, gid)
                path.chmod(0o644)
        workspace = root / "workspace"
        workspace.chmod(0o775)
    except PermissionError as exc:
        logger.warning("[VirtualSpace] cannot chown virtual space %s: %s", root, exc)


class VirtualSpaceManager:
    """为每个会话准备独立 Claude project。"""

    @property
    def enabled(self) -> bool:
        return _as_bool(settings.virtual_space_enabled)

    def prepare(self, space_id: str, session_id: str | None = None) -> VirtualSpace:
        source_root = (
            Path(settings.virtual_space_source_dir or _project_root())
            .expanduser()
            .resolve()
        )
        base_dir = Path(settings.virtual_space_dir or Path(settings.work_dir) / "virtual_spaces")
        base_dir = base_dir.expanduser().resolve()
        base_dir.mkdir(parents=True, exist_ok=True)

        safe_id = _safe_id(space_id)
        safe_session_id = _safe_id(session_id or space_id)
        root = (base_dir / safe_id).resolve()
        if not root.is_relative_to(base_dir):
            raise ValueError("Invalid virtual space path")

        workspace = root / "workspace"
        sessions_dir = root / "sessions"
        home_dir = sessions_dir / safe_session_id / ".home"
        claude_dir = root / ".claude"
        skills_dir = claude_dir / "skills"
        workspace.mkdir(parents=True, exist_ok=True)
        sessions_dir.mkdir(parents=True, exist_ok=True)
        home_dir.mkdir(parents=True, exist_ok=True)
        (home_dir / ".claude").mkdir(parents=True, exist_ok=True)
        claude_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)

        for rel_path in settings.virtual_space_app_paths:
            rel = Path(rel_path)
            if rel_path == "." or rel.is_absolute() or ".." in rel.parts:
                logger.warning("[VirtualSpace] skip unsafe app path: %s", rel_path)
                continue
            source = _resolve_from_source(rel_path, source_root)
            dest = root / rel_path
            _copy_path(source, dest)

        source_skills_dir = _resolve_from_source(settings.skills_dir, source_root)
        _copy_path(source_skills_dir, skills_dir)

        source_claude_dir = source_root / ".claude"
        for name in settings.virtual_space_claude_files:
            if Path(name).is_absolute() or ".." in Path(name).parts:
                logger.warning("[VirtualSpace] skip unsafe .claude file: %s", name)
                continue
            source = source_claude_dir / name
            if source.exists() and source.is_file():
                _copy_path(source, claude_dir / name)

        _apply_sandbox_owner(root)

        return VirtualSpace(
            id=safe_id,
            session_id=safe_session_id,
            root=root,
            workspace=workspace,
            skills_dir=skills_dir,
            home_dir=home_dir,
        )


virtual_space_manager = VirtualSpaceManager()
