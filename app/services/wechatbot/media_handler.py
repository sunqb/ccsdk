"""
WeChat Bot 媒体处理模块

负责：
- 处理不同类型的媒体消息（图片、语音、文件、视频）
- 根据配置策略（ignore/summarize/ingest）处理媒体
"""
import asyncio
import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from app.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class MediaPolicy(str, Enum):
    """媒体处理策略"""
    IGNORE = "ignore"      # 忽略媒体，只提示暂不支持
    SUMMARIZE = "summarize"  # 下载媒体并摘要
    INGEST = "ingest"      # 下载文件并进入 RAG 入库流程


@dataclass
class MediaMessage:
    """媒体消息结构"""
    user_id: str
    message_type: str  # text, image, voice, file, video
    text: str | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    raw: dict | None = None


class MediaHandler:
    """
    媒体消息处理器

    根据配置的策略处理不同类型的媒体消息。
    """

    def __init__(self):
        self._policy = self._parse_policy(settings.wechatbot_media_policy)
        self._temp_dir = Path(tempfile.gettempdir()) / "wechatbot_media"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def _parse_policy(self, policy: str) -> MediaPolicy:
        """解析策略配置"""
        policy = policy.strip().lower()
        if policy == "summarize":
            return MediaPolicy.SUMMARIZE
        elif policy == "ingest":
            return MediaPolicy.INGEST
        else:
            return MediaPolicy.IGNORE

    def is_media_message(self, message_type: str) -> bool:
        """判断是否为媒体消息类型"""
        return message_type in ("image", "voice", "file", "video")

    def get_ignore_response(self, message_type: str) -> str:
        """获取忽略策略的回复文本"""
        type_names = {
            "image": "图片",
            "voice": "语音",
            "file": "文件",
            "video": "视频",
        }
        type_name = type_names.get(message_type, "该类型")
        return f"暂不支持处理{type_name}消息。请发送文字问题，我会尽力回答。"

    async def handle_media(
        self,
        media: MediaMessage,
    ) -> str | None:
        """
        处理媒体消息

        Args:
            media: 媒体消息对象

        Returns:
            str | None: 回复文本，如果不回复则返回 None
        """
        if self._policy == MediaPolicy.IGNORE:
            return self.get_ignore_response(media.message_type)

        elif self._policy == MediaPolicy.SUMMARIZE:
            return await self._handle_summarize(media)

        elif self._policy == MediaPolicy.INGEST:
            allowed_user_ids = set(settings.wechatbot_allowed_user_ids)
            if allowed_user_ids and media.user_id not in allowed_user_ids:
                return "当前微信用户未被授权上传文件入库。"
            return await self._handle_ingest(media)

        return self.get_ignore_response(media.message_type)

    async def _download_file(self, url: str, file_name: str) -> Path | None:
        """
        下载文件到临时目录

        Args:
            url: 文件 URL
            file_name: 文件名

        Returns:
            Path | None: 下载后的文件路径
        """
        try:
            if not self._is_safe_download_url(url):
                logger.warning("拒绝下载不安全媒体 URL")
                return None

            # 生成唯一文件名
            ext = Path(file_name).suffix if file_name else ""
            unique_name = f"{hashlib.sha256(f'{file_name}{os.urandom(8)}'.encode()).hexdigest()[:16]}{ext}"
            dest_path = self._temp_dir / unique_name
            max_bytes = settings.wechatbot_media_max_download_size_mb * 1024 * 1024

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        logger.warning("媒体文件超过大小上限: content_length=%s", content_length)
                        return None

                    downloaded = 0
                    with open(dest_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                logger.warning("媒体文件流式下载超过大小上限")
                                return None
                            f.write(chunk)

            logger.info(f"文件已下载: {dest_path}")
            return dest_path

        except Exception as e:
            logger.exception(f"文件下载失败: {e}")
            return None

    def _is_safe_download_url(self, url: str) -> bool:
        """限制媒体下载 URL，降低 SSRF 风险。"""
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                return False

            for addr_info in socket.getaddrinfo(parsed.hostname, None):
                ip = ipaddress.ip_address(addr_info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return False
            return True
        except Exception:
            return False

    async def _call_ocr_service(self, file_path: Path) -> str | None:
        """
        调用 OCR 服务识别图片内容

        Args:
            file_path: 图片文件路径

        Returns:
            str | None: 识别出的文本
        """
        try:
            # TODO: 根据实际 OCR 服务配置
            ocr_endpoint = settings.wechatbot_ocr_endpoint
            if not ocr_endpoint:
                logger.info("OCR 服务未配置，跳过图片识别")
                return None

            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    files = {"image": (file_path.name, f, "image/png")}
                    response = await client.post(ocr_endpoint, files=files)
                    response.raise_for_status()

                    result = response.json()
                    return result.get("text") or result.get("content")

        except Exception as e:
            logger.warning(f"OCR 识别失败: {e}")
            return None

    async def _call_speech_recognition(self, file_path: Path) -> str | None:
        """
        调用语音识别服务

        Args:
            file_path: 音频文件路径

        Returns:
            str | None: 识别出的文本
        """
        try:
            # TODO: 根据实际语音识别服务配置
            asr_endpoint = settings.wechatbot_asr_endpoint
            if not asr_endpoint:
                logger.info("ASR 服务未配置，跳过语音识别")
                return None

            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(file_path, "rb") as f:
                    files = {"audio": (file_path.name, f, "audio/mpeg")}
                    response = await client.post(asr_endpoint, files=files)
                    response.raise_for_status()

                    result = response.json()
                    return result.get("text") or result.get("transcript")

        except Exception as e:
            logger.warning(f"语音识别失败: {e}")
            return None

    async def _call_rag_ingest(self, file_path: Path, user_id: str) -> dict:
        """
        调用 RAG 入库服务

        Args:
            file_path: 文件路径
            user_id: 用户 ID

        Returns:
            dict: 入库结果，包含 success 和 message
        """
        try:
            # 获取 RAG 服务配置
            rag_ingest_endpoint = settings.wechatbot_rag_ingest_endpoint
            if not rag_ingest_endpoint:
                logger.warning("RAG 入库服务未配置")
                return {"success": False, "message": "RAG 入库服务未配置"}

            # 准备文件上传
            file_size = file_path.stat().st_size
            if file_size > 50 * 1024 * 1024:  # 50MB 限制
                return {"success": False, "message": "文件大小超过 50MB 限制"}

            async with httpx.AsyncClient(timeout=300.0) as client:
                with open(file_path, "rb") as f:
                    files = {
                        "file": (file_path.name, f, "application/octet-stream"),
                        "user_id": (None, user_id[:8] + "..."),  # 脱敏
                        "source": (None, "wechatbot"),
                    }
                    response = await client.post(rag_ingest_endpoint, files=files)
                    response.raise_for_status()

                    result = response.json()
                    return {
                        "success": result.get("success", True),
                        "message": result.get("message", "入库完成"),
                        "document_id": result.get("document_id"),
                    }

        except Exception as e:
            logger.exception(f"RAG 入库失败: {e}")
            return {"success": False, "message": f"入库失败: {str(e)[:100]}"}

    async def _handle_summarize(self, media: MediaMessage) -> str:
        """
        处理 summarize 策略

        下载媒体并交给对应解析/识别服务摘要。
        """
        user_id_hash = hashlib.sha256(media.user_id.encode()).hexdigest()[:16]
        logger.info("Summarize 策略: user_hash=%s, type=%s", user_id_hash, media.message_type)

        if not media.file_url:
            return f"收到您的{self._get_type_name(media.message_type)}，但无法获取文件内容。"

        # 下载文件
        file_path = await self._download_file(media.file_url, media.file_name or f"media.{media.message_type}")
        if not file_path:
            return f"收到您的{self._get_type_name(media.message_type)}，但下载失败。"

        try:
            if media.message_type == "image":
                # 调用 OCR 识别图片文字
                text = await self._call_ocr_service(file_path)
                if text:
                    return f"图片内容识别结果：\n{text[:500]}"
                else:
                    return "图片内容未能识别，请换用文字描述您的问题。"

            elif media.message_type == "voice":
                # 调用语音识别
                text = await self._call_speech_recognition(file_path)
                if text:
                    return f"语音转文字结果：\n{text[:500]}"
                else:
                    return "语音内容未能识别，请换用文字发送。"

            else:
                return f"收到您的{self._get_type_name(media.message_type)}，summarize 策略暂不支持此类文件。"

        finally:
            # 清理临时文件
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _handle_ingest(self, media: MediaMessage) -> str:
        """
        处理 ingest 策略

        下载文件并进入 RAG 入库流程。
        """
        if media.message_type != "file":
            return self.get_ignore_response(media.message_type)

        # 检查文件扩展名
        if media.file_name:
            allowed_extensions = getattr(settings, "rag_allowed_extensions", [])
            ext = "." + media.file_name.rsplit(".", 1)[-1].lower() if "." in media.file_name else ""
            if allowed_extensions and ext not in allowed_extensions:
                logger.warning(f"文件扩展名不在允许列表中: {ext}")
                return f"不支持的文件类型「{ext}」。请上传以下格式：{', '.join(allowed_extensions) if allowed_extensions else '常见文档格式'}"

        if not media.file_url:
            return f"收到您的文件「{media.file_name}」，但无法获取文件内容。"

        user_id_hash = hashlib.sha256(media.user_id.encode()).hexdigest()[:16]
        logger.info("Ingest 策略: user_hash=%s, size=%s", user_id_hash, media.file_size)

        # 下载文件
        file_path = await self._download_file(media.file_url, media.file_name or "upload.file")
        if not file_path:
            return f"收到您的文件「{media.file_name}」，但下载失败。"

        try:
            # 调用 RAG 入库
            result = await self._call_rag_ingest(file_path, media.user_id)

            if result.get("success"):
                return f"文件「{media.file_name}」已成功上传到知识库，可以开始使用了。"
            else:
                return f"文件「{media.file_name}」入库失败：{result.get('message', '未知错误')}"

        finally:
            # 清理临时文件
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _get_type_name(self, message_type: str) -> str:
        """获取消息类型的中文名称"""
        names = {
            "image": "图片",
            "voice": "语音",
            "file": "文件",
            "video": "视频",
        }
        return names.get(message_type, "媒体")


# 全局处理器单例
_media_handler: MediaHandler | None = None


def get_media_handler() -> MediaHandler:
    """获取媒体处理器实例"""
    global _media_handler
    if _media_handler is None:
        _media_handler = MediaHandler()
    return _media_handler
