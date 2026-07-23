"""Application startup and shutdown orchestration."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.platform.database import async_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Load runtime configuration, synchronize providers, and manage background workers."""
    from app.bootstrap import workflow_worker
    from app.contexts.foundations.environment_projection.infrastructure.archivist import (
        ensure_archivist,
    )
    from app.core import runtime_config
    from app.services import (
        ai_provider_service,
        config_service,
    )

    try:
        async with async_session_factory() as db:
            runtime_config.load(await config_service.all_values(db))
            seeded = await ai_provider_service.seed_from_env(db)
            if seeded:
                logger.info("首次部署：从 .env 种子 %d 张 AI 卡片", seeded)
            await ai_provider_service.sync_to_factory(db)
            await ensure_archivist(db)
        logger.info("配置覆盖层 + AI 卡片已载入")
    except Exception:  # noqa: BLE001 - startup keeps the environment fallback available
        logger.exception("载入配置覆盖层/AI 卡片失败")

    worker_task = workflow_worker.start_background_worker()
    if worker_task is not None:
        logger.info("durable workflow outbox worker 已启动")
    try:
        yield
    finally:
        await workflow_worker.stop_background_worker()
        from app.services.feishu_login import feishu_login_service

        await feishu_login_service.close()
