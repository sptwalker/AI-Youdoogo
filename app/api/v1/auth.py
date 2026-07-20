"""鉴权接口：登录 / 刷新 / 当前用户。

登出为客户端丢弃令牌（无状态 JWT），不设服务端接口。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ok
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services.auth_service import authenticate, login_by_feishu

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user_id: Any, role_code: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, role_code),
        expires_in=get_settings().jwt_expire_minutes * 60,
    )


@router.post("/login")
async def login(body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    """用户名+密码登录，签发访问令牌。"""
    user = await authenticate(db, body.username, body.password)
    return ok(_token_for(user.id, user.role_code).model_dump())


@router.get("/feishu/url")
async def feishu_login_url(redirect_uri: str, state: str = "") -> dict:
    """获取飞书扫码登录授权 URL（前端跳转，I2）。"""
    from app.integrations.feishu.client import feishu_client

    return ok({"url": feishu_client.oauth_authorize_url(redirect_uri, state)})


class FeishuCallback(BaseModel):
    code: str


@router.post("/feishu/callback")
async def feishu_login_callback(
    body: FeishuCallback, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict:
    """飞书回调 code 换登录令牌（首次自动开户，I2）。"""
    user = await login_by_feishu(db, body.code)
    return ok(_token_for(user.id, user.role_code).model_dump())


@router.post("/refresh")
async def refresh(user: CurrentUser) -> dict:
    """持有效令牌换发新令牌（延长有效期）。

    ponytail: 无状态 JWT 可被无限续签，止损手段=停用账号（实时查库即刻生效）；
    需要更强吊销时再加 Redis 黑名单/jti。
    """
    return ok(_token_for(user.id, user.role_code).model_dump())


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    """当前登录用户信息。"""
    return ok(UserOut.model_validate(user).model_dump(mode="json"))
