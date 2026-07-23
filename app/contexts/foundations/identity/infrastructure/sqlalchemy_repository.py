"""SQLAlchemy persistence adapter for the Identity-owned account model."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.domain.models import IdentityAccount
from app.models.system import SysUser


def _to_domain(user: SysUser) -> IdentityAccount:
    return IdentityAccount(
        id=user.id,
        username=user.username,
        password_hash=user.password_hash,
        real_name=user.real_name,
        role_code=user.role_code,
        department_id=user.department_id,
        is_active=user.is_active,
        feishu_open_id=user.feishu_open_id,
        en_name=user.en_name,
        title=user.title,
        mobile=user.mobile,
        avatar_url=user.avatar_url,
        create_time=user.create_time,
        is_deleted=user.is_delete,
    )


def _from_domain(account: IdentityAccount) -> SysUser:
    return SysUser(
        id=account.id,
        username=account.username,
        password_hash=account.password_hash,
        real_name=account.real_name,
        role_code=account.role_code,
        department_id=account.department_id,
        is_active=account.is_active,
        feishu_open_id=account.feishu_open_id,
        en_name=account.en_name,
        title=account.title,
        mobile=account.mobile,
        avatar_url=account.avatar_url,
        create_time=account.create_time,
        is_delete=account.is_deleted,
    )


class SQLAlchemyIdentityRepository:
    """Map the existing ORM row without exposing it to Identity application code."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows: dict[uuid.UUID, SysUser] = {}

    async def find_by_username(self, username: str) -> IdentityAccount | None:
        stmt = select(SysUser).where(
            SysUser.username == username,
            SysUser.is_delete.is_(False),
        )
        user = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(user) if user is not None else None

    async def find_by_feishu_open_id(self, open_id: str) -> IdentityAccount | None:
        stmt = select(SysUser).where(SysUser.feishu_open_id == open_id)
        user = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(user) if user is not None else None

    async def get_by_id(self, user_id: uuid.UUID) -> IdentityAccount | None:
        stmt = select(SysUser).where(
            SysUser.id == user_id,
            SysUser.is_delete.is_(False),
        )
        user = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(user) if user is not None else None

    async def username_exists(self, username: str) -> bool:
        # Preserve the old service's pre-check: a soft-deleted username still
        # blocks creation, while the database's partial index remains the race
        # condition fallback for active rows.
        stmt = select(SysUser.id).where(SysUser.username == username)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def add(self, account: IdentityAccount) -> None:
        row = _from_domain(account)
        self._rows[account.id] = row
        self._session.add(row)

    async def save(self, account: IdentityAccount) -> None:
        row = self._rows.get(account.id)
        if row is None:
            row = await self._session.get(SysUser, account.id)
        if row is None:
            return
        self._rows[account.id] = row
        row.username = account.username
        row.password_hash = account.password_hash
        row.real_name = account.real_name
        row.role_code = account.role_code
        row.department_id = account.department_id
        row.is_active = account.is_active
        row.feishu_open_id = account.feishu_open_id
        row.en_name = account.en_name
        row.title = account.title
        row.mobile = account.mobile
        row.avatar_url = account.avatar_url
        row.is_delete = account.is_deleted

    async def list_accounts(self) -> list[IdentityAccount]:
        stmt = (
            select(SysUser)
            .where(SysUser.is_delete.is_(False))
            .order_by(SysUser.create_time)
        )
        users = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(user) for user in users]
