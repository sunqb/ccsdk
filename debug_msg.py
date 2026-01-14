#!/usr/bin/env python3
"""
调试 SDK 消息结构
"""
import os
import asyncio

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

if not ANTHROPIC_API_KEY:
    raise SystemExit("缺少 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN")

async def debug_messages():
    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        cwd="/Volumes/samsungssd/code/temp/ccsdk",
        allowed_tools=["Read"],
        setting_sources=[],
        env={
            "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
            **({"ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL} if ANTHROPIC_BASE_URL else {}),
        },
        model=ANTHROPIC_MODEL,
        include_partial_messages=True,
    )

    print("开始调试消息结构...")
    async for message in query(prompt="Say hi", options=options):
        print(f"\n消息类型: {type(message).__name__}")
        print(f"  dir: {[a for a in dir(message) if not a.startswith('_')]}")

        # 检查常见属性
        for attr in ['type', 'subtype', 'content', 'data', 'result', 'text']:
            if hasattr(message, attr):
                val = getattr(message, attr)
                print(f"  {attr}: {str(val)[:100]}...")

if __name__ == "__main__":
    asyncio.run(debug_messages())
