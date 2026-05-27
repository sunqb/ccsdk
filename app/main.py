"""
CC Agent SDK - 基于 Claude Agent SDK 的 API 服务
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .openapi_auth import APP_DESCRIPTION, OPENAPI_TAGS, customize_openapi
from .routers import agent_router, rag_router, skills_router
from .routers.agent_sdk import router as agent_sdk_router
from .services.skills import skills_manager
from .models.response import HealthResponse

VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化 RAG MySQL 数据库
    if settings.rag_db_dsn:
        try:
            from .database import init_rag_db, is_mysql_available
            from .services.rag import rag_mysql_store, set_mysql_store_for_ingestion
            await init_rag_db()
            if is_mysql_available():
                set_mysql_store_for_ingestion(rag_mysql_store)
                print("[RAG DB] MySQL 持久化已注入 ingestion service")
        except Exception as exc:
            print(f"[RAG DB] MySQL 初始化失败，回退到 SQLite: {exc}")

    # 启动时加载 Skills
    skills_manager.load_skills()
    print(f"Loaded {len(skills_manager.list_skills())} skills from {settings.skills_dir}")

    # 嵌入模型启动偏差检测（Layer 2 反馈回路）
    try:
        from .services.rag import embedding_health_check, get_embedding_profile
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

    # 显示认证状态
    api_key = os.getenv("AGENT_SDK_API_KEY")
    if api_key:
        print("API Key authentication enabled")
    else:
        print("Warning: API Key authentication disabled (AGENT_SDK_API_KEY not set)")

    yield

    # 关闭时清理
    if settings.rag_db_dsn:
        try:
            from .database import close_rag_db
            await close_rag_db()
        except Exception:
            pass
    print("Shutting down...")


app = FastAPI(
    title="CC Agent SDK",
    description=APP_DESCRIPTION,
    version=VERSION,
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

customize_openapi(app)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(agent_sdk_router)  # 兼容原 cc-agent-sdk API
app.include_router(agent_router)       # 简化版 API
app.include_router(rag_router)         # RAG API
app.include_router(skills_router)      # Skills API


@app.get("/", tags=["Root"])
async def root():
    """API 根路径（无需鉴权）"""
    return {
        "name": "CC Agent SDK",
        "version": VERSION,
        "description": "基于 Claude Agent SDK 的 Docker Agent 服务"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """健康检查（无需鉴权）"""
    return HealthResponse(
        status="healthy",
        version=VERSION
    )


@app.get("/config", tags=["Config"])
async def get_config():
    """获取当前配置（不含敏感信息，无需鉴权）"""
    return {
        "model": settings.anthropic_model,
        "workDir": settings.work_dir,
        "skillsDir": settings.skills_dir,
        "defaultAllowedTools": settings.default_allowed_tools,
        "firstOutputTimeoutMs": settings.agent_sdk_first_output_timeout_ms,
        "streamResultMode": settings.agent_sdk_stream_result_mode,
        "streamEventMode": settings.agent_sdk_stream_event_mode,
    }
