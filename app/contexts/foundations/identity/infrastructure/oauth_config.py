"""Feishu OAuth configuration and input validation owned by Identity."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.feishu.oauth import FeishuOAuthConfig

PRODUCTION_REDIRECT_URL = "https://ai.youdoogo.com/api/v1/auth/feishu/callback"
CALLBACK_PATH = "/api/v1/auth/feishu/callback"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
VISIBLE_OAUTH_VALUE = re.compile(r"^[\x21-\x7e]+$")
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class OAuthUnavailable(Exception):
    """OAuth is disabled, misconfigured, or its state store is unavailable."""


class InvalidOAuthState(Exception):
    """OAuth state is absent, expired, replayed, tampered with, or unbound."""


class InvalidReturnTo(Exception):
    """A return path is not a same-origin local application path."""


class InvalidOAuthCallback(Exception):
    """The callback does not contain a valid authorization code."""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def load_oauth_config() -> FeishuOAuthConfig:
    """Load and validate OAuth configuration without affecting app startup."""
    settings = get_settings()
    if not _as_bool(runtime_config.effective("feishu_oauth_enabled", False)):
        raise OAuthUnavailable
    app_id = str(runtime_config.effective("feishu_app_id", "") or "")
    app_secret = str(runtime_config.effective("feishu_app_secret", "") or "")
    redirect_url = str(runtime_config.effective("feishu_redirect_url", "") or "")
    if (
        not 1 <= len(app_id) <= 128
        or VISIBLE_OAUTH_VALUE.fullmatch(app_id) is None
        or not 1 <= len(app_secret) <= 512
        or VISIBLE_OAUTH_VALUE.fullmatch(app_secret) is None
    ):
        raise OAuthUnavailable

    try:
        parsed = urlsplit(redirect_url)
    except ValueError as exc:
        raise OAuthUnavailable from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != CALLBACK_PATH
    ):
        raise OAuthUnavailable
    if settings.app_env != "local":
        if redirect_url != PRODUCTION_REDIRECT_URL:
            raise OAuthUnavailable
    else:
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "test",
        }
        if parsed.scheme != "https" and not local_http:
            raise OAuthUnavailable
    if not parsed.hostname:
        raise OAuthUnavailable
    try:
        _ = parsed.port
    except ValueError as exc:
        raise OAuthUnavailable from exc
    return FeishuOAuthConfig(
        app_id=app_id,
        app_secret=app_secret,
        redirect_url=redirect_url,
        secure_cookies=parsed.scheme == "https",
    )


def normalize_return_to(raw: str | None) -> str:
    """Accept only same-origin local absolute paths."""
    if raw is None or raw == "":
        return "/"
    if len(raw) > 2048:
        raise InvalidReturnTo
    decoded = unquote(raw)
    if any(ord(char) < 32 for char in decoded) or "\\" in decoded:
        raise InvalidReturnTo
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise InvalidReturnTo from exc
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not decoded_path.startswith("/")
        or decoded_path.startswith("//")
    ):
        raise InvalidReturnTo
    return parsed.geturl()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
