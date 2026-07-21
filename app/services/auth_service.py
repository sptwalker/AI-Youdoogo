"""鉴权与用户管理业务逻辑。"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.models.system import SysUser
from app.schemas.auth import VALID_ROLES, UserCreate, UserUpdate
from app.services.feishu_oauth_config import valid_feishu_open_id


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


def _feishu_username(open_id: str, attempt: int = 0) -> str:
    """Return a bounded, deterministic username for a provisioned identity.

    The open_id itself is never used as a profile-field lookup key or exposed in
    the username.  A long digest keeps the value within the existing 64-character
    username limit while making accidental collisions practically impossible.
    ``attempt`` is only used if an unrelated pre-existing username occupies the
    deterministic candidate.
    """
    digest = hashlib.sha256(open_id.encode("utf-8")).hexdigest()
    base = f"fs_{digest}"
    if attempt <= 0:
        return base[:64]
    suffix = f"-{attempt}"
    return f"{base[:64 - len(suffix)]}{suffix}"


def _deny_feishu_user() -> AppError:
    """Return one non-enumerating error for disabled or deleted local users."""
    return AppError(
        "当前飞书账号不可用，请联系管理员。",
        code=403,
        status_code=403,
    )


async def _find_feishu_user(db: AsyncSession, open_id: str) -> SysUser | None:
    """Resolve only by the app-scoped, stable Feishu identity key."""
    stmt = select(SysUser).where(SysUser.feishu_open_id == open_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_or_provision_feishu_user(
    db: AsyncSession,
    open_id: str,
    *,
    real_name: str | None = None,
    en_name: str | None = None,
    avatar_url: str | None = None,
) -> SysUser:
    """Resolve an active local user or provision a least-privilege member.

    The Feishu OAuth verifier is the authentication gate.  This function only
    uses ``open_id`` for identity resolution; optional profile fields are copied
    on first provision only when the current OAuth path actually supplied them.
    Disabled and soft-deleted rows remain denied, including when a concurrent
    first-login attempt races with their lookup.  A unique-constraint race is
    rolled back and rechecked so the loser returns the winner rather than
    producing a duplicate or a 500 response.
    """
    if not valid_feishu_open_id(open_id):
        raise AppError("飞书未返回用户标识", code=401, status_code=401)

    existing = await _find_feishu_user(db, open_id)
    if existing is not None:
        if existing.is_delete or not existing.is_active:
            raise _deny_feishu_user()
        return existing

    for attempt in range(8):
        user = SysUser(
            username=_feishu_username(open_id, attempt),
            password_hash="!feishu-sso",
            feishu_open_id=open_id,
            role_code="member",
        )
        # Do not invent profile data.  These assignments are made only when
        # this particular OAuth identity response supplied a string value.
        if real_name is not None:
            user.real_name = real_name
        if en_name is not None:
            user.en_name = en_name
        if avatar_url is not None:
            user.avatar_url = avatar_url
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raced = await _find_feishu_user(db, open_id)
            if raced is not None:
                if raced.is_delete or not raced.is_active:
                    raise _deny_feishu_user() from None
                return raced
            # The deterministic username may have been taken by an unrelated
            # local account.  Try the next bounded deterministic candidate.
            continue
        await db.refresh(user)
        await _refresh_env(db)
        return user

    raise AppError("飞书账号开户失败，请稍后重试。", code=503, status_code=503)


async def authenticate_feishu(
    db: AsyncSession,
    open_id: str,
    *,
    real_name: str | None = None,
    en_name: str | None = None,
    avatar_url: str | None = None,
) -> SysUser:
    """Backward-compatible name for the Feishu resolve/provision flow."""
    return await resolve_or_provision_feishu_user(
        db,
        open_id,
        real_name=real_name,
        en_name=en_name,
        avatar_url=avatar_url,
    )


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> SysUser | None:
    """按ID取未删除用户。"""
    stmt = select(SysUser).where(SysUser.id == user_id, SysUser.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


async def login_by_feishu(db: AsyncSession, code: str) -> SysUser:
    """飞书 SSO:用回调 code 换飞书身份 → 按 open_id 找/建本地用户 → 返回（供签发 JWT）。

    首次登录自动开户（默认 member 最低权限，红线：角色变更仍走 admin）;已存在直接登录。
    若该 open_id 已由 I1 组织同步预建，则复用；停用或软删账号不会被重新激活。

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

    return await resolve_or_provision_feishu_user(
        db,
        open_id,
        real_name=info.get("name") if isinstance(info.get("name"), str) else None,
        en_name=info.get("en_name") if isinstance(info.get("en_name"), str) else None,
        avatar_url=(
            info.get("avatar_url")
            if isinstance(info.get("avatar_url"), str)
            else None
        ),
    )



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
