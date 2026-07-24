"""Canonical Environment Projection operations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.environment_projection.application.snapshot import (
    ENV_DOC_TITLE,
    BuildEnvironmentSnapshot,
)
from app.contexts.foundations.environment_projection.contracts.context_snapshot import (
    ContextSnapshot,
    MissingSnapshotSource,
    SnapshotScope,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ARCHIVIST_CODE as ARCHIVIST_CODE,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ARCHIVIST_NAME as ARCHIVIST_NAME,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ensure_archivist as ensure_archivist,
)
from app.contexts.foundations.environment_projection.infrastructure.projection_store import (
    load_snapshot_source_metadata,
    prepare_archive_target,
    replace_archived_snapshot,
)
from app.contexts.foundations.environment_projection.infrastructure.published_sources import (
    PublishedEnvironmentSourceReader,
)
from app.platform.outbox.source_change import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)

_ENV_DOC_CATEGORY = "系统档案"
_CACHE_TTL_SECONDS = 60.0
_SNAPSHOT_AREAS = ("organization", "expert", "identity", "connector")

_cache: ContextSnapshot | None = None

SnapshotBuilder = Callable[[AsyncSession], Awaitable[str]]
SnapshotReader = Callable[[AsyncSession], Awaitable[ContextSnapshot]]


async def build_snapshot(session: AsyncSession) -> str:
    return await BuildEnvironmentSnapshot(
        PublishedEnvironmentSourceReader(session)
    ).execute()


async def get_context_snapshot(session: AsyncSession) -> ContextSnapshot:
    return await _get_context_snapshot(session, snapshot_builder=build_snapshot)


async def _get_context_snapshot(
    session: AsyncSession,
    *,
    snapshot_builder: SnapshotBuilder,
) -> ContextSnapshot:
    global _cache
    now = datetime.now(UTC)
    if _cache is not None and not _cache.is_expired(now):
        return _cache
    scope = SnapshotScope(tenant_id=DEFAULT_TENANT_ID, areas=_SNAPSHOT_AREAS)
    try:
        content = await snapshot_builder(session)
        provenance, versions = await load_snapshot_source_metadata(session)
    except Exception:  # noqa: BLE001 - callers inspect stale/missing instead
        logger.warning("环境快照构建失败，本次不注入", exc_info=True)
        return ContextSnapshot(
            scope=scope,
            content="",
            provenance=(),
            source_versions=(),
            missing=tuple(
                MissingSnapshotSource(
                    source_type=area,
                    reason="projection_unavailable",
                )
                for area in scope.areas
            ),
            stale=True,
            generated_at=now,
            expires_at=now,
        )
    snapshot = ContextSnapshot(
        scope=scope,
        content=content,
        provenance=provenance,
        source_versions=versions,
        missing=(),
        stale=False,
        generated_at=now,
        expires_at=now + timedelta(seconds=_CACHE_TTL_SECONDS),
    )
    _cache = snapshot
    return snapshot


def invalidate_cache() -> None:
    global _cache
    _cache = None


async def refresh_env_doc(
    session: AsyncSession,
    *,
    suppress_errors: bool = True,
) -> None:
    await _refresh_env_doc(
        session,
        snapshot_builder=build_snapshot,
        suppress_errors=suppress_errors,
    )


async def _refresh_env_doc(
    session: AsyncSession,
    *,
    snapshot_builder: SnapshotBuilder,
    suppress_errors: bool,
) -> None:
    invalidate_cache()
    try:
        target = await prepare_archive_target(session)
        if target is None:
            logger.warning("环境快照跳过：系统尚无 admin 用户可作 uploader")
            return
        text = await snapshot_builder(session)
        await replace_archived_snapshot(
            session,
            target=target,
            title=ENV_DOC_TITLE,
            category=_ENV_DOC_CATEGORY,
            text=text,
        )
    except Exception:  # noqa: BLE001 - compatibility refresh remains non-fatal
        logger.warning("环境快照刷新失败（不影响业务操作）", exc_info=True)
        if not suppress_errors:
            raise


async def get_env_context(session: AsyncSession) -> str:
    return await _get_env_context(session, snapshot_reader=get_context_snapshot)


async def _get_env_context(
    session: AsyncSession,
    *,
    snapshot_reader: SnapshotReader,
) -> str:
    snapshot = await snapshot_reader(session)
    return snapshot.content if snapshot.is_usable() else ""
