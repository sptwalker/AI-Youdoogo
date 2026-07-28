"""Prevent Feishu callback credentials from entering Uvicorn access logs."""

from __future__ import annotations

from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from app.contexts.foundations.identity.browser_login import CALLBACK_PATH


class OAuthCallbackQueryScrubMiddleware:
    """Capture the callback fields in-memory, then remove its query from ASGI logging.

    Uvicorn formats access logs from ``scope['query_string']`` when the response
    starts.  OAuth authorization codes must not be written there.  The endpoint
    reads only the captured ``code``, ``state``, and ``error`` values.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == CALLBACK_PATH:
            raw_query = scope.get("query_string", b"")
            captured: dict[str, str] = {}
            if isinstance(raw_query, bytes) and len(raw_query) <= 4096:
                try:
                    parsed = parse_qs(
                        raw_query.decode("ascii"),
                        keep_blank_values=True,
                        max_num_fields=8,
                    )
                    for key in ("code", "state", "error"):
                        values = parsed.get(key)
                        if values:
                            if len(values) != 1:
                                captured = {}
                                break
                            captured[key] = values[0]
                except (UnicodeDecodeError, ValueError):
                    captured = {}
            state = scope.setdefault("state", {})
            state["feishu_oauth_query"] = captured
            scope["query_string"] = b""
        await self.app(scope, receive, send)
