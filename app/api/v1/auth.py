"""鉴权接口：密码登录 / 飞书登录 / 刷新 / 当前用户。

登出为客户端丢弃令牌（无状态 JWT），不设服务端接口。
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.core.security import create_access_token
from app.integrations.feishu.oauth import FeishuOAuthError
from app.schemas.auth import FeishuExchangeResponse, LoginRequest, TokenResponse, UserOut
from app.services.auth_service import authenticate, authenticate_feishu
from app.services.feishu_login import (
    EXCHANGE_TTL_SECONDS,
    STATE_TTL_SECONDS,
    FeishuLoginService,
    InvalidOAuthCallback,
    InvalidOAuthState,
    InvalidReturnTo,
    OAuthUnavailable,
    get_feishu_login_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

STATE_COOKIE = "youdoo_feishu_oauth_binding"
EXCHANGE_COOKIE = "youdoo_feishu_exchange"
CALLBACK_COOKIE_PATH = "/api/v1/auth/feishu/callback"
EXCHANGE_COOKIE_PATH = "/api/v1/auth/feishu/exchange"
LOGIN_RESULT_PATHS = {
    "success": "/login?feishu=success",
    "cancelled": "/login?feishu=cancelled",
    "access_required": "/login?feishu=access_required",
    "invalid_state": "/login?feishu=invalid_state",
    "error": "/login?feishu=error",
    "unavailable": "/login?feishu=unavailable",
}

FeishuService = Annotated[FeishuLoginService, Depends(get_feishu_login_service)]


def _token_for(user_id: Any, role_code: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id, role_code),
        expires_in=get_settings().jwt_expire_minutes * 60,
    )


def _login_redirect(result: str) -> RedirectResponse:
    response = RedirectResponse(LOGIN_RESULT_PATHS[result], status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.delete_cookie(STATE_COOKIE, path=CALLBACK_COOKIE_PATH)
    return response


def _exchange_error(msg: str, status_code: int) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={"code": status_code, "msg": msg, "data": None},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
    response.delete_cookie(EXCHANGE_COOKIE, path=EXCHANGE_COOKIE_PATH)
    return response


@router.post("/login")
async def login(body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    """用户名+密码登录，签发访问令牌。"""
    user = await authenticate(db, body.username, body.password)
    return ok(_token_for(user.id, user.role_code).model_dump())


@router.get("/feishu/status")
async def feishu_status(service: FeishuService) -> dict:
    """Public feature status only; never exposes which credential is missing."""
    return ok({"enabled": service.is_available()})


@router.get("/feishu/start")
async def feishu_start(
    service: FeishuService,
    return_to: str | None = None,
) -> RedirectResponse:
    """Create browser-bound state and redirect to Feishu's authorization page."""
    try:
        started = await service.start(return_to)
    except InvalidReturnTo as exc:
        raise AppError("返回地址无效", code=400, status_code=400) from exc
    except OAuthUnavailable as exc:
        raise AppError(
            "飞书登录暂不可用，请联系管理员。", code=503, status_code=503
        ) from exc
    response = RedirectResponse(started.authorization_url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        STATE_COOKIE,
        started.browser_binding,
        max_age=STATE_TTL_SECONDS,
        path=CALLBACK_COOKIE_PATH,
        secure=started.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/feishu/callback")
async def feishu_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: FeishuService,
) -> RedirectResponse:
    """Verify one-time state, authenticate the Feishu user, and stage an app JWT handoff."""
    query = request.scope.get("state", {}).get("feishu_oauth_query", {})
    state = query.get("state", "") if isinstance(query, dict) else ""
    code = query.get("code", "") if isinstance(query, dict) else ""
    provider_error = query.get("error", "") if isinstance(query, dict) else ""
    binding = request.cookies.get(STATE_COOKIE, "")

    try:
        transaction = await service.consume_callback_state(state, binding)
    except InvalidOAuthState:
        return _login_redirect("invalid_state")
    except OAuthUnavailable:
        return _login_redirect("unavailable")

    if provider_error:
        return _login_redirect("cancelled" if provider_error == "access_denied" else "error")

    try:
        completed = await service.exchange_code(transaction, code)
    except InvalidOAuthCallback:
        return _login_redirect("error")
    except OAuthUnavailable:
        return _login_redirect("unavailable")
    except FeishuOAuthError as exc:
        logger.warning("飞书 OAuth 认证失败 stage=%s", exc.stage)
        return _login_redirect("error")

    try:
        user = await authenticate_feishu(db, completed.identity.open_id)
    except AppError as exc:
        if exc.status_code == 403:
            return _login_redirect("access_required")
        raise

    token = _token_for(user.id, user.role_code)
    try:
        handle, secure = await service.create_exchange(
            access_token=token.access_token,
            token_type=token.token_type,
            expires_in=token.expires_in,
            redirect_to=completed.return_to,
        )
    except OAuthUnavailable:
        return _login_redirect("unavailable")
    response = _login_redirect("success")
    response.set_cookie(
        EXCHANGE_COOKIE,
        handle,
        max_age=EXCHANGE_TTL_SECONDS,
        path=EXCHANGE_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/feishu/exchange")
async def feishu_exchange(request: Request, service: FeishuService) -> JSONResponse:
    """Atomically consume the HttpOnly handoff and return the existing app JWT shape."""
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site", "")
    try:
        expected_origin = service.expected_origin()
    except OAuthUnavailable:
        return _exchange_error("飞书登录暂不可用，请联系管理员。", 503)
    if (origin and origin.rstrip("/") != expected_origin) or fetch_site == "cross-site":
        return _exchange_error("登录交换请求无效，请重新登录。", 403)
    handle = request.cookies.get(EXCHANGE_COOKIE, "")
    try:
        exchange = await service.consume_exchange(handle)
    except InvalidOAuthState:
        return _exchange_error("登录凭证已失效，请重新使用飞书登录。", 400)
    except OAuthUnavailable:
        return _exchange_error("飞书登录暂不可用，请联系管理员。", 503)

    payload = FeishuExchangeResponse(
        access_token=exchange.access_token,
        token_type=exchange.token_type,
        expires_in=exchange.expires_in,
        redirect_to=exchange.redirect_to,
    )
    response = JSONResponse(
        content=ok(payload.model_dump()),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
    response.delete_cookie(EXCHANGE_COOKIE, path=EXCHANGE_COOKIE_PATH)
    return response


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
