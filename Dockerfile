# 后端生产镜像：同一镜像支持一次性 migrate 与纯 serve 两种 CCE 命令。
FROM m.daocloud.io/docker.io/library/python:3.12-alpine

# The mirror tag can lag Alpine point rebuilds; install current security fixes before app layers.
RUN apk upgrade --no-cache

# uv 官方二进制
COPY --from=m.daocloud.io/ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv

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
RUN uv sync --frozen --no-dev --no-install-project --no-cache \
    && rm -rf /root/.cache/uv /bin/uv

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
