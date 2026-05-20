"""
Skills API 路由 - 仅提供 Skills 管理功能

完全遵循 cc-agent-sdk 设计：
- 没有 /skills/{skill_name}/invoke 端点
- Skills 通过 /agent-sdk/stream 自动调用
- 此路由仅用于查询和管理 Skills
"""
from fastapi import APIRouter, HTTPException

from ..models.response import SkillInfo
from ..services.skills import skills_manager

router = APIRouter(prefix="/skills", tags=["Skills"])


@router.get("")
async def list_skills() -> list[SkillInfo]:
    """
    【前端可用 / 管理查询】列出所有可用 Skills。

    适用场景：
    - 前端展示当前项目支持哪些 Skills。
    - 管理端检查 Skills 是否加载成功。

    注意：本接口只查询 Skills 元信息，不执行 Skill。
    Skill 的实际使用由 `/agent-sdk/stream` 或 `/agent-sdk/rag/stream` 中的 Agent 自动判断。
    """
    skills = skills_manager.list_skills()
    return [
        SkillInfo(
            name=skill.name,
            description=skill.description,
            path=str(skill.path),
            enabled=skill.enabled
        )
        for skill in skills
    ]


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> SkillInfo:
    """
    【前端可用 / 管理查询】获取指定 Skill 的元信息。

    返回 Skill 名称、描述、路径、启用状态；不返回完整 SKILL.md 内容。
    """
    skill = skills_manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return SkillInfo(
        name=skill.name,
        description=skill.description,
        path=str(skill.path),
        enabled=skill.enabled
    )


@router.get("/{skill_name}/content")
async def get_skill_content(skill_name: str) -> dict:
    """
    【管理/调试】获取指定 Skill 的 SKILL.md 完整内容。

    适用场景：查看 Skill 触发说明、使用约束和实现文档。
    普通聊天流程不需要调用本接口。
    """
    skill = skills_manager.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return {
        "name": skill.name,
        "content": skill.content
    }


@router.post("")
async def create_skill(name: str, content: str, description: str | None = None) -> SkillInfo:
    """
    【管理接口】创建新的 Skill。

    适用场景：后台管理动态新增 Skill。普通前端聊天流程不应调用。

    - **name**: Skill 名称
    - **content**: SKILL.md 内容
    - **description**: 可选，Skill 描述
    """
    existing = skills_manager.get_skill(name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Skill '{name}' already exists")

    skill = skills_manager.create_skill(
        name=name,
        content=content,
        description=description
    )

    return SkillInfo(
        name=skill.name,
        description=skill.description,
        path=str(skill.path),
        enabled=skill.enabled
    )


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str) -> dict:
    """
    【管理接口】删除指定 Skill。

    注意：破坏性操作，仅建议后台管理使用。删除后 Agent 将无法再自动匹配该 Skill。
    """
    if not skills_manager.delete_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return {"message": f"Skill '{skill_name}' deleted successfully"}
