"""鉴权与用户管理业务逻辑。"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import (
    ApplicationError,
    AuthenticationFailed,
    ConflictDetected,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.models.system import SysUser
from app.schemas.auth import VALID_ROLES, UserCreate, UserUpdate
from app.services.feishu_oauth_config import valid_feishu_open_id


async def authenticate(db: AsyncSession, username: str, password: str) -> SysUser:
    """按用户名+密码认证，失败抛统一错误（不区分用户不存在/密码错，防枚举）。

    用户不存在时也执行一次 bcrypt 校验，使两分支耗时一致（防时序侧信道枚举用户名）。

    Raises:
        ApplicationError: 认证失败（401）或账号停用（403）。
    """
    stmt = select(SysUser).where(SysUser.username == username, SysUser.is_delete.is_(False))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        verify_password(password, DUMMY_HASH)  # 恒定耗时
        raise AuthenticationFailed("用户名或密码错误")
    if not verify_password(password, user.password_hash):
        raise AuthenticationFailed("用户名或密码错误")
    if not user.is_active:
        raise PermissionDenied("账号已停用")
    return user


def _deny_feishu_user() -> ApplicationError:
    """未绑定、停用和软删统一拒绝，避免枚举本地账号状态。"""
    return PermissionDenied("当前飞书账号暂无系统访问权限，请联系管理员完成账号授权或状态确认。")


async def _find_feishu_user(db: AsyncSession, open_id: str) -> SysUser | None:
    """Resolve only by the app-scoped, stable Feishu identity key."""
    stmt = select(SysUser).where(SysUser.feishu_open_id == open_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def authenticate_feishu(db: AsyncSession, open_id: str) -> SysUser:
    """仅按当前应用的稳定 ``open_id`` 认证已预绑定的本地账号。

    飞书只证明外部身份，不创建本地账号、不变更角色，也不按姓名、邮箱或手机号合并。
    返回的 ``SysUser`` 是角色与权限的唯一事实源，OAuth 登录与密码登录共用后续
    JWT、``/me`` 和权限依赖链路。
    """
    if not valid_feishu_open_id(open_id):
        raise AuthenticationFailed("飞书未返回用户标识")

    user = await _find_feishu_user(db, open_id)
    if user is None or user.is_delete or not user.is_active:
        raise _deny_feishu_user()
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> SysUser | None:
    """按ID取未删除用户。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


async def login_by_feishu(db: AsyncSession, code: str) -> SysUser:
    """飞书 SSO：用回调 code 换身份，再精确解析已预绑定的本地用户。

    该兼容端点与浏览器 PKCE 回调共享相同预绑定策略；不自动开户或授予角色。

    Raises:
        ApplicationError: 飞书换取身份失败 / 未绑定 / 账号停用或软删。
    """
    from app.integrations.feishu.client import FeishuAPIError, feishu_client

    try:
        info = await feishu_client.oauth_user_info(code)
    except FeishuAPIError as exc:
        raise AuthenticationFailed(f"飞书登录失败:{exc}") from exc
    open_id = info.get("open_id")
    if not isinstance(open_id, str):
        raise AuthenticationFailed("飞书未返回用户标识")
    return await authenticate_feishu(db, open_id)


def _check_role(role_code: str) -> None:
    if role_code not in VALID_ROLES:
        raise RuleViolation(f"非法角色：{role_code}，可选 {'/'.join(VALID_ROLES)}")


async def _refresh_env(db: AsyncSession) -> None:
    """用户变更后刷新环境快照（docs/13 §9）。局部 import 防循环依赖；内部吞异常。"""
    from app.services import environment_service

    await environment_service.refresh_env_doc(db)


async def create_user(db: AsyncSession, data: UserCreate) -> SysUser:
    """创建用户（用户名唯一）。"""
    _check_role(data.role_code)
    exists = (
        await db.execute(select(SysUser.id).where(SysUser.username == data.username))
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictDetected("用户名已存在")
    user = SysUser(
        username=data.username,
        password_hash=hash_password(data.password),
        real_name=data.real_name,
        role_code=data.role_code,
        department_id=data.department_id,
        feishu_open_id=data.feishu_open_id,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:  # 先查后插的竞态窗口（如双击提交），撞唯一约束兜底为 409
        await db.rollback()
        msg = "该飞书身份已绑定其他用户" if data.feishu_open_id else "用户名已存在"
        raise ConflictDetected(msg) from exc
    await db.refresh(user)
    await _refresh_env(db)
    return user


async def list_users(db: AsyncSession) -> list[SysUser]:
    """列出全部未删除用户。"""
    stmt = select(SysUser).where(SysUser.is_delete.is_(False)).order_by(SysUser.create_time)
    return list((await db.execute(stmt)).scalars())


async def update_user(db: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> SysUser:
    """更新用户：仅更新提供的字段。

    Raises:
        ApplicationError: 用户不存在（404）或角色非法（400）。
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise ResourceNotFound("用户不存在")
    if data.role_code is not None:
        _check_role(data.role_code)
        user.role_code = data.role_code
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    if data.real_name is not None:
        user.real_name = data.real_name
    if data.department_id is not None:
        user.department_id = data.department_id
    if data.is_active is not None:
        user.is_active = data.is_active
    feishu_binding_changed = "feishu_open_id" in data.model_fields_set
    if feishu_binding_changed:
        user.feishu_open_id = data.feishu_open_id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if feishu_binding_changed:
            raise ConflictDetected("该飞书身份已绑定其他用户") from exc
        raise
    await db.refresh(user)
    await _refresh_env(db)
    return user
