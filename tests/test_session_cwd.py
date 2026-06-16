from __future__ import annotations

import pytest

from app.services.agent import resolve_agent_cwd


def test_resolve_agent_cwd_prefers_explicit_cwd() -> None:
    assert (
        resolve_agent_cwd(cwd="/custom", space_id="s1", conversation_id="c1")
        == "/custom"
    )


def test_resolve_agent_cwd_uses_session_isolated_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "work_dir", "/data/work")
    monkeypatch.setattr(settings, "session_isolated_workdir", True)
    assert (
        resolve_agent_cwd(cwd=None, space_id=None, conversation_id="conv-1")
        == "/data/work/sessions/conv-1"
    )


@pytest.mark.asyncio
async def test_get_or_create_session_keeps_existing_cwd() -> None:
    from app.services.session import Session, SessionManager, MemoryBackend

    manager = SessionManager(MemoryBackend(), ttl_minutes=60)
    session = Session(id="conv-1", cwd="/data/work/sessions/conv-1")
    manager._cache[session.id] = session

    resolved = await manager.get_or_create_session(
        session_id="conv-1",
        cwd=None,
        default_cwd="/data/work",
    )
    assert resolved.cwd == "/data/work/sessions/conv-1"
