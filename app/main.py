"""FastAPI 主入口：健康检查 + 依赖连通性自检。"""

import logging

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import ok, register_exception_handlers
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="创想悦动AI决策大脑系统", version="0.1.0")
register_exception_handlers(app)


@app.get("/api/v1/health")
async def health() -> dict:
    """存活探针。"""
    return ok({"version": app.version, "env": settings.app_env})


@app.get("/api/v1/health/deps")
async def health_deps() -> dict:
    """基础设施连通性自检：PostgreSQL / Redis / MinIO 逐项报告。"""
    result: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 自检接口需吞掉一切异常逐项报告
        result["postgres"] = f"error: {exc}"

    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        result["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        result["redis"] = f"error: {exc}"

    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"http://{settings.minio_endpoint}/minio/health/live")
            resp.raise_for_status()
        result["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        result["minio"] = f"error: {exc}"

    return ok(result)
