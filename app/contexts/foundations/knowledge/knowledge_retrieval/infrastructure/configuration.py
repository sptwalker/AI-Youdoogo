"""Read-only retrieval configuration adapter."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sys_config import SysConfig


async def resolve(session: AsyncSession, key: str, default: Any = None) -> Any:
    statement = select(SysConfig).where(
        SysConfig.key == key,
        SysConfig.is_delete.is_(False),
    )
    config = (await session.execute(statement)).scalar_one_or_none()
    return config.value if config is not None else default
