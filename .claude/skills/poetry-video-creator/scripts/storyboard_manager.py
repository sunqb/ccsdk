#!/usr/bin/env python3
"""
古诗词视频分镜管理工具
负责分镜脚本的 CRUD、变更追踪、以及旁白提取。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def get_project_dir(poem_title: str) -> Path:
    """根据诗词标题创建/获取项目目录。"""
    safe_title = poem_title.replace(" ", "_").replace("/", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = f"{safe_title}_{timestamp}"
    base_dir = Path(os.getcwd()) / "poetry_video_projects" / project_name
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def load_storyboard(project_dir: Path) -> dict[str, Any]:
    """加载分镜脚本。"""
    sb_path = project_dir / "storyboard.json"
    if not sb_path.exists():
        return {}
    with open(sb_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_storyboard(project_dir: Path, data: dict[str, Any]) -> Path:
    """保存分镜脚本，自动更新 updated_at。"""
    data["updated_at"] = datetime.now().isoformat()
    if "created_at" not in data or not data["created_at"]:
        data["created_at"] = data["updated_at"]

    sb_path = project_dir / "storyboard.json"
    with open(sb_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return sb_path


def update_storyboard_field(
    project_dir: Path, index: int, field: str, value: str
) -> dict[str, Any]:
    """更新指定分镜的指定字段。"""
    data = load_storyboard(project_dir)
    sb = data.get("storyboard", [])
    for item in sb:
        if item.get("index") == index:
            old = item.get(field, "")
            item[field] = value
            data["storyboard"] = sb
            save_storyboard(project_dir, data)
            return {"success": True, "index": index, "field": field, "old": old, "new": value}
    return {"success": False, "error": f"分镜 index={index} 不存在"}


def add_storyboard_item(project_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    """在分镜末尾新增一个分镜。"""
    data = load_storyboard(project_dir)
    sb = data.get("storyboard", [])
    # 自动分配 index
    max_index = max((i.get("index", -1) for i in sb), default=-1)
    item["index"] = max_index + 1
    sb.append(item)
    # 重新排序
    sb.sort(key=lambda x: x.get("index", 0))
    data["storyboard"] = sb
    save_storyboard(project_dir, data)
    return {"success": True, "added_index": item["index"]}


def remove_storyboard_item(project_dir: Path, index: int) -> dict[str, Any]:
    """删除指定分镜。"""
    data = load_storyboard(project_dir)
    sb = data.get("storyboard", [])
    new_sb = [i for i in sb if i.get("index") != index]
    if len(new_sb) == len(sb):
        return {"success": False, "error": f"分镜 index={index} 不存在"}
    # 重新编号
    for idx, item in enumerate(new_sb):
        item["index"] = idx
    data["storyboard"] = new_sb
    save_storyboard(project_dir, data)
    return {"success": True, "removed_index": index}


def get_storyboard_summary(project_dir: Path) -> str:
    """获取分镜概要，用于对话展示。"""
    data = load_storyboard(project_dir)
    poem = data.get("poem", {})
    sb = data.get("storyboard", [])

    lines = []
    lines.append(f"📜 《{poem.get('title', '未命名')}》")
    lines.append(f"作者：{poem.get('author', '未知')} | 朝代：{poem.get('dynasty', '未知')}")
    lines.append(f"要求：{poem.get('user_requirements', '无')}")
    lines.append(f"共 {len(sb)} 个分镜：")
    lines.append("")

    for item in sb:
        idx = item.get("index", 0)
        module = item.get("module", "")
        subtitle = item.get("subtitle", "")
        narration_preview = item.get("narration", "")[:40] + "..."
        lines.append(f"  [{idx}] {module}")
        if subtitle:
            lines.append(f"      字幕：{subtitle}")
        lines.append(f"      旁白：{narration_preview}")
        lines.append("")

    return "\n".join(lines)


def extract_narration(project_dir: Path) -> Path:
    """从分镜中提取完整旁白稿，保存为 narration.md。"""
    data = load_storyboard(project_dir)
    poem = data.get("poem", {})
    sb = data.get("storyboard", [])

    lines = []
    lines.append(f"# 《{poem.get('title', '未命名')}》旁白口播稿")
    lines.append("")
    lines.append(f"> 作者：{poem.get('author', '未知')} | 朝代：{poem.get('dynasty', '未知')}")
    lines.append("")

    for item in sb:
        module = item.get("module", "")
        narration = item.get("narration", "")
        lines.append(f"## {module}")
        lines.append("")
        lines.append(narration)
        lines.append("")

    # 同时提取完整连续文本
    full_text = "\n".join(item.get("narration", "") for item in sb)
    lines.append("---")
    lines.append("")
    lines.append("# 完整口播稿")
    lines.append("")
    lines.append(full_text)

    narration_path = project_dir / "narration.md"
    with open(narration_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return narration_path


def save_character(project_dir: Path, content: str) -> Path:
    """保存主体形象描述。"""
    char_path = project_dir / "character.md"
    with open(char_path, "w", encoding="utf-8") as f:
        f.write(content)
    return char_path


def load_character(project_dir: Path) -> str:
    """加载主体形象描述。"""
    char_path = project_dir / "character.md"
    if not char_path.exists():
        return ""
    with open(char_path, "r", encoding="utf-8") as f:
        return f.read()


# CLI 入口
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python storyboard_manager.py <command> [args...]")
        print("Commands: init, summary, update, add, remove, narration, character")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        title = sys.argv[2] if len(sys.argv) > 2 else "未命名"
        project_dir = get_project_dir(title)
        print(f"PROJECT_DIR={project_dir}")

    elif cmd == "summary":
        project_dir = Path(sys.argv[2])
        print(get_storyboard_summary(project_dir))

    elif cmd == "narration":
        project_dir = Path(sys.argv[2])
        path = extract_narration(project_dir)
        print(f"NARRATION_PATH={path}")

    elif cmd == "character":
        project_dir = Path(sys.argv[2])
        if len(sys.argv) > 3 and sys.argv[3] == "--save":
            content = sys.stdin.read()
            path = save_character(project_dir, content)
            print(f"CHARACTER_PATH={path}")
        else:
            print(load_character(project_dir))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
