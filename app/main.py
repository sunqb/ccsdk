"""
CC Agent SDK - 基于 Claude Agent SDK 的 API 服务

打开本文件即可看到完整启动流程：
  1. 创建 FastAPI app
  2. lifespan：插件启停 → 加载 Skills → 打印鉴权状态
  3. 挂载路由：核心能力 + 插件
  4. 系统端点：/、/health、/config
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models.response import HealthResponse
from .openapi_auth import APP_DESCRIPTION, OPENAPI_TAGS, customize_openapi
from .plugins import plugin_registry
from .routers import agent_router, skills_router
from .routers.agent_sdk import router as agent_sdk_router
from .services.skills import skills_manager

VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 插件（RAG 等）：DB 初始化、健康检查、资源释放
    await plugin_registry.startup_all(app)

    skills_manager.load_skills()
    print(f"Loaded {len(skills_manager.list_skills())} skills from {settings.skills_dir}")

    if os.getenv("AGENT_SDK_API_KEY"):
        print("API Key authentication enabled")
    else:
        print("Warning: API Key authentication disabled (AGENT_SDK_API_KEY not set)")

    yield

    await plugin_registry.shutdown_all()
    print("Shutting down...")


# ---------------------------------------------------------------------------
# 创建应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CC Agent SDK",
    description=APP_DESCRIPTION,
    version=VERSION,
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

customize_openapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 核心路由
app.include_router(agent_sdk_router)   # 兼容原 cc-agent-sdk API
app.include_router(agent_router)       # 简化版 Agent API
app.include_router(skills_router)      # Skills 管理

# 插件路由（RAG 等，由 plugin_registry 统一挂载）
plugin_registry.mount_routers(app)


# ---------------------------------------------------------------------------
# 系统端点
# ---------------------------------------------------------------------------

@app.get("/", tags=["Root"])
async def root():
    return {
        "name": "CC Agent SDK",
        "version": VERSION,
        "description": "基于 Claude Agent SDK 的 Docker Agent 服务",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    return HealthResponse(status="healthy", version=VERSION)


@app.get("/config", tags=["Config"])
async def get_config():
    return {
        "model": settings.anthropic_model,
        "workDir": settings.work_dir,
        "skillsDir": settings.skills_dir,
        "defaultAllowedTools": settings.default_allowed_tools,
        "firstOutputTimeoutMs": settings.agent_sdk_first_output_timeout_ms,
        "streamResultMode": settings.agent_sdk_stream_result_mode,
        "streamEventMode": settings.agent_sdk_stream_event_mode,
        "plugins": plugin_registry.list_plugin_status(),
    }
