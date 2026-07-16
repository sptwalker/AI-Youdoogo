"""Feishu user OAuth integration.

This module is deliberately separate from :mod:`client`, whose tenant token is
used by notifications and data integrations.  Login uses Feishu's current
OAuth v3 user token endpoint and never treats a tenant token as a browser
identity.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTHORIZATION_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"
USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"
_OPEN_ID = re.compile(r"^ou[-_][A-Za-z0-9_-]+$")


class FeishuOAuthError(Exception):
    """A safe, non-leaky Feishu OAuth failure."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"Feishu OAuth {stage} failed")


@dataclass(frozen=True)
class FeishuOAuthConfig:
    """Validated runtime configuration for one OAuth transaction."""

    app_id: str
    app_secret: str
    redirect_url: str
    secure_cookies: bool


@dataclass(frozen=True)
class FeishuIdentity:
    """Identity returned by Feishu's user-authorized flow."""

    open_id: str


def pkce_challenge(code_verifier: str) -> str:
    """Return an RFC 7636 S256 challenge without padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class FeishuOAuthClient:
    """Small, bounded-time client for Feishu user OAuth only."""

    def __init__(self, config: FeishuOAuthConfig) -> None:
        self.config = config
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    def authorization_url(self, state: str, code_challenge: str) -> str:
        """Build the current Feishu authorization URL with PKCE."""
        params = {
            "client_id": self.config.app_id,
            "response_type": "code",
            "redirect_uri": self.config.redirect_url,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTHORIZATION_URL}?{urlencode(params)}"

    async def identity_from_code(self, code: str, code_verifier: str) -> FeishuIdentity:
        """Exchange an authorization code and fetch the authorized user's identity.

        The returned user access token is held only for this request and is not
        persisted, logged, returned to the browser, or used as an app tenant
        token.
        """
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            access_token = await self._exchange_code(client, code, code_verifier)
            return await self._fetch_identity(client, access_token)

    async def _exchange_code(
        self, client: httpx.AsyncClient, code: str, code_verifier: str
    ) -> str:
        body = {
            "grant_type": "authorization_code",
            "client_id": self.config.app_id,
            "client_secret": self.config.app_secret,
            "code": code,
            "redirect_uri": self.config.redirect_url,
            "code_verifier": code_verifier,
        }
        try:
            response = await client.post(
                TOKEN_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
            )
        except httpx.RequestError as exc:
            raise FeishuOAuthError("token exchange request") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise FeishuOAuthError("token exchange HTTP response")
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise FeishuOAuthError("token exchange response") from exc
        if not isinstance(payload, dict):
            raise FeishuOAuthError("token exchange response")
        data: dict[str, Any] = payload
        if data.get("code") != 0 or not isinstance(data.get("access_token"), str):
            raise FeishuOAuthError("token exchange rejected")
        access_token = data["access_token"]
        if not access_token or len(access_token) > 4096:
            raise FeishuOAuthError("token exchange response")
        return access_token

    async def _fetch_identity(self, client: httpx.AsyncClient, access_token: str) -> FeishuIdentity:
        try:
            response = await client.get(
                USER_INFO_URL,
                headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            )
        except httpx.RequestError as exc:
            raise FeishuOAuthError("user identity request") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise FeishuOAuthError("user identity HTTP response")
        try:
            data: dict[str, Any] = response.json()
            user_data = data.get("data")
        except (ValueError, AttributeError) as exc:
            raise FeishuOAuthError("user identity response") from exc
        if data.get("code") != 0 or not isinstance(user_data, dict):
            raise FeishuOAuthError("user identity rejected")
        open_id = user_data.get("open_id")
        if (
            not isinstance(open_id, str)
            or not 8 <= len(open_id) <= 128
            or _OPEN_ID.fullmatch(open_id) is None
        ):
            raise FeishuOAuthError("user identity response")
        return FeishuIdentity(open_id=open_id)
