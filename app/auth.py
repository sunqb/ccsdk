"""
认证中间件
"""
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from .openapi_auth import API_KEY_SCHEME_NAME


api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name=API_KEY_SCHEME_NAME,
    description=(
        "服务 API Key。仅当服务端已配置 AGENT_SDK_API_KEY 时必填；未配置时可不填。"
    ),
)


def get_api_key() -> Optional[str]:
    """获取配置的 API Key"""
    return os.getenv("AGENT_SDK_API_KEY")


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> Optional[str]:
    """
    验证 API Key

    如果配置了 AGENT_SDK_API_KEY，则必须在请求头中提供有效的 X-API-Key
    """
    configured_key = get_api_key()

    # 如果没有配置 API Key，则跳过验证
    if not configured_key:
        return None

    # 检查请求头中的 API Key
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API Key required. Provide X-API-Key header."
        )

    if api_key != configured_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API Key"
        )

    return api_key


def require_api_key():
    """依赖项：要求有效的 API Key"""
    return Depends(verify_api_key)
