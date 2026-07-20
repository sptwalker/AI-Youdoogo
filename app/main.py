"""FastAPI 主入口：健康检查 + 依赖连通性自检。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import text

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.ai_providers import router as ai_providers_router
from app.api.v1.auth import router as auth_router
from app.api.v1.collab import router as collab_router
from app.api.v1.data_sources import router as data_sources_router
from app.api.v1.desktop import router as desktop_router
from app.api.v1.discussion import message_router as discussion_message_router
from app.api.v1.discussion import router as discussion_router
from app.api.v1.eval import router as eval_router
from app.api.v1.grants import router as grants_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.knowledge_bases import router as knowledge_bases_router
from app.api.v1.meetings import router as meetings_router
from app.api.v1.ops_data import router as ops_data_router
from app.api.v1.org import router as org_router
from app.api.v1.proposals import router as proposals_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import ok, register_exception_handlers
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时载入 sys_config 覆盖层 + 把 AI 卡片推进 LLM 网关（无卡片时 AI 不可用）。"""
    from app.core import runtime_config
    from app.core.database import async_session_factory
    from app.services import ai_provider_service, config_service, environment_service

    try:
        async with async_session_factory() as db:
            runtime_config.load(await config_service.all_values(db))
            seeded = await ai_provider_service.seed_from_env(db)  # 首次部署兜底建卡（docs/12）
            if seeded:
                logger.info("首次部署：从 .env 种子 %d 张 AI 卡片", seeded)
            await ai_provider_service.sync_to_factory(db)
            await environment_service.ensure_archivist(db)  # 系统档案员自举（docs/13 §9）
            # 崩溃恢复（H4.1）：复位孤儿步骤 + 续跑未完成的编排（best-effort，不阻断启动）
            from app.services import orchestration_service

            try:
                await orchestration_service.recover_incomplete(db)
            except Exception:  # noqa: BLE001 - 恢复失败不阻断启动
                logger.warning("编排崩溃恢复失败", exc_info=True)
        logger.info("配置覆盖层 + AI 卡片已载入")
    except Exception:  # noqa: BLE001 - 载入失败退回 .env，不阻断启动
        logger.exception("载入配置覆盖层/AI 卡片失败")
    yield


app = FastAPI(title="创想悦动AI决策大脑系统", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(knowledge_bases_router, prefix="/api/v1")
app.include_router(data_sources_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(ops_data_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(proposals_router, prefix="/api/v1")
app.include_router(meetings_router, prefix="/api/v1")
app.include_router(org_router, prefix="/api/v1")
app.include_router(desktop_router, prefix="/api/v1")
app.include_router(discussion_router, prefix="/api/v1")
app.include_router(discussion_message_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(grants_router, prefix="/api/v1")
app.include_router(collab_router, prefix="/api/v1")
app.include_router(ai_providers_router, prefix="/api/v1")
app.include_router(semantic_router, prefix="/api/v1")
app.include_router(eval_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict:
    """存活探针。"""
    return ok({"version": app.version, "env": settings.app_env})


@app.get("/api/v1/health/ready")
async def health_ready() -> Response:
    """就绪探针（H2.4）：DB 可达 + 至少一张 active AI 卡片。未就绪回 503。"""
    from app.core.database import async_session_factory
    from app.services import metrics_service

    async with async_session_factory() as db:
        is_ready, detail = await metrics_service.readiness(db)
    body = ok(detail) if is_ready else {"code": 1, "msg": "not ready", "data": detail}
    return JSONResponse(body, status_code=200 if is_ready else 503)


@app.get("/api/v1/metrics")
async def metrics() -> Response:
    """Prometheus 指标（H2.4，文本格式）。从 DB 聚合，跨 worker 一致。"""
    from app.core.database import async_session_factory
    from app.services import metrics_service

    async with async_session_factory() as db:
        text_body = await metrics_service.render_metrics(db)
    return PlainTextResponse(text_body, media_type="text/plain; version=0.0.4")


@app.get("/api/v1/health/deps")
async def health_deps() -> dict:
    """基础设施连通性自检：PostgreSQL / Redis / MinIO 逐项报告。

    异常细节只进日志不回显（连接串含主机/账号信息，防匿名探测泄露）。
    """
    result: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["postgres"] = "ok"
    except Exception:  # noqa: BLE001 - 自检接口需吞掉一切异常逐项报告
        logger.exception("health/deps: postgres 连接失败")
        result["postgres"] = "error"

    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        result["redis"] = "ok"
    except Exception:  # noqa: BLE001
        logger.exception("health/deps: redis 连接失败")
        result["redis"] = "error"

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"http://{settings.minio_endpoint}/minio/health/live")
            resp.raise_for_status()
        result["minio"] = "ok"
    except Exception:  # noqa: BLE001
        logger.exception("health/deps: minio 连接失败")
        result["minio"] = "error"

    return ok(result)
