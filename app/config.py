"""
配置管理模块
"""
import os
import sys
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


def _env_bool(name: str, default: str = "") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _default_work_dir() -> str:
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _default_rag_allowed_extensions() -> list[str]:
    configured = os.getenv("RAG_ALLOWED_EXTENSIONS")
    if configured is not None:
        return _csv_list(configured)

    return [".txt", ".md", ".pdf", ".docx"]


print("="*50, file=sys.stderr)
print(f"[Config] 加载 .env 文件: {env_path}", file=sys.stderr)
print(f"[Config] .env 文件存在: {env_path.exists()}", file=sys.stderr)
print(f"[Config] load_dotenv 返回: {loaded}", file=sys.stderr)
print(f"[Config] ANTHROPIC_API_KEY: {_secret_status(os.getenv('ANTHROPIC_API_KEY'))}", file=sys.stderr)
print(f"[Config] ANTHROPIC_AUTH_TOKEN: {_secret_status(os.getenv('ANTHROPIC_AUTH_TOKEN'))}", file=sys.stderr)
print(f"[Config] ANTHROPIC_BASE_URL: {os.getenv('ANTHROPIC_BASE_URL', 'None')}", file=sys.stderr)
print(f"[Config] ANTHROPIC_MODEL: {os.getenv('ANTHROPIC_MODEL', 'None')}", file=sys.stderr)
print(f"[Config] WORK_DIR: {os.getenv('WORK_DIR', 'None')}", file=sys.stderr)
print("="*50, file=sys.stderr)


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

    # 沙箱文件系统模板。Docker 沙箱会把该目录挂载为容器内 /sandbox。
    # true：不启用 Docker 时也可以仅使用目录级 project 隔离。
    virtual_space_enabled: bool = field(
        default_factory=lambda: os.getenv("VIRTUAL_SPACE_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    # 虚拟空间根目录，默认 <WORK_DIR>/virtual_spaces
    virtual_space_dir: str = field(
        default_factory=lambda: os.getenv("VIRTUAL_SPACE_DIR", "")
    )
    # 被复制的应用程序源目录，默认项目根目录
    virtual_space_source_dir: str = field(
        default_factory=lambda: os.getenv("VIRTUAL_SPACE_SOURCE_DIR", "")
    )
    # 需要复制进虚拟空间根目录的应用文件/目录，逗号分隔
    virtual_space_app_paths: list[str] = field(
        default_factory=lambda: [
            item.strip()
            for item in os.getenv(
                "VIRTUAL_SPACE_APP_PATHS",
                "app,pyproject.toml,requirements.txt,README.md",
            ).split(",")
            if item.strip()
        ]
    )
    # 需要从源项目 .claude/ 复制到虚拟空间 .claude/ 的文件，逗号分隔
    virtual_space_claude_files: list[str] = field(
        default_factory=lambda: [
            item.strip()
            for item in os.getenv("VIRTUAL_SPACE_CLAUDE_FILES", "CLAUDE.md,settings.json").split(",")
            if item.strip()
        ]
    )

    # Docker 真实沙箱。开启后 Claude Agent SDK/CLI 在受限容器内运行。
    sandbox_enabled: bool = field(
        default_factory=lambda: os.getenv("SANDBOX_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    sandbox_runtime: str = field(
        default_factory=lambda: os.getenv("SANDBOX_RUNTIME", "docker")
    )
    sandbox_image: str = field(
        default_factory=lambda: os.getenv("SANDBOX_IMAGE", "ccsdk-sandbox:latest")
    )
    sandbox_network: str = field(
        default_factory=lambda: os.getenv("SANDBOX_NETWORK", "bridge")
    )
    sandbox_memory: str = field(
        default_factory=lambda: os.getenv("SANDBOX_MEMORY", "2g")
    )
    sandbox_cpus: str = field(
        default_factory=lambda: os.getenv("SANDBOX_CPUS", "1.0")
    )
    sandbox_pids_limit: int = field(
        default_factory=lambda: int(os.getenv("SANDBOX_PIDS_LIMIT", "256"))
    )
    sandbox_tmpfs_size: str = field(
        default_factory=lambda: os.getenv("SANDBOX_TMPFS_SIZE", "256m")
    )
    sandbox_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "900"))
    )
    sandbox_read_only_rootfs: bool = field(
        default_factory=lambda: os.getenv("SANDBOX_READ_ONLY_ROOTFS", "true").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    sandbox_uid: int = field(
        default_factory=lambda: int((os.getenv("SANDBOX_UID") or str(os.getuid() or 1000)).strip())
    )
    sandbox_gid: int = field(
        default_factory=lambda: int((os.getenv("SANDBOX_GID") or str(os.getgid() or 1000)).strip())
    )
    # 允许从 API 服务环境透传进一次性沙箱容器的业务环境变量名，逗号分隔。
    # 不默认透传全部环境，避免把宿主/API 容器敏感信息暴露给 skill 执行环境。
    sandbox_env_passthrough: list[str] = field(
        default_factory=lambda: [
            item.strip()
            for item in os.getenv("SANDBOX_ENV_PASSTHROUGH", "").split(",")
            if item.strip()
        ]
    )


settings = Settings()
