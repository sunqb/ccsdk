"""OpenAPI / Swagger 鉴权说明与 security scheme 定制。"""

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

API_KEY_SCHEME_NAME = "ApiKeyAuth"

API_KEY_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": "X-API-Key",
    "description": (
        "服务 API Key。\n\n"
        "- **服务端已配置** `AGENT_SDK_API_KEY`：本组接口必须携带有效 `X-API-Key`，否则 401/403。\n"
        "- **服务端未配置**：可不传，鉴权逻辑自动跳过。\n\n"
        "前端联调可在 Swagger 右上角 **Authorize** 填入密钥。"
    ),
}

OPENAPI_TAGS = [
    {
        "name": "Agent SDK",
        "description": (
            "**鉴权：需要（条件启用）**\n\n"
            "本组为正式前端推荐入口。配置 `AGENT_SDK_API_KEY` 后，所有接口需在请求头携带 `X-API-Key`。"
        ),
    },
    {
        "name": "RAG",
        "description": (
            "**鉴权：需要（条件启用）**\n\n"
            "文档上传、知识库、RAG 问答与运维接口。鉴权规则同 Agent SDK。"
        ),
    },
    {
        "name": "Agent",
        "description": (
            "**鉴权：不需要**\n\n"
            "Legacy / 开发测试入口，无 `X-API-Key` 校验。新业务请使用 Agent SDK。"
        ),
    },
    {
        "name": "Skills",
        "description": (
            "**鉴权：不需要**\n\n"
            "Skills 查询与管理，无 `X-API-Key` 校验。"
        ),
    },
    {
        "name": "Health",
        "description": "**鉴权：不需要** — 健康检查。",
    },
    {
        "name": "Config",
        "description": "**鉴权：不需要** — 公开配置（不含密钥）。",
    },
    {
        "name": "Root",
        "description": "**鉴权：不需要** — 服务元信息。",
    },
]

APP_DESCRIPTION = """基于 Claude Agent SDK 的 Agent 服务，支持 Skills 与 RAG 知识库问答。

## 鉴权说明

| 路径前缀 | 鉴权 | 说明 |
|----------|------|------|
| `/agent-sdk/*` | **需要**（条件启用） | 正式前端入口 |
| `/rag/*` | **需要**（条件启用） | 文档、知识库、RAG 问答 |
| `/agent/*` | **不需要** | Legacy 调试 |
| `/skills/*` | **不需要** | Skills 管理 |
| `/`、`/health`、`/config` | **不需要** | 公开 |

**条件启用**：仅当服务端环境变量 `AGENT_SDK_API_KEY` 非空时，才校验请求头 `X-API-Key`；未配置时所有接口均可直接调用。

在 Swagger 中，需鉴权接口会显示 **锁图标**；可在右上角 **Authorize** 填入 API Key 后调试。
"""

_AUTH_NOTE_REQUIRED = (
    "\n\n---\n"
    "**鉴权**：需要（条件启用）。请求头 `X-API-Key` 须与服务端 `AGENT_SDK_API_KEY` 一致；"
    "服务端未配置该变量时不校验。"
)

_AUTH_NOTE_NONE = "\n\n---\n**鉴权**：不需要。"

_PROTECTED_PREFIXES = ("/agent-sdk", "/rag")
_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
)


def _is_protected_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _PROTECTED_PREFIXES)


def _append_auth_note(operation: dict, *, protected: bool) -> None:
    suffix = _AUTH_NOTE_REQUIRED if protected else _AUTH_NOTE_NONE
    description = operation.get("description") or ""
    if suffix.strip() not in description:
        operation["description"] = f"{description}{suffix}".strip()


def customize_openapi(app: FastAPI) -> None:
    """注册自定义 OpenAPI 生成器，标注鉴权与 security scheme。"""

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )

        components = schema.setdefault("components", {})
        components.setdefault("securitySchemes", {})[API_KEY_SCHEME_NAME] = API_KEY_SCHEME

        for path, path_item in schema.get("paths", {}).items():
            protected = _is_protected_path(path)
            for method, operation in path_item.items():
                if method not in _HTTP_METHODS or not isinstance(operation, dict):
                    continue
                if protected:
                    operation["security"] = [{API_KEY_SCHEME_NAME: []}]
                else:
                    operation["security"] = []
                _append_auth_note(operation, protected=protected)

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi
