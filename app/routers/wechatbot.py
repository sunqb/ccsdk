"""
WeChat Bot 路由模块

提供以下 API：
- GET  /wechatbot/status  - 获取 Bot 状态
- POST /wechatbot/start   - 启动 Bot（发起登录）
- POST /wechatbot/stop    - 停止 Bot
- POST /wechatbot/relogin - 重新登录
- GET  /wechatbot/qrcode  - 获取当前二维码
"""
import logging
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.config import settings
from app.services.wechatbot.manager import get_wechatbot_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechatbot", tags=["WeChat Bot"])


class ReloginRequest(BaseModel):
    """重新登录请求。"""

    force: bool = False


class SendMessageRequest(BaseModel):
    """运维测试发送消息请求。"""

    user_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


@router.get("/status", dependencies=[Depends(verify_api_key)])
async def get_status():
    """
    获取 WeChat Bot 状态

    Returns:
        dict: 包含 enabled, status, qrcode_url 等信息
    """
    if not settings.wechatbot_enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "message": "WeChatBot 功能已禁用",
        }

    manager = get_wechatbot_manager()
    return await manager.get_status()


@router.post("/start", dependencies=[Depends(verify_api_key)])
async def start_bot():
    """
    启动 WeChat Bot（发起登录流程）

    Returns:
        dict: 包含 status, qrcode_url 等信息
    """
    if not settings.wechatbot_enabled:
        raise HTTPException(
            status_code=400,
            detail="WeChatBot 功能已禁用（WECHATBOT_ENABLED=false）"
        )

    manager = get_wechatbot_manager()
    result = await manager.start()

    return result


@router.post("/stop", dependencies=[Depends(verify_api_key)])
async def stop_bot():
    """
    停止 WeChat Bot

    Returns:
        dict: 停止操作结果
    """
    if not settings.wechatbot_enabled:
        raise HTTPException(
            status_code=400,
            detail="WeChatBot 功能已禁用"
        )

    manager = get_wechatbot_manager()
    result = await manager.stop()

    return result


@router.post("/relogin", dependencies=[Depends(verify_api_key)])
async def relogin_bot(request: ReloginRequest | None = None):
    """
    重新发起登录（无需重启 Bot）

    Returns:
        dict: 包含 qrcode_url 等信息
    """
    if not settings.wechatbot_enabled:
        raise HTTPException(
            status_code=400,
            detail="WeChatBot 功能已禁用"
        )

    manager = get_wechatbot_manager()
    result = await manager.relogin(force=request.force if request else False)

    return result


@router.get("/qrcode", dependencies=[Depends(verify_api_key)])
async def get_qrcode():
    """
    获取当前登录二维码（仅在等待扫码时有效）

    Returns:
        dict: 包含 qrcode_url 等信息
    """
    if not settings.wechatbot_enabled:
        raise HTTPException(
            status_code=400,
            detail="WeChatBot 功能已禁用"
        )

    manager = get_wechatbot_manager()
    result = await manager.get_qrcode()

    if result.get("qrcode_url") is None and result.get("status") != "logging_in":
        raise HTTPException(
            status_code=400,
            detail=f"当前状态为 {result.get('status')}，不需要扫码"
        )

    return result


@router.get("/login-qrcode", dependencies=[Depends(verify_api_key)])
async def get_login_qrcode():
    """获取当前登录二维码（规格路径，兼容 /qrcode）。"""
    return await get_qrcode()


@router.post("/send", dependencies=[Depends(verify_api_key)])
async def send_message(request: SendMessageRequest):
    """运维测试发送微信消息。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    manager = get_wechatbot_manager()
    result = await manager.send_message(request.user_id, request.text)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "发送失败"))
    return result
