"""接口层公共依赖：当前用户解析与角色守卫。"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt as pyjwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.contracts import RolePolicyRequest
from app.contexts.foundations.access_control.entrypoints import policy
from app.contexts.foundations.identity.application.contracts import IdentityUserResult
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.foundations.identity.public import get_user_by_id
from app.contexts.shared_kernel import AuthenticationFailed, PermissionDenied
from app.core.config import get_settings
from app.core.internal_token import InternalClaims, verify_internal_token
from app.core.security import decode_access_token
from app.platform.database import get_db

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IdentityUserResult:
    """解析 Bearer 令牌并加载用户（实时查库，停用/删除立即失效）。

    Raises:
        ApplicationError: 未携带/非法/过期令牌（401），账号停用（403）。
    """
    if credentials is None:
        raise AuthenticationFailed("未登录")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (pyjwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise AuthenticationFailed("令牌无效或已过期") from exc
    user = await get_user_by_id(db, user_id=user_id)
    if user is None:
        raise AuthenticationFailed("令牌无效或已过期")
    if not user.is_active:
        raise PermissionDenied("账号已停用")
    return user


CurrentUser = Annotated[IdentityUserResult, Depends(get_current_user)]


async def require_human(user: CurrentUser) -> IdentityUserResult:
    """生效动作红线守卫（纵深防御）：必须已认证真人触发。

    AI 员工经 run_agent 内部运行、不持 JWT，故任何进入本依赖的请求天然是真人；
    与角色门（require_roles）并存标注「生效动作」，配合「生效函数不进 agent tool 注册表」。
    """
    return user


HumanUser = Annotated[IdentityUserResult, Depends(require_human)]


def require_roles(*roles: str) -> Callable[..., Coroutine[Any, Any, IdentityUserResult]]:
    """角色守卫依赖工厂：require_roles("admin") / require_roles("admin", "executive")。

    判定收敛到 permission_service.check_role（单一角色判定权威，F4b）。
    """

    async def _guard(user: CurrentUser) -> IdentityUserResult:
        decision = policy.decide_role(
            RolePolicyRequest(
                principal=Principal(
                    principal_type=PrincipalType.USER,
                    principal_id=user.id,
                    role_code=user.role_code,
                    department_id=user.department_id,
                    is_active=user.is_active,
                ),
                allowed_roles=tuple(roles),
            )
        )
        if not decision.allowed:
            raise PermissionDenied(decision.reason)
        return user

    return _guard


def require_service(
    *required_scopes: str,
) -> Callable[..., Coroutine[Any, Any, InternalClaims]]:
    """服务身份守卫依赖工厂（Internal JWT / C1）：require_service("llm:invoke")。

    校验 Bearer 为本平台签发的 ES256 服务令牌，且 required_scopes ⊆ claims.scope。
    返回 InternalClaims（**不查用户库**——服务身份不是用户，与 get_current_user 彻底分开）。

    audience = 本平台 issuer（本轮单进程自签自验，平台既是签发方也是受众）；
    ponytail: 跨服务部署时改为按目标服务分配的 aud（Phase 1 多服务）。
    ponytail: 本轮仅提供依赖、不挂任何路由（无入站远端）；首个入站远端端点在 Phase 1 挂载。
    """

    async def _guard(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> InternalClaims:
        if credentials is None:
            raise AuthenticationFailed("未携带服务令牌")
        claims = verify_internal_token(
            credentials.credentials, audience=get_settings().internal_jwt_issuer
        )
        missing = set(required_scopes) - set(claims.scope)
        if missing:
            raise PermissionDenied(f"服务令牌缺少权限：{sorted(missing)}")
        return claims

    return _guard
