"""Per-request trace_id: contextvar + log filter + ASGI middleware.

Correlates every log line of one request via ``X-Request-ID`` (echoed if the
client sent a sane one, else generated). Single-service today; the same header
is what an upstream OpenTelemetry collector would propagate later.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")

# 信任边界：X-Request-ID 由客户端可控——只收白名单字符+长度，否则本地生成，防日志注入/膨胀。
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{8,64}\Z")


def get_trace_id() -> str:
    """Return the current request's trace_id, or ``-`` outside a request."""
    return _trace_id.get()


def _sanitize(raw: bytes | None) -> str:
    if not raw:
        return ""
    try:
        candidate = raw.decode("ascii")
    except UnicodeDecodeError:
        return ""
    return candidate if _SAFE_ID.match(candidate) else ""


class TraceIdLogFilter(logging.Filter):
    """Inject ``trace_id`` onto every record so ``%(trace_id)s`` renders."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


class TraceIdMiddleware:
    """Set the request trace_id contextvar and echo it back as ``X-Request-ID``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or {}).get(b"x-request-id")
        trace_id = _sanitize(incoming) or uuid.uuid4().hex
        token = _trace_id.set(trace_id)
        header = (b"x-request-id", trace_id.encode("ascii"))

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(header)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _trace_id.reset(token)
