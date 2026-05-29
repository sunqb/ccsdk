"""
配置管理模块
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 加载 .env 文件
from dotenv import load_dotenv

# 优先从项目根目录加载 .env (override=True 强制覆盖已有环境变量)
env_path = Path(__file__).parent.parent / ".env"
loaded = load_dotenv(env_path, override=True)

def _secret_status(value: str | None) -> str:
    if not value:
        return "None"
    return f"set(len={len(value)})"


def _env_bool(name: str, default: str | bool = "") -> bool:
    value = os.getenv(name)
    if value is None:
        value = str(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_work_dir() -> str:
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_json_dict(name: str) -> dict:
    value = os.getenv(name, "").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _default_rag_allowed_extensions() -> list[str]:
    configured = os.getenv("RAG_ALLOWED_EXTENSIONS")
    if configured is not None:
        return _csv_list(configured)

    return [".txt", ".md", ".pdf", ".docx"]


print("="*50)
print(f"[Config] 加载 .env 文件: {env_path}")
print(f"[Config] .env 文件存在: {env_path.exists()}")
print(f"[Config] load_dotenv 返回: {loaded}")
print(f"[Config] ANTHROPIC_API_KEY: {_secret_status(os.getenv('ANTHROPIC_API_KEY'))}")
print(f"[Config] ANTHROPIC_AUTH_TOKEN: {_secret_status(os.getenv('ANTHROPIC_AUTH_TOKEN'))}")
print(f"[Config] ANTHROPIC_BASE_URL: {os.getenv('ANTHROPIC_BASE_URL', 'None')}")
print(f"[Config] ANTHROPIC_MODEL: {os.getenv('ANTHROPIC_MODEL', 'None')}")
print(f"[Config] WORK_DIR: {os.getenv('WORK_DIR', 'None')}")
print("="*50)


@dataclass
class Settings:
    """应用配置"""
    # Anthropic 配置
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
    )
    anthropic_auth_token: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_base_url: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )

    # Agent SDK 配置
    agent_sdk_first_output_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("AGENT_SDK_FIRST_OUTPUT_TIMEOUT_MS", "30000"))
    )
    agent_sdk_api_key: str | None = field(
        default_factory=lambda: os.getenv("AGENT_SDK_API_KEY")
    )
    agent_sdk_port: int = field(
        default_factory=lambda: int(os.getenv("AGENT_SDK_PORT", "8000"))
    )
    # /agent-sdk/stream 最终 result 事件输出模式：
    # - full: 输出完整 result 文本（默认，兼容原行为）
    # - empty: 输出空字符串
    # - none: 不输出 result(success) 事件（仅依赖 SSE 断开或 end 事件判断结束）
    agent_sdk_stream_result_mode: str = field(
        default_factory=lambda: os.getenv("AGENT_SDK_STREAM_RESULT_MODE", "full")
    )
    # /agent-sdk/stream 事件输出模式：
    # - full: 完整事件流（默认，尽量与 claude-agent-sdk/Claude Code CLI 保持一致）
    # - text_only: 仅输出 content_block_delta/text_delta（并保留 end/error）
    agent_sdk_stream_event_mode: str = field(
        default_factory=lambda: os.getenv("AGENT_SDK_STREAM_EVENT_MODE", "full")
    )

    # 通过代码注入 Claude Code CLI settings / MCP（无需写 .claude/settings.json）
    # 说明：
    # - AGENT_SDK_ADDITIONAL_SETTINGS_JSON：JSON 字符串，将作为 `claude --settings <json>` 的"附加 settings"注入
    # - AGENT_SDK_PERMISSIONS_ALLOW：逗号分隔的 allow 规则，自动合并进 additional settings 的 permissions.allow
    # - AGENT_SDK_MCP_SERVERS_JSON：JSON 字符串，形如 {"search": {"type":"sse","url":"..."}}
    # - AGENT_SDK_STRICT_MCP_CONFIG：为 1/true 时，传递 `--strict-mcp-config`
    agent_sdk_additional_settings_json: str | None = field(
        default_factory=lambda: os.getenv(
            "AGENT_SDK_ADDITIONAL_SETTINGS_JSON",
            '{"skipWebFetchPreflight": true}'  # 默认跳过 WebFetch 预检
        )
    )
    agent_sdk_permissions_allow: str | None = field(
        default_factory=lambda: os.getenv("AGENT_SDK_PERMISSIONS_ALLOW")
    )
    agent_sdk_mcp_servers_json: str | None = field(
        default_factory=lambda: os.getenv("AGENT_SDK_MCP_SERVERS_JSON")
    )
    agent_sdk_strict_mcp_config: bool = field(
        default_factory=lambda: _env_bool("AGENT_SDK_STRICT_MCP_CONFIG")
    )

    # 服务配置
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    # Skills 配置（遵循 SDK 规范，放在 .claude/skills）
    skills_dir: str = field(
        default_factory=lambda: os.getenv("SKILLS_DIR", "./.claude/skills")
    )

    # 工作目录
    work_dir: str = field(
        default_factory=lambda: os.getenv("WORK_DIR", _default_work_dir())
    )

    # 全局 MySQL 数据库配置（RAG / WeChatBot / 后续 SaaS 元数据共用）
    # 格式：mysql+asyncmy://user:pass@host:port/dbname
    db_dsn: str = field(default_factory=lambda: os.getenv("DB_DSN", ""))

    # RAG MVP 配置
    rag_enabled: bool = field(
        default_factory=lambda: _env_bool("RAG_ENABLED")
    )
    rag_storage_dir: str = field(
        default_factory=lambda: os.getenv(
            "RAG_STORAGE_DIR",
            os.path.join(os.getenv("WORK_DIR", _default_work_dir()), "rag"),
        )
    )
    rag_temp_file_ttl_hours: int = field(
        default_factory=lambda: int(os.getenv("RAG_TEMP_FILE_TTL_HOURS", "24"))
    )
    rag_vector_provider: str = field(
        default_factory=lambda: os.getenv("RAG_VECTOR_PROVIDER", "local")
    )
    rag_direct_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RAG_DIRECT_TIMEOUT_SECONDS", "120"))
    )
    rag_direct_max_tokens: int = field(
        default_factory=lambda: int(os.getenv("RAG_DIRECT_MAX_TOKENS", "2048"))
    )
    rag_embedding_provider: str = field(
        default_factory=lambda: os.getenv("RAG_EMBEDDING_PROVIDER", "openai_compatible")
    )
    rag_embedding_model: str = field(
        default_factory=lambda: os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    rag_embedding_base_url: str | None = field(
        default_factory=lambda: os.getenv("RAG_EMBEDDING_BASE_URL")
    )
    rag_embedding_api_key: str | None = field(
        default_factory=lambda: os.getenv("RAG_EMBEDDING_API_KEY")
    )
    rag_default_top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_DEFAULT_TOP_K", "8"))
    )
    rag_max_top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_TOP_K", "30"))
    )
    rag_retrieve_top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_RETRIEVE_TOP_K", "100"))
    )
    rag_final_top_k: int = field(
        default_factory=lambda: int(os.getenv("RAG_FINAL_TOP_K", "8"))
    )
    rag_enable_multi_query: bool = field(
        default_factory=lambda: _env_bool("RAG_ENABLE_MULTI_QUERY", "true")
    )
    rag_rerank_provider: str = field(
        default_factory=lambda: os.getenv("RAG_RERANK_PROVIDER", "local_lexical")
    )
    rag_rerank_base_url: str | None = field(
        default_factory=lambda: os.getenv("RAG_RERANK_BASE_URL")
    )
    rag_verification_mode: str = field(
        default_factory=lambda: os.getenv("RAG_VERIFICATION_MODE", "standard").strip().lower()
    )
    rag_min_citation_alignment: float = field(
        default_factory=lambda: float(os.getenv("RAG_MIN_CITATION_ALIGNMENT", "0.6"))
    )
    rag_chunk_size: int = field(
        default_factory=lambda: int(os.getenv("RAG_CHUNK_SIZE", "1000"))
    )
    rag_chunk_overlap: int = field(
        default_factory=lambda: int(os.getenv("RAG_CHUNK_OVERLAP", "120"))
    )
    rag_max_upload_files: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_UPLOAD_FILES", "5"))
    )
    rag_max_upload_size_mb: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_UPLOAD_SIZE_MB", "20"))
    )
    rag_allowed_extensions: list[str] = field(
        default_factory=_default_rag_allowed_extensions
    )
    rag_max_concurrent_ingestions: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_CONCURRENT_INGESTIONS", "4"))
    )
    rag_max_concurrent_queries: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_CONCURRENT_QUERIES", "16"))
    )
    rag_qdrant_url: str | None = field(default_factory=lambda: os.getenv("RAG_QDRANT_URL"))
    rag_qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("RAG_QDRANT_API_KEY"))
    rag_qdrant_collection: str = field(
        default_factory=lambda: os.getenv("RAG_QDRANT_COLLECTION", "rag_chunks")
    )
    rag_qdrant_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RAG_QDRANT_TIMEOUT_SECONDS", "30"))
    )
    rag_qdrant_create_collection: bool = field(
        default_factory=lambda: _env_bool("RAG_QDRANT_CREATE_COLLECTION", "true")
    )
    rag_pgvector_dsn: str | None = field(default_factory=lambda: os.getenv("RAG_PGVECTOR_DSN"))
    rag_milvus_uri: str | None = field(default_factory=lambda: os.getenv("RAG_MILVUS_URI"))

    # RAG 文档解析器配置
    # 提供者：local（默认，本地解析 .txt/.md/.pdf/.docx）/ mineru（调用公司 MinerU 服务解析 .pdf/.docx）
    rag_parser_provider: str = field(
        default_factory=lambda: os.getenv("RAG_PARSER_PROVIDER", "local").strip().lower()
    )
    mineru_base_url: str | None = field(
        default_factory=lambda: os.getenv("MINERU_BASE_URL")
    )
    mineru_api_key: str | None = field(
        default_factory=lambda: os.getenv("MINERU_API_KEY")
    )
    mineru_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("MINERU_TIMEOUT_SECONDS", "120"))
    )
    mineru_fallback_to_local: bool = field(
        default_factory=lambda: _env_bool("MINERU_FALLBACK_TO_LOCAL", "false")
    )

    # 默认允许的工具
    # 说明：为了避免"只想要代码展示"却在服务器上落盘生成文件，默认禁用 Write/Bash。
    # 如需允许写文件，应由上层显式传入 allowed_tools/disallowed_tools 进行放开。
    default_allowed_tools: list[str] = field(
        default_factory=lambda: ["Skill", "Read", "Glob", "Grep", "WebSearch", "WebFetch"]
    )

    # 全局强制禁用的工具（服务端安全模式）
    # 通过环境变量 GLOBAL_DISALLOWED_TOOLS 配置，逗号分隔，如 "Write,Bash"
    # 设为空字符串可全部放开：GLOBAL_DISALLOWED_TOOLS=
    global_disallowed_tools: list[str] = field(
        default_factory=lambda: [
            t.strip() for t in os.getenv("GLOBAL_DISALLOWED_TOOLS", "Write,Bash").split(",")
            if t.strip()
        ]
    )

    # Session 存储模式
    # - memory：纯内存，重启后丢失（默认）
    # - file：持久化到 JSON 文件，重启后自动恢复 conversationId -> resume_id 映射
    session_store: str = field(
        default_factory=lambda: os.getenv("SESSION_STORE", "memory").strip().lower()
    )

    # file 模式下的持久化文件路径
    session_file_path: str = field(
        default_factory=lambda: os.getenv("SESSION_FILE_PATH", "./.claude/sessions.json")
    )

    # db 模式下的数据库连接串（SESSION_STORE=db 时生效）
    # 示例：mysql+asyncmy://user:pass@host:3306/dbname
    session_db_dsn: str = field(
        default_factory=lambda: os.getenv("SESSION_DB_DSN", "")
    )

    # 是否按 conversationId 自动隔离工作目录
    # true：未传 cwd 时自动使用 <WORK_DIR>/sessions/<conversationId>/ 作为工作目录
    # false（默认）：所有会话共享 WORK_DIR
    # 前端也可以直接在请求里传 cwd 覆盖此行为
    session_isolated_workdir: bool = field(
        default_factory=lambda: _env_bool("SESSION_ISOLATED_WORKDIR")
    )

    # WeChat Bot 配置
    wechatbot_enabled: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_ENABLED")
    )
    # 是否随主服务启动自动启动 Bot
    wechatbot_auto_start: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_AUTO_START", "false")
    )
    # 目标 SDK 配置（wechatbot.WeChatBot）
    wechatbot_base_url: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_BASE_URL", "https://ilinkai.weixin.qq.com")
    )
    wechatbot_cred_path: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_CRED_PATH", "~/.wechatbot/credentials.json")
    )
    # WeChat iLink Bot 配置
    wechatbot_ilink_app_id: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_ILINK_APP_ID")
    )
    wechatbot_ilink_app_secret: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_ILINK_APP_SECRET")
    )
    wechatbot_ilink_device_id: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_ILINK_DEVICE_ID")
    )
    # 凭证持久化目录（默认放在非公开目录）
    wechatbot_credentials_dir: str = field(
        default_factory=lambda: os.getenv(
            "WECHATBOT_CREDENTIALS_DIR",
            os.path.join(os.getenv("WORK_DIR", _default_work_dir()), ".wechatbot", "credentials")
        )
    )
    # 消息回复分块大小（微信侧限制）
    wechatbot_reply_chunk_size: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_REPLY_CHUNK_SIZE", "500"))
    )
    # 分块发送间隔，避免触发微信侧限流
    wechatbot_reply_chunk_interval_seconds: float = field(
        default_factory=lambda: float(os.getenv("WECHATBOT_REPLY_CHUNK_INTERVAL_SECONDS", "0.8"))
    )
    # 回复最大总字符数，超过会截断
    wechatbot_max_reply_chars: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_MAX_REPLY_CHARS", "3500"))
    )
    # 全局并发消息处理数
    wechatbot_max_concurrent_messages: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_MAX_CONCURRENT_MESSAGES", "3"))
    )
    # Agent/RAG 单条消息处理超时
    wechatbot_message_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("WECHATBOT_MESSAGE_TIMEOUT_SECONDS", "120"))
    )
    # 默认消息模式：agent / rag
    wechatbot_default_mode: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_MODE", "agent").strip().lower()
    )
    # 微信用户白名单，逗号分隔；为空表示不限制
    wechatbot_allowed_user_ids: list[str] = field(
        default_factory=lambda: _csv_list(os.getenv("WECHATBOT_ALLOWED_USER_IDS", ""))
    )
    # Mode A SaaS：单 Bot 多用户/多租户配置
    wechatbot_default_tenant_id: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_TENANT_ID", "default").strip() or "default"
    )
    wechatbot_bot_instance_id: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_BOT_INSTANCE_ID", "default").strip() or "default"
    )
    wechatbot_require_user_tenant: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_REQUIRE_USER_TENANT", "false")
    )
    # Mode A-2 自动绑定：db / env / composite
    wechatbot_binding_store: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_BINDING_STORE", "composite").strip().lower()
    )
    wechatbot_bind_token_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_BIND_TOKEN_TTL_SECONDS", "600"))
    )
    wechatbot_user_tenant_map: dict = field(
        default_factory=lambda: _env_json_dict("WECHATBOT_USER_TENANT_MAP")
    )
    wechatbot_tenant_rag_scope_map: dict = field(
        default_factory=lambda: _env_json_dict("WECHATBOT_TENANT_RAG_SCOPE_MAP")
    )
    # Agent 模式下的系统提示词
    wechatbot_agent_system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "WECHATBOT_AGENT_SYSTEM_PROMPT",
            "你是一个智能助手，请根据用户的问题给出专业、准确的回答。"
        )
    )
    # 默认 RAG scope（当用户未指定时使用）
    wechatbot_default_rag_scope: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_RAG_SCOPE")
    )
    wechatbot_default_knowledge_base_id: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_KNOWLEDGE_BASE_ID")
    )
    wechatbot_default_knowledge_base_name: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_KNOWLEDGE_BASE_NAME")
    )
    wechatbot_default_file_set_id: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_DEFAULT_FILE_SET_ID")
    )
    # 媒体处理策略：ignore（默认，忽略媒体）/ download（下载但不入库）
    wechatbot_media_policy: str = field(
        default_factory=lambda: os.getenv("WECHATBOT_MEDIA_POLICY", "ignore").strip().lower()
    )
    # 媒体下载大小上限（MB）
    wechatbot_media_max_download_size_mb: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_MEDIA_MAX_DOWNLOAD_SIZE_MB", "20"))
    )
    # 消息队列大小（用于 SSE 回复聚合）
    wechatbot_queue_size: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_QUEUE_SIZE", "100"))
    )
    # 单用户每分钟最大消息数（限流）
    wechatbot_rate_limit_per_user: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_RATE_LIMIT_PER_USER", "20"))
    )
    # 单用户突发最大消息数（burst limit）
    wechatbot_rate_limit_burst: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_RATE_LIMIT_BURST", "5"))
    )
    # 限流窗口大小（秒）
    wechatbot_rate_limit_window: int = field(
        default_factory=lambda: int(os.getenv("WECHATBOT_RATE_LIMIT_WINDOW", "60"))
    )
    # OCR 服务端点（用于 summarize 策略）
    wechatbot_ocr_endpoint: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_OCR_ENDPOINT")
    )
    # ASR 服务端点（用于 summarize 策略）
    wechatbot_asr_endpoint: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_ASR_ENDPOINT")
    )
    # RAG 入库服务端点（用于 ingest 策略）
    wechatbot_rag_ingest_endpoint: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_RAG_INGEST_ENDPOINT")
    )
    # 审计日志启用
    wechatbot_audit_enabled: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_AUDIT_ENABLED", default=False)
    )
    wechatbot_audit_log_content_preview: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_AUDIT_LOG_CONTENT_PREVIEW", default=False)
    )
    # OpenTelemetry 启用
    wechatbot_otel_enabled: bool = field(
        default_factory=lambda: _env_bool("WECHATBOT_OTEL_ENABLED", default=False)
    )
    # OpenTelemetry OTLP 端点
    wechatbot_otel_endpoint: str | None = field(
        default_factory=lambda: os.getenv("WECHATBOT_OTEL_ENDPOINT")
    )


settings = Settings()
