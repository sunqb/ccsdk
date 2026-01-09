"""
Skills 管理服务
"""
import os
import re
import yaml
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from ..config import settings


@dataclass
class SkillDefinition:
    """Skill 定义"""
    name: str
    path: Path
    description: Optional[str] = None
    content: Optional[str] = None
    enabled: bool = True


class SkillsManager:
    """Skills 管理器"""

    def __init__(self, skills_dir: Optional[str] = None):
        self._skills_dir = Path(skills_dir or settings.skills_dir)
        self._skills: dict[str, SkillDefinition] = {}
        self._loaded = False

    def _parse_skill_description(self, content: str) -> Optional[str]:
        """从 SKILL.md 内容中解析描述，支持 YAML frontmatter"""
        # 检查是否有 YAML frontmatter
        if content.strip().startswith("---"):
            # 尝试解析 YAML frontmatter
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    if isinstance(frontmatter, dict) and "description" in frontmatter:
                        return frontmatter["description"]
                except Exception:
                    pass

        # 回退到原有逻辑：查找第一行非空非注释内容
        lines = content.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and line != "---":
                return line[:200]
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1)
        return None

    def load_skills(self) -> dict[str, SkillDefinition]:
        """加载所有 Skills"""
        self._skills.clear()

        if not self._skills_dir.exists():
            self._skills_dir.mkdir(parents=True, exist_ok=True)
            self._loaded = True
            return self._skills

        for skill_path in self._skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_md = skill_path / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
                description = self._parse_skill_description(content)

                skill = SkillDefinition(
                    name=skill_path.name,
                    path=skill_path,
                    description=description,
                    content=content,
                    enabled=True
                )
                self._skills[skill.name] = skill
            except Exception as e:
                print(f"Failed to load skill {skill_path.name}: {e}")

        self._loaded = True
        return self._skills

    def get_skill(self, name: str, reload: bool = False) -> Optional[SkillDefinition]:
        """获取指定 Skill"""
        if reload or not self._loaded:
            self.load_skills()
        return self._skills.get(name)

    def list_skills(self, reload: bool = True) -> list[SkillDefinition]:
        """列出所有 Skills，默认每次重新加载"""
        if reload or not self._loaded:
            self.load_skills()
        return list(self._skills.values())

    def get_skills_dir(self) -> Path:
        """获取 Skills 目录"""
        return self._skills_dir

    def create_skill(
        self,
        name: str,
        content: str,
        description: Optional[str] = None
    ) -> SkillDefinition:
        """创建新 Skill"""
        skill_path = self._skills_dir / name
        skill_path.mkdir(parents=True, exist_ok=True)

        skill_md = skill_path / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")

        skill = SkillDefinition(
            name=name,
            path=skill_path,
            description=description or self._parse_skill_description(content),
            content=content,
            enabled=True
        )
        self._skills[name] = skill
        return skill

    def delete_skill(self, name: str) -> bool:
        """删除 Skill"""
        skill = self._skills.get(name)
        if not skill:
            return False

        import shutil
        try:
            shutil.rmtree(skill.path)
            del self._skills[name]
            return True
        except Exception:
            return False


# 全局 Skills 管理器实例
skills_manager = SkillsManager()
