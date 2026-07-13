#!/bin/sh
# 生产启动：先跑数据库迁移（幂等，upgrade head），再多 worker 起 Uvicorn。
set -e

echo "[entrypoint] alembic upgrade head ..."
alembic upgrade head

echo "[entrypoint] starting uvicorn with ${WEB_CONCURRENCY:-2} workers ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
