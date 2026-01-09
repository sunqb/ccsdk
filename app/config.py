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

print("="*50)
print(f"[Config] 加载 .env 文件: {env_path}")
print(f"[Config] .env 文件存在: {env_path.exists()}")
print(f"[Config] load_dotenv 返回: {loaded}")
print(f"[Config] ANTHROPIC_API_KEY: {os.getenv('ANTHROPIC_API_KEY', 'None')[:20] if os.getenv('ANTHROPIC_API_KEY') else 'None'}...")
print(f"[Config] ANTHROPIC_AUTH_TOKEN: {os.getenv('ANTHROPIC_AUTH_TOKEN', 'None')[:20] if os.getenv('ANTHROPIC_AUTH_TOKEN') else 'None'}...")
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
    default_allowed_tools: list[str] = field(
        default_factory=lambda: ["Skill", "Read", "Write", "Bash", "Glob", "Grep"]
    )


settings = Settings()
