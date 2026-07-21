"""鉴权与用户管理业务逻辑。"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.models.system import SysUser
from app.schemas.auth import VALID_ROLES, UserCreate, UserUpdate


async def authenticate(db: AsyncSession, username: str, password: str) -> SysUser:
    """按用户名+密码认证，失败抛统一错误（不区分用户不存在/密码错，防枚举）。

    用户不存在时也执行一次 bcrypt 校验，使两分支耗时一致（防时序侧信道枚举用户名）。

    Raises:
        AppError: 认证失败（401）或账号停用（403）。
    """
    stmt = select(SysUser).where(SysUser.username == username, SysUser.is_delete.is_(False))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        verify_password(password, DUMMY_HASH)  # 恒定耗时
        raise AppError("用户名或密码错误", code=401, status_code=401)
    if not verify_password(password, user.password_hash):
        raise AppError("用户名或密码错误", code=401, status_code=401)
    if not user.is_active:
        raise AppError("账号已停用", code=403, status_code=403)
    return user


async def authenticate_feishu(db: AsyncSession, open_id: str) -> SysUser:
    """按已绑定的飞书 open_id 认证，不自动创建用户或授予角色。

    未绑定、已删除和已停用统一返回同一消息，避免枚举系统内账号状态。
    """
    stmt = select(SysUser).where(
        SysUser.feishu_open_id == open_id,
        SysUser.is_delete.is_(False),
        SysUser.is_active.is_(True),
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise AppError(
            "当前飞书账号暂无系统访问权限，请联系管理员完成账号授权或状态确认。",
            code=403,
            status_code=403,
        )
    return user


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> SysUser | None:
    """按ID取未删除用户。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


async def login_by_feishu(db: AsyncSession, code: str) -> SysUser:
    """飞书 SSO:用回调 code 换飞书身份 → 按 open_id 找/建本地用户 → 返回（供签发 JWT）。

    首次登录自动开户（默认 member 最低权限，红线：角色变更仍走 admin）;已存在直接登录。
    若该 open_id 已由 I1 组织同步预建，则复用并激活。

    Raises:
        AppError: 飞书换取身份失败 / 账号停用。
    """
    from app.integrations.feishu.client import FeishuAPIError, feishu_client

    try:
        info = await feishu_client.oauth_user_info(code)
    except FeishuAPIError as exc:
        raise AppError(f"飞书登录失败:{exc}", code=401, status_code=401) from exc
    open_id = info.get("open_id")
    if not open_id:
        raise AppError("飞书未返回用户标识", code=401, status_code=401)

    user = (
        await db.execute(
            select(SysUser).where(
                SysUser.feishu_open_id == open_id, SysUser.is_delete.is_(False)
            )
        )
    ).scalar_one_or_none()
    if user is None:
        user = SysUser(
            username=f"fs_{open_id[:24]}", password_hash="!feishu-sso",
            feishu_open_id=open_id, role_code="member",
            real_name=info.get("name") or "", en_name=info.get("en_name") or "",
            avatar_url=info.get("avatar_url") or "",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        await _refresh_env(db)
    elif not user.is_active:
        raise AppError("账号已停用", code=403, status_code=403)
    return user



def _check_role(role_code: str) -> None:
    if role_code not in VALID_ROLES:
        raise AppError(f"非法角色：{role_code}，可选 {'/'.join(VALID_ROLES)}")


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
        raise AppError("用户名已存在", code=409, status_code=409)
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
        raise AppError(msg, code=409, status_code=409) from exc
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
        AppError: 用户不存在（404）或角色非法（400）。
    """
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise AppError("用户不存在", code=404, status_code=404)
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
            raise AppError("该飞书身份已绑定其他用户", code=409, status_code=409) from exc
        raise
    await db.refresh(user)
    await _refresh_env(db)
    return user
