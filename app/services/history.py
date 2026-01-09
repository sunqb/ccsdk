"""
历史记录服务
"""
import os
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

from ..config import settings


@dataclass
class HistoryMessage:
    """历史消息"""
    type: str
    role: Optional[str] = None
    content: Any = None
    timestamp: Optional[str] = None
    raw: Optional[dict] = None


class HistoryService:
    """历史记录服务 - 读取 .claude/projects/<project>/<conversationId>.jsonl"""

    def __init__(self):
        self._claude_dir = Path.home() / ".claude"

    def _get_conversation_file(self, conversation_id: str) -> Optional[Path]:
        """获取会话文件路径"""
        projects_dir = self._claude_dir / "projects"

        if not projects_dir.exists():
            return None

        # 搜索所有项目目录
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            conv_file = project_dir / f"{conversation_id}.jsonl"
            if conv_file.exists():
                return conv_file

        return None

    def get_history(
        self,
        conversation_id: str,
        offset: int = 0,
        limit: int = 200,
        include_thinking: bool = False,
        raw: bool = False
    ) -> dict[str, Any]:
        """
        获取会话历史

        Args:
            conversation_id: 会话ID
            offset: 起始位置
            limit: 返回数量
            include_thinking: 是否包含 thinking 块
            raw: 是否返回原始数据

        Returns:
            包含历史消息的字典
        """
        conv_file = self._get_conversation_file(conversation_id)

        if not conv_file:
            return {
                "conversationId": conversation_id,
                "messages": [],
                "total": 0,
                "error": "Conversation not found"
            }

        messages = []
        try:
            with open(conv_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        messages.append(event)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            return {
                "conversationId": conversation_id,
                "messages": [],
                "total": 0,
                "error": str(e)
            }

        total = len(messages)

        # 过滤 thinking 块
        if not include_thinking:
            filtered = []
            for msg in messages:
                if isinstance(msg, dict):
                    msg_type = msg.get("type", "")
                    if "thinking" in msg_type.lower():
                        continue
                    # 过滤 content 中的 thinking 块
                    if "content" in msg and isinstance(msg["content"], list):
                        msg = msg.copy()
                        msg["content"] = [
                            block for block in msg["content"]
                            if not (isinstance(block, dict) and
                                    block.get("type", "").lower() == "thinking")
                        ]
                filtered.append(msg)
            messages = filtered

        # 应用分页
        messages = messages[offset:offset + limit]

        if raw:
            return {
                "conversationId": conversation_id,
                "messages": messages,
                "total": total,
                "offset": offset,
                "limit": limit
            }

        # 转换为简化格式
        simplified = []
        for msg in messages:
            if isinstance(msg, dict):
                simplified.append({
                    "type": msg.get("type"),
                    "role": msg.get("role"),
                    "content": self._extract_text_content(msg.get("content")),
                    "timestamp": msg.get("timestamp")
                })

        return {
            "conversationId": conversation_id,
            "messages": simplified,
            "total": total,
            "offset": offset,
            "limit": limit
        }

    def _extract_text_content(self, content: Any) -> Optional[str]:
        """提取文本内容"""
        if content is None:
            return None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif "text" in block:
                        texts.append(block["text"])
                elif isinstance(block, str):
                    texts.append(block)
            return "\n".join(texts) if texts else None
        return str(content)

    def get_claude_data_dir(self) -> str:
        """获取 Claude 数据目录路径"""
        return str(self._claude_dir)

    def list_projects(self) -> list[str]:
        """列出所有项目目录"""
        projects_dir = self._claude_dir / "projects"
        projects = []

        if not projects_dir.exists():
            return projects

        for project_dir in projects_dir.iterdir():
            if project_dir.is_dir():
                projects.append(project_dir.name)

        return sorted(projects)

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出所有会话"""
        projects_dir = self._claude_dir / "projects"
        conversations = []

        if not projects_dir.exists():
            return conversations

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for conv_file in project_dir.glob("*.jsonl"):
                conv_id = conv_file.stem
                try:
                    stat = conv_file.stat()
                    conversations.append({
                        "conversationId": conv_id,
                        "project": project_dir.name,
                        "filePath": str(conv_file),
                        "size": stat.st_size,
                        "mtimeMs": stat.st_mtime * 1000  # 转换为毫秒
                    })
                except Exception:
                    conversations.append({
                        "conversationId": conv_id,
                        "project": project_dir.name,
                        "filePath": str(conv_file)
                    })

        # 按修改时间排序并限制数量
        conversations = sorted(conversations, key=lambda x: x.get("mtimeMs", 0), reverse=True)
        return conversations[:limit]


# 全局实例
history_service = HistoryService()
