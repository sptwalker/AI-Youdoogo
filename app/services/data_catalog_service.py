"""Compatibility facade for Governed Data Query catalog operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.governed_data_query.entrypoints import operations


async def allowed_views(db: AsyncSession) -> set[str]:
    return set(await operations.allowed_views(db))


async def get_catalog(db: AsyncSession) -> dict[str, Any]:
    return dict((await operations.get_catalog(db)).to_dict())


async def catalog_prompt(db: AsyncSession) -> str:
    return await operations.catalog_prompt(db)
