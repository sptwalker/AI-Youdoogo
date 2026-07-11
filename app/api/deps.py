"""接口层公共依赖：当前用户解析与角色守卫。"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt as pyjwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.models.system import SysUser
from app.services.auth_service import get_user_by_id

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SysUser:
    """解析 Bearer 令牌并加载用户（实时查库，停用/删除立即失效）。

    Raises:
        AppError: 未携带/非法/过期令牌（401），账号停用（403）。
    """
    if credentials is None:
        raise AppError("未登录", code=401, status_code=401)
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise AppError("令牌无效或已过期", code=401, status_code=401) from exc
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise AppError("令牌无效或已过期", code=401, status_code=401)
    if not user.is_active:
        raise AppError("账号已停用", code=403, status_code=403)
    return user


CurrentUser = Annotated[SysUser, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[..., Coroutine[Any, Any, SysUser]]:
    """角色守卫依赖工厂：require_roles("admin") / require_roles("admin", "executive")。"""

    async def _guard(user: CurrentUser) -> SysUser:
        if user.role_code not in roles:
            raise AppError("无权限执行此操作", code=403, status_code=403)
        return user

    return _guard
