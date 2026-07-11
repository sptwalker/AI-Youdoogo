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


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> SysUser | None:
    """按ID取未删除用户。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


def _check_role(role_code: str) -> None:
    if role_code not in VALID_ROLES:
        raise AppError(f"非法角色：{role_code}，可选 {'/'.join(VALID_ROLES)}")


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
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:  # 先查后插的竞态窗口（如双击提交），撞唯一约束兜底为 409
        await db.rollback()
        raise AppError("用户名已存在", code=409, status_code=409) from exc
    await db.refresh(user)
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
    await db.commit()
    await db.refresh(user)
    return user
