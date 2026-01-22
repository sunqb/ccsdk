"""
配置管理模块
"""
import os
from dataclasses import dataclass, field
from typing import Optional
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
    anthropic_base_url: Optional[str] = field(
        default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )

    # Agent SDK 配置
    agent_sdk_first_output_timeout_ms: int = field(
        default_factory=lambda: int(os.getenv("AGENT_SDK_FIRST_OUTPUT_TIMEOUT_MS", "30000"))
    )
    agent_sdk_api_key: Optional[str] = field(
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
    # - AGENT_SDK_ADDITIONAL_SETTINGS_JSON：JSON 字符串，将作为 `claude --settings <json>` 的“附加 settings”注入
    # - AGENT_SDK_PERMISSIONS_ALLOW：逗号分隔的 allow 规则，自动合并进 additional settings 的 permissions.allow
    # - AGENT_SDK_MCP_SERVERS_JSON：JSON 字符串，形如 {"search": {"type":"sse","url":"..."}}
    # - AGENT_SDK_STRICT_MCP_CONFIG：为 1/true 时，传递 `--strict-mcp-config`
    agent_sdk_additional_settings_json: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENT_SDK_ADDITIONAL_SETTINGS_JSON")
    )
    agent_sdk_permissions_allow: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENT_SDK_PERMISSIONS_ALLOW")
    )
    agent_sdk_mcp_servers_json: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENT_SDK_MCP_SERVERS_JSON")
    )
    agent_sdk_strict_mcp_config: bool = field(
        default_factory=lambda: os.getenv("AGENT_SDK_STRICT_MCP_CONFIG", "").strip().lower()
        in {"1", "true", "yes", "on"}
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
        default_factory=lambda: os.getenv("WORK_DIR", os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
    )

    # 默认允许的工具
    # 说明：为了避免“只想要代码展示”却在服务器上落盘生成文件，默认禁用 Write/Bash。
    # 如需允许写文件，应由上层显式传入 allowed_tools/disallowed_tools 进行放开。
    default_allowed_tools: list[str] = field(
        default_factory=lambda: ["Skill", "Read", "Glob", "Grep"]
    )


settings = Settings()
