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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key
from app.config import settings
from app.services.wechatbot.audit import get_audit_logger
from app.services.wechatbot.binding_store import get_binding_store, normalize_mode
from app.services.wechatbot.channel_manager import get_wechatbot_channel_manager
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


class CreateBindTokenRequest(BaseModel):
    """创建绑定码请求。"""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(..., alias="tenantId", min_length=1)
    app_user_id: str = Field(..., alias="appUserId", min_length=1)
    default_mode: str | None = Field(default=None, alias="defaultMode")
    rag_scope: dict[str, Any] | None = Field(default=None, alias="ragScope")
    ttl_seconds: int | None = Field(default=None, alias="ttlSeconds", ge=60)


class ModeBChannelRequest(BaseModel):
    """Mode B 每用户独立微信通道请求。"""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(..., alias="tenantId", min_length=1)
    app_user_id: str = Field(..., alias="appUserId", min_length=1)
    bot_instance_id: str | None = Field(default=None, alias="botInstanceId")
    force_login: bool = Field(default=False, alias="forceLogin")


class BindingQueryResponse(BaseModel):
    """绑定查询响应。"""

    id: int | None = None
    bot_instance_id: str
    user_id_hash: str
    tenant_id: str
    app_user_id: str
    default_mode: str | None = None
    enabled: bool
    bind_source: str
    last_seen_at: str | None = None


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


@router.post("/bind-tokens", dependencies=[Depends(verify_api_key)])
async def create_bind_token(request: CreateBindTokenRequest):
    """创建一次性微信绑定码。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    store = get_binding_store()
    token = await store.create_bind_token(
        tenant_id=request.tenant_id,
        app_user_id=request.app_user_id,
        bot_instance_id=settings.wechatbot_bot_instance_id,
        default_mode=normalize_mode(request.default_mode),
        rag_scope=request.rag_scope,
        ttl_seconds=request.ttl_seconds,
    )
    get_audit_logger().log_bind_token_created(
        token_preview=token.token_preview,
        tenant_id=request.tenant_id,
        app_user_id=request.app_user_id,
        expires_at=token.expires_at.isoformat(),
    )
    return {
        "token": token.token,
        "expiresAt": token.expires_at.isoformat(),
        "bindCommand": token.bind_command,
    }


@router.get("/bindings", dependencies=[Depends(verify_api_key)])
async def list_bindings(tenantId: str | None = None, appUserId: str | None = None):
    """查询当前绑定列表。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    store = get_binding_store()
    items = await store.list_bindings(tenant_id=tenantId, app_user_id=appUserId)
    return {
        "items": [
            {
                "id": item.id,
                "botInstanceId": item.bot_instance_id,
                "userIdHash": item.user_id_hash,
                "tenantId": item.tenant_id,
                "appUserId": item.app_user_id,
                "defaultMode": item.default_mode.value if item.default_mode else None,
                "enabled": item.enabled,
                "bindSource": item.bind_source,
                "lastSeenAt": item.last_seen_at.isoformat() if item.last_seen_at else None,
            }
            for item in items
        ]
    }


@router.delete("/bindings/{binding_id}", dependencies=[Depends(verify_api_key)])
async def disable_binding(binding_id: int):
    """禁用/解绑指定绑定。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    store = get_binding_store()
    ok = await store.disable_binding(binding_id)
    if not ok:
        raise HTTPException(status_code=404, detail="绑定不存在或已被禁用")
    return {"success": True, "bindingId": binding_id}


@router.post("/mode-b/channels/start", dependencies=[Depends(verify_api_key)])
async def start_mode_b_channel(request: ModeBChannelRequest):
    """启动 Mode B 每用户独立微信通道；首次调用会返回该用户专属登录二维码。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    result = await get_wechatbot_channel_manager().start_channel(
        tenant_id=request.tenant_id,
        app_user_id=request.app_user_id,
        bot_instance_id=request.bot_instance_id,
        force_login=request.force_login,
    )
    return result


@router.post("/mode-b/channels/stop", dependencies=[Depends(verify_api_key)])
async def stop_mode_b_channel(request: ModeBChannelRequest):
    """停止指定 Mode B 每用户独立微信通道。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    return await get_wechatbot_channel_manager().stop_channel(
        tenant_id=request.tenant_id,
        app_user_id=request.app_user_id,
        bot_instance_id=request.bot_instance_id,
    )


@router.get("/mode-b/channels/status", dependencies=[Depends(verify_api_key)])
async def get_mode_b_channel_status(
    tenantId: str,
    appUserId: str,
    botInstanceId: str | None = None,
):
    """查询指定 Mode B 每用户独立微信通道状态。"""
    if not settings.wechatbot_enabled:
        raise HTTPException(status_code=400, detail="WeChatBot 功能已禁用")

    return await get_wechatbot_channel_manager().get_channel_status(
        tenant_id=tenantId,
        app_user_id=appUserId,
        bot_instance_id=botInstanceId,
    )
