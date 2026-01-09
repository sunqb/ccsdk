#!/usr/bin/env python3
"""
端到端测试 - 模拟 API 调用
"""
import asyncio
import sys
sys.path.insert(0, '/Volumes/samsungssd/code/temp/ccsdk')

async def test_agent_service():
    # 先加载配置（这会触发 load_dotenv）
    from app.config import settings
    from app.services.agent import agent_service

    print("\n" + "=" * 60)
    print("测试 Agent Service")
    print(f"  anthropic_auth_token: {settings.anthropic_auth_token[:20] if settings.anthropic_auth_token else 'None'}...")
    print(f"  anthropic_base_url: {settings.anthropic_base_url}")
    print("=" * 60)

    print("\n调用 agent_service.query_stream...")

    async for event in agent_service.query_stream(
        prompt="Say hi",
        allowed_tools=["Read"]
    ):
        print(f"  事件类型: {event.type}, 子类型: {event.subtype}")
        if event.data:
            data_str = str(event.data)
            print(f"  数据: {data_str[:200]}...")
        if event.type == "error":
            print(f"  [ERROR] {event.data}")
            break
        if event.type == "result":
            print(f"  [RESULT] 完成")
            break

if __name__ == "__main__":
    asyncio.run(test_agent_service())
