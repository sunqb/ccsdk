"""
WeChat Bot 消息路由模块

负责：
- 命令解析（/help、/chat、/rag、/reset、/status）
- 默认模式选择
- 路由决策
"""
import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RouteMode(str, Enum):
    """消息路由模式"""
    AGENT = "agent"       # 普通 Agent 模式
    RAG = "rag"          # RAG 模式
    HELP = "help"        # 帮助
    RESET = "reset"      # 重置会话
    STATUS = "status"    # 状态查询
    UNSUPPORTED = "unsupported"  # 不支持的消息类型


@dataclass
class RouteDecision:
    """路由决策结果"""
    mode: RouteMode
    message: str           # 解析后的纯消息（去掉命令前缀）
    conversation_id: str    # 用于 Agent/RAG 调用的会话 ID
    rag_scope: dict[str, str | list[str] | None] | None = None  # RAG 范围参数


@dataclass
class ParsedCommand:
    """解析后的命令"""
    command: str | None    # 命令名称（如 "help"、"chat"、"rag"）
    args: str              # 命令参数


def parse_command(text: str) -> ParsedCommand:
    """
    解析微信消息文本，提取命令和参数

    Args:
        text: 原始消息文本

    Returns:
        ParsedCommand: 包含命令名称和参数
    """
    text = text.strip()

    # 没有命令前缀，作为普通消息处理
    if not text.startswith("/"):
        return ParsedCommand(command=None, args=text)

    # 分割命令和参数
    parts = text.split(None, 1)
    command = parts[0].lower()  # 命令统一小写
    args = parts[1] if len(parts) > 1 else ""

    return ParsedCommand(command=command, args=args)


def generate_conversation_id(user_id: str, bot_instance_id: str = "default") -> str:
    """
    生成微信用户的 conversationId

    格式：wechat:{bot_instance_id}:{user_id_hash}

    Args:
        user_id: 微信用户 ID
        bot_instance_id: Bot 实例 ID（用于多账号场景）

    Returns:
        str: 格式化的 conversationId
    """
    # 使用 SHA256 哈希 user_id，保护隐私
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    return f"wechat:{bot_instance_id}:{user_id_hash}"


def route_message(
    text: str,
    user_id: str,
    default_mode: RouteMode = RouteMode.AGENT,
) -> RouteDecision:
    """
    路由微信消息

    Args:
        text: 消息文本
        user_id: 微信用户 ID
        default_mode: 默认模式（当没有命令时使用）

    Returns:
        RouteDecision: 路由决策
    """
    text = text.strip()

    # 生成 conversationId
    conversation_id = generate_conversation_id(user_id)

    # 解析命令
    parsed = parse_command(text)

    # 没有命令，使用默认模式
    if parsed.command is None:
        if default_mode == RouteMode.RAG:
            # RAG 模式需要 scope
            rag_scope = _build_rag_scope()
            return RouteDecision(
                mode=RouteMode.RAG,
                message=parsed.args,
                conversation_id=conversation_id,
                rag_scope=rag_scope,
            )
        else:
            return RouteDecision(
                mode=RouteMode.AGENT,
                message=parsed.args,
                conversation_id=conversation_id,
            )

    # 根据命令路由
    command = parsed.command.lstrip("/")  # 去掉可能的 / 前缀

    if command in ("help", "h", "?"):
        return RouteDecision(
            mode=RouteMode.HELP,
            message="",
            conversation_id=conversation_id,
        )

    elif command in ("chat", "c"):
        # 强制 Agent 模式
        return RouteDecision(
            mode=RouteMode.AGENT,
            message=parsed.args,
            conversation_id=conversation_id,
        )

    elif command in ("rag", "r"):
        # RAG 模式
        rag_scope = _build_rag_scope()
        return RouteDecision(
            mode=RouteMode.RAG,
            message=parsed.args,
            conversation_id=conversation_id,
            rag_scope=rag_scope,
        )

    elif command in ("reset", "reboot"):
        # 重置会话
        return RouteDecision(
            mode=RouteMode.RESET,
            message="",
            conversation_id=conversation_id,
        )

    elif command in ("status", "stat", "s"):
        # 状态查询
        return RouteDecision(
            mode=RouteMode.STATUS,
            message="",
            conversation_id=conversation_id,
        )

    else:
        # 未知命令，作为普通消息处理
        logger.info(f"未知命令: {command}，作为普通消息处理")
        if default_mode == RouteMode.RAG:
            rag_scope = _build_rag_scope()
            return RouteDecision(
                mode=RouteMode.RAG,
                message=text,  # 使用原始文本
                conversation_id=conversation_id,
                rag_scope=rag_scope,
            )
        else:
            return RouteDecision(
                mode=RouteMode.AGENT,
                message=text,
                conversation_id=conversation_id,
            )


def _build_rag_scope() -> dict[str, str | list[str] | None]:
    """
    构建 RAG scope 配置

    优先级：
    1. WECHATBOT_DEFAULT_RAG_SCOPE（JSON 字符串）
    2. 分别配置的 WECHATBOT_DEFAULT_KNOWLEDGE_BASE_ID/NAME 或 FILE_SET_ID

    Returns:
        dict: 包含 scope 信息的字典
    """
    scope: dict[str, str | list[str] | None] = {}

    # 从配置读取默认 RAG scope
    default_scope = settings.wechatbot_default_rag_scope
    if default_scope:
        # 期望是 JSON 字符串
        import json
        try:
            scope = json.loads(default_scope)
        except json.JSONDecodeError:
            logger.warning("WECHATBOT_DEFAULT_RAG_SCOPE 解析失败")

    # 兼容规格中的单独配置项；JSON scope 优先。
    scope.setdefault("knowledgeBaseId", settings.wechatbot_default_knowledge_base_id)
    scope.setdefault("knowledgeBaseName", settings.wechatbot_default_knowledge_base_name)
    scope.setdefault("fileSetId", settings.wechatbot_default_file_set_id)

    return scope


def get_help_text() -> str:
    """
    获取帮助文本

    Returns:
        str: 帮助说明
    """
    return """🤖 CC Agent 微信机器人

支持以下命令：

/help - 显示帮助信息
/chat <问题> - 使用普通 Agent 模式回答
/rag <问题> - 使用知识库问答模式
/reset - 重置当前会话
/status - 查看当前状态

直接发送消息将使用默认模式回答。"""


def get_status_text(
    conversation_id: str,
    default_mode: str,
) -> str:
    """
    获取状态文本

    Args:
        conversation_id: 当前会话 ID
        default_mode: 默认模式

    Returns:
        str: 状态信息
    """
    return f"""📊 当前状态

会话 ID：{conversation_id}
默认模式：{default_mode}

发送 /help 查看支持的全部命令。"""
