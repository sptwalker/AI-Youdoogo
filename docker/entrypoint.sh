#!/bin/sh
# 无参数保持原 Compose 行为；CCE 分别使用 migrate 与 serve，避免每个副本跑迁移。
set -eu

migrate() {
    echo "[entrypoint] alembic upgrade head ..."
    alembic upgrade head
}

serve() {
    echo "[entrypoint] starting uvicorn with ${WEB_CONCURRENCY:-2} workers ..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
}

case "${1:-}" in
    migrate)
        migrate
        ;;
    serve)
        serve
        ;;
    "")
        migrate
        serve
        ;;
    *)
        exec "$@"
        ;;
esac
