#!/usr/bin/env python3
"""
测试 Skill 调用
"""
import asyncio
import sys
sys.path.insert(0, '/Volumes/samsungssd/code/temp/ccsdk')

async def test_skill_invoke():
    from app.config import settings
    from app.services.agent import agent_service
    from app.services.skills import skills_manager

    print("\n" + "=" * 60)
    print("测试 Skill 调用")
    print("=" * 60)

    # 检查 skill 是否存在
    skill = skills_manager.get_skill("Topic_Planning")
    if not skill:
        print("[ERROR] Skill 'Topic_Planning' 不存在!")
        return

    print(f"\n[INFO] Skill 已加载:")
    print(f"  name: {skill.name}")
    print(f"  path: {skill.path}")
    print(f"  content 长度: {len(skill.content)} 字符")
    print(f"  content 前200字符: {skill.content[:200]}...")

    # 构建 system_prompt（与 skills.py 保持一致）
    system_prompt = f"""

=== 自定义技能定义 ===
你已被配置为执行名为 "{skill.name}" 的自定义技能。以下是该技能的完整定义：

{skill.content}

=== 执行说明 ===
1. 仔细阅读上述技能定义
2. 如果技能包含多个子流程或入口（如 topic-planning, topic-research 等），请自动从主入口开始执行
3. 直接开始执行技能任务，不要询问用户想做什么
4. 按照技能定义中的工作流程逐步完成任务
5. 不要尝试调用任何名为 "Skill" 的工具"""

    # 使用新的 prompt 格式
    prompt = f"用户任务：《长安的荔枝》选题\n\n请立即按照技能定义中的工作流程，开始执行此任务。如果是选题策划类任务，请从 topic-planning 主入口开始。"

    print(f"\n[INFO] 调用参数:")
    print(f"  prompt: {prompt}")
    print(f"  system_prompt 长度: {len(system_prompt)} 字符")

    print("\n[INFO] 开始调用 agent_service.query_stream...")
    print("-" * 60)

    async for event in agent_service.query_stream(
        prompt=prompt,
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        system_prompt=system_prompt
    ):
        print(f"事件: type={event.type}, subtype={event.subtype}")
        if event.type == "content_block_delta" and event.subtype == "text_delta":
            text = event.data.get("text", "")
            print(text, end="", flush=True)
        elif event.type == "error":
            print(f"\n[ERROR] {event.data}")
            break
        elif event.type == "result":
            print(f"\n[RESULT] subtype={event.subtype}")
            if event.subtype == "success":
                print(f"  成功!")
            break

    print("\n" + "-" * 60)
    print("测试完成")

if __name__ == "__main__":
    asyncio.run(test_skill_invoke())
