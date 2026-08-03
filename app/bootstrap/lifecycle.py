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
    from app.contexts.foundations.governance.system_configuration import (
        public as system_configuration,
    )
    from app.contexts.foundations.governance.system_configuration.ai_provider_management import (
        public as ai_provider_management,
    )
    from app.contexts.foundations.identity.browser_login import feishu_login_service
    from app.core import runtime_config
    from app.integrations.feishu.client import feishu_client

    try:
        async with async_session_factory() as db:
            configurations = await system_configuration.list_configurations(db)
            runtime_config.load({item.key: item.value for item in configurations})
            seeded = await ai_provider_management.seed_providers_from_environment(db)
            if seeded:
                logger.info("首次部署：从 .env 种子 %d 张 AI 卡片", seeded)
            await ai_provider_management.synchronize_provider_runtime(db)
            await ensure_archivist(db)
        logger.info("配置覆盖层 + AI 卡片已载入")
    except Exception:  # noqa: BLE001 - startup keeps the environment fallback available
        logger.exception("载入配置覆盖层/AI 卡片失败")

    worker_task = workflow_worker.start_background_worker()
    if worker_task is not None:
        logger.info("durable workflow outbox worker 已启动")

    from app.platform.eventing.composition import register_relay

    if register_relay():
        logger.info("event relay 已启用（事件传输门禁 / docs/23）")
    try:
        yield
    finally:
        await workflow_worker.stop_background_worker()
        await feishu_login_service.close()
        await feishu_client.close()
