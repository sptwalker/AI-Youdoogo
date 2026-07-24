"""Compatibility facade for the canonical Environment Projection boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

import app.knowledge.ingest as _legacy_ingest
from app.contexts.foundations.environment_projection import public as projection
from app.contexts.foundations.environment_projection.contracts.context_snapshot import (
    ContextSnapshot,
)
from app.contexts.foundations.environment_projection.entrypoints import operations

ARCHIVIST_CODE = projection.ARCHIVIST_CODE
ARCHIVIST_NAME = projection.ARCHIVIST_NAME
ENV_DOC_TITLE = projection.ENV_DOC_TITLE
ensure_archivist = projection.ensure_archivist

# Existing plugins patch this module object to replace Knowledge Indexing effects.
ingest = _legacy_ingest


async def build_snapshot(db: AsyncSession) -> str:
    return await operations.build_snapshot(db)


async def get_context_snapshot(db: AsyncSession) -> ContextSnapshot:
    return await operations._get_context_snapshot(
        db,
        snapshot_builder=build_snapshot,
    )


def invalidate_cache() -> None:
    operations.invalidate_cache()


async def refresh_env_doc(
    db: AsyncSession,
    *,
    suppress_errors: bool = True,
) -> None:
    await operations._refresh_env_doc(
        db,
        snapshot_builder=build_snapshot,
        suppress_errors=suppress_errors,
    )


async def get_env_context(db: AsyncSession) -> str:
    return await operations._get_env_context(
        db,
        snapshot_reader=get_context_snapshot,
    )


__all__ = [
    "ARCHIVIST_CODE",
    "ARCHIVIST_NAME",
    "ENV_DOC_TITLE",
    "build_snapshot",
    "ensure_archivist",
    "get_context_snapshot",
    "get_env_context",
    "ingest",
    "invalidate_cache",
    "refresh_env_doc",
]
