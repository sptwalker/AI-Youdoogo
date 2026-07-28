# syntax=docker/dockerfile:1
# 后端生产镜像：同一镜像支持一次性 migrate 与纯 serve 两种 CCE 命令。
FROM python:3.12-alpine

# Apply current Alpine security fixes before app layers.
RUN apk upgrade --no-cache

# uv 官方二进制
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 先装依赖（利用层缓存；仅 pyproject/uv.lock 变化才重装）
COPY pyproject.toml uv.lock ./
# BuildKit cache mount keeps uv's download cache across builds without baking it into
# the image layer; the venv is materialised into /app/.venv (UV_LINK_MODE=copy) so the
# final image carries no package-manager cache. `sharing=locked` serialises concurrent
# builds on the shared runner. `/bin/uv` is dropped so the runtime image stays lean.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project \
    && rm -rf /bin/uv

# 再拷业务代码与迁移
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker/entrypoint.sh /entrypoint.sh
RUN addgroup -g 10001 -S app \
    && adduser -u 10001 -S -D -H -G app app \
    && chmod +x /entrypoint.sh \
    && chown -R app:app /app

EXPOSE 8000
USER 10001:10001
ENTRYPOINT ["/entrypoint.sh"]
