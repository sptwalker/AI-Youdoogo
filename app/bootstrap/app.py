"""FastAPI application factory and system-level operational entrypoints."""

import logging

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import text

from app.bootstrap.error_wiring import register_application_error_handlers
from app.bootstrap.lifecycle import lifespan
from app.bootstrap.observability import readiness, render_metrics
from app.bootstrap.wiring import register_routes
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.oauth_query_scrub import OAuthCallbackQueryScrubMiddleware
from app.core.request_context import TraceIdMiddleware
from app.platform.database import async_session_factory, engine
from app.platform.http_runtime import ok, register_exception_handlers

logger = logging.getLogger(__name__)


def _register_operational_routes(app: FastAPI, settings: Settings) -> None:
    """Register health, readiness, dependency, and metrics entrypoints."""

    @app.get("/api/v1/health")
    async def health() -> dict:
        """Return the process liveness response."""
        return ok({"version": app.version, "env": settings.app_env})

    @app.get("/api/v1/health/ready")
    async def health_ready() -> Response:
        """Report database and active-provider readiness."""
        async with async_session_factory() as db:
            is_ready, detail = await readiness(db)
        body = ok(detail) if is_ready else {"code": 1, "msg": "not ready", "data": detail}
        return JSONResponse(body, status_code=200 if is_ready else 503)

    @app.get("/api/v1/metrics")
    async def metrics() -> Response:
        """Render process-independent Prometheus metrics from persistent state."""
        async with async_session_factory() as db:
            text_body = await render_metrics(db)
        return PlainTextResponse(text_body, media_type="text/plain; version=0.0.4")

    @app.get("/api/v1/health/deps")
    async def health_deps() -> dict:
        """Probe PostgreSQL, Redis, and MinIO without exposing connection details."""
        result: dict[str, str] = {}

        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            result["postgres"] = "ok"
        except Exception:  # noqa: BLE001 - every dependency is reported independently
            logger.exception("health/deps: postgres 连接失败")
            result["postgres"] = "error"

        try:
            redis_client = aioredis.from_url(settings.redis_url)
            await redis_client.ping()
            await redis_client.aclose()
            result["redis"] = "ok"
        except Exception:  # noqa: BLE001
            logger.exception("health/deps: redis 连接失败")
            result["redis"] = "error"

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"http://{settings.minio_endpoint}/minio/health/live")
                response.raise_for_status()
            result["minio"] = "ok"
        except Exception:  # noqa: BLE001
            logger.exception("health/deps: minio 连接失败")
            result["minio"] = "error"

        return ok(result)


def create_app() -> FastAPI:
    """Create and wire the FastAPI application at the outermost boundary."""
    settings = get_settings()
    setup_logging(settings.log_level)
    application = FastAPI(
        title="创想悦动AI决策大脑系统",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(OAuthCallbackQueryScrubMiddleware)
    application.add_middleware(TraceIdMiddleware)  # 最后加=最外层，trace_id 先于一切就位
    register_exception_handlers(application)
    register_application_error_handlers(application)
    register_routes(application)
    _register_operational_routes(application, settings)
    return application


app = create_app()
