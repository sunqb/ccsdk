#!/usr/bin/env python3
"""
测试 Claude Agent SDK 的 API 配置
"""
import os
import asyncio

# 先设置环境变量
os.environ["ANTHROPIC_API_KEY"] = "sk-OXmyvA1RKvpCIMSABio4WkkWJWuKhoIIRqO3QFEtDCQX8ZII"
os.environ["ANTHROPIC_BASE_URL"] = "https://api.dev88.tech"

print("=" * 60)
print("环境变量配置:")
print(f"  ANTHROPIC_API_KEY: {os.environ.get('ANTHROPIC_API_KEY', 'None')[:20]}...")
print(f"  ANTHROPIC_BASE_URL: {os.environ.get('ANTHROPIC_BASE_URL', 'None')}")
print("=" * 60)

async def test_sdk():
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions

        print("\nClaude Agent SDK 导入成功")

        # 构建选项，同时传递 env
        options = ClaudeAgentOptions(
            cwd="/Volumes/samsungssd/code/temp/ccsdk",
            allowed_tools=["Read"],
            env={
                "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
                "ANTHROPIC_BASE_URL": os.environ["ANTHROPIC_BASE_URL"],
            },
            model="claude-sonnet-4-5-20250929",
        )

        print(f"\n选项配置:")
        print(f"  model: {options.model}")
        print(f"  cwd: {options.cwd}")
        print(f"  env keys: {list(options.env.keys())}")

        print("\n开始调用 query...")

        async for message in query(prompt="Say hi", options=options):
            msg_type = getattr(message, "type", None)
            print(f"  收到消息类型: {msg_type}")

            if hasattr(message, "content"):
                print(f"  内容: {message.content[:200] if message.content else 'None'}...")

            if hasattr(message, "data"):
                print(f"  数据: {str(message.data)[:200]}...")

    except Exception as e:
        print(f"\n错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sdk())
