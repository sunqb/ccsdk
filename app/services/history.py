"""
历史记录服务
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


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

    def repair_session(self, session_id: str) -> dict[str, Any]:
        """
        修复损坏的 .jsonl 文件：为末尾未配对的 tool_use 补上假的 tool_result。

        当 Claude 工具调用过程中请求被中断时，.jsonl 会留下
        assistant(tool_use) 而没有对应的 user(tool_result)，
        导致下次 resume 时 API 返回 400。

        修复策略：扫描全文，找出所有有 tool_use 但没有对应 tool_result 的条目，
        在文件末尾追加合法的 tool_result 行，使历史合法。
        原文件内容不删除，仅追加，保留完整历史。

        Returns:
            {"repaired": bool, "patched_count": int, "error": str|None}
        """
        conv_file = self._get_conversation_file(session_id)
        if not conv_file:
            return {"repaired": False, "patched_count": 0, "error": "file not found"}

        try:
            lines = conv_file.read_text(encoding="utf-8").splitlines()

            # 收集所有 tool_use_id 和 已有 tool_result 的 tool_use_id
            tool_use_map: dict[str, dict] = {}   # id -> tool_use block
            tool_use_parent: dict[str, dict] = {}  # id -> 所在的 jsonl 行对象
            responded_ids: set[str] = set()

            for raw in lines:
                raw = raw.strip()
                if not raw:
                    continue
                obj = json.loads(raw)
                msg = obj.get("message", {})
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") == "tool_use":
                        tid = block.get("id", "")
                        if tid:
                            tool_use_map[tid] = block
                            tool_use_parent[tid] = obj
                    elif block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tid:
                            responded_ids.add(tid)

            unpaired = {tid: block for tid, block in tool_use_map.items() if tid not in responded_ids}
            if not unpaired:
                return {"repaired": False, "patched_count": 0, "error": None}

            # 为每个未配对的 tool_use 构造一条 user(tool_result) 行追加到文件
            patch_lines = []
            for tid, tu_block in unpaired.items():
                parent = tool_use_parent[tid]
                patch_obj = {
                    "parentUuid": parent.get("uuid", ""),
                    "isSidechain": False,
                    "type": "user",
                    "uuid": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sessionId": parent.get("sessionId", session_id),
                    "cwd": parent.get("cwd", ""),
                    "version": parent.get("version", ""),
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tid,
                                "content": [{"type": "text", "text": "[interrupted]"}],
                                "is_error": True,
                            }
                        ],
                    },
                }
                patch_lines.append(json.dumps(patch_obj, ensure_ascii=False))

            with conv_file.open("a", encoding="utf-8") as f:
                for line in patch_lines:
                    f.write(line + "\n")

            logger.info(f"[repair_session] {session_id}: patched {len(patch_lines)} tool_use(s): {list(unpaired.keys())}")
            return {"repaired": True, "patched_count": len(patch_lines), "error": None}

        except Exception as e:
            logger.error(f"[repair_session] {session_id}: {e}")
            return {"repaired": False, "patched_count": 0, "error": str(e)}

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
