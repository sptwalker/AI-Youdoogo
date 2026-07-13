"""FastAPI 主入口：健康检查 + 依赖连通性自检。"""

import logging

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.data_sources import router as data_sources_router
from app.api.v1.discussion import message_router as discussion_message_router
from app.api.v1.discussion import router as discussion_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.knowledge_bases import router as knowledge_bases_router
from app.api.v1.meetings import router as meetings_router
from app.api.v1.ops_data import router as ops_data_router
from app.api.v1.org import router as org_router
from app.api.v1.proposals import router as proposals_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.api.v1.workbench import router as workbench_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import ok, register_exception_handlers
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="创想悦动AI决策大脑系统", version="0.1.0")
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
app.include_router(workbench_router, prefix="/api/v1")
app.include_router(discussion_router, prefix="/api/v1")
app.include_router(discussion_message_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict:
    """存活探针。"""
    return ok({"version": app.version, "env": settings.app_env})


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
