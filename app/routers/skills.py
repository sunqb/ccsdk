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
    列出所有可用的 Skills
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
    获取指定 Skill 的详细信息
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
    获取 Skill 的 SKILL.md 内容
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
    创建新的 Skill

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
    删除指定的 Skill
    """
    if not skills_manager.delete_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return {"message": f"Skill '{skill_name}' deleted successfully"}
