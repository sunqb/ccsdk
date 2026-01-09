#!/usr/bin/env python3
"""
调试 SDK 消息结构
"""
import os
import asyncio

os.environ["ANTHROPIC_API_KEY"] = "sk-OXmyvA1RKvpCIMSABio4WkkWJWuKhoIIRqO3QFEtDCQX8ZII"
os.environ["ANTHROPIC_BASE_URL"] = "https://api.dev88.tech"

async def debug_messages():
    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        cwd="/Volumes/samsungssd/code/temp/ccsdk",
        allowed_tools=["Read"],
        setting_sources=[],
        env={
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
            "ANTHROPIC_BASE_URL": os.environ["ANTHROPIC_BASE_URL"],
        },
        model="claude-sonnet-4-5-20250929",
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
