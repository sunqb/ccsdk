"""RAG 插件：包装现有 app/services/rag，不改动其内部实现。"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from ..config import settings
from .base import AgentPlugin, CleanupTask


class RagPlugin(AgentPlugin):
    name = "rag"

    def is_enabled(self) -> bool:
        return settings.rag_enabled

    async def on_startup(self, app: FastAPI) -> None:
        if settings.rag_db_dsn:
            try:
                from ..database import init_rag_db, is_mysql_available
                from ..services.rag import rag_mysql_store, set_mysql_store_for_ingestion

                await init_rag_db()
                if is_mysql_available():
                    set_mysql_store_for_ingestion(rag_mysql_store)
                    print("[RAG DB] MySQL 持久化已注入 ingestion service")
            except Exception as exc:
                print(f"[RAG DB] MySQL 初始化失败，回退到 SQLite: {exc}")

        try:
            from ..services.rag import embedding_health_check

            profile = await embedding_health_check()
            print(
                f"[RAG Embedding] provider={profile.provider}, "
                f"model={profile.model}, dimension={profile.dimension}"
            )
        except RuntimeError as exc:
            print(f"[RAG Embedding WARNING] Health check failed: {exc}")
            print("[RAG Embedding] Service will start but RAG features may not work correctly.")
        except Exception as exc:
            print(f"[RAG Embedding WARNING] Unexpected error during health check: {exc}")

    async def on_shutdown(self) -> None:
        if settings.rag_db_dsn:
            try:
                from ..database import close_rag_db

                await close_rag_db()
            except Exception:
                pass

    def get_routers(self) -> list[APIRouter]:
        from ..routers.rag import router as rag_router

        return [rag_router]

    def cleanup_tasks(self) -> list[CleanupTask]:
        from ..services.rag import rag_ingestion_service

        return [
            CleanupTask(
                name="rag_expired_file_sets",
                run=rag_ingestion_service.cleanup_expired_file_sets,
            ),
        ]
