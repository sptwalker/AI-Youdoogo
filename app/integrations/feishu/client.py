"""Feishu tenant-token client for messaging, documents, and organization data."""

from __future__ import annotations

import asyncio
import json
import time
from types import TracebackType
from typing import Any, Self, TypeVar
from urllib.parse import urlencode

import httpx


class FeishuAPIError(Exception):
    """Feishu API request or response error."""


class FeishuAuthError(FeishuAPIError):
    """Feishu tenant authentication error."""


_FeishuError = TypeVar("_FeishuError", bound=FeishuAPIError)


class FeishuClient:
    """Own Feishu HTTP lifecycle, tenant authentication, and API operations."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._tenant_token: str | None = None
        self._tenant_token_expire_at = 0.0
        self._tenant_cred_key: str | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @staticmethod
    def _creds() -> tuple[str, str]:
        from app.core import runtime_config

        return (
            str(runtime_config.effective("feishu_app_id", "") or ""),
            str(runtime_config.effective("feishu_app_secret", "") or ""),
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _json_object(
        response: httpx.Response, error_type: type[_FeishuError], context: str
    ) -> dict[str, Any]:
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise error_type(f"Invalid JSON response {context}") from exc
        if not isinstance(payload, dict):
            raise error_type(f"Invalid response object {context}")
        return payload

    @classmethod
    def _api_data(cls, response: httpx.Response, context: str) -> dict[str, Any]:
        payload = cls._json_object(response, FeishuAPIError, context)
        if payload.get("code") != 0:
            raise FeishuAPIError(f"Feishu API error {context}: {payload.get('msg')}")
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise FeishuAPIError(f"Invalid API data {context}")
        return data

    async def get_tenant_access_token(self) -> str:
        app_id, app_secret = self._creds()
        cred_key = f"{app_id}|{app_secret}"
        now = time.monotonic()
        if (
            self._tenant_token
            and self._tenant_cred_key == cred_key
            and now < self._tenant_token_expire_at
        ):
            return self._tenant_token
        try:
            response = await self._get_client().post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FeishuAuthError(f"HTTP error getting tenant access token: {exc}") from exc
        except httpx.RequestError as exc:
            raise FeishuAPIError(f"Request error getting tenant access token: {exc}") from exc
        data = self._json_object(response, FeishuAuthError, "getting tenant access token")
        if data.get("code") != 0:
            raise FeishuAuthError(f"Failed to get tenant access token: {data.get('msg')}")
        token = data.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuAuthError("Invalid tenant access token response")
        expire = data.get("expire", 7200)
        try:
            if isinstance(expire, bool):
                raise ValueError
            expires_in = int(expire)
        except (TypeError, ValueError) as exc:
            raise FeishuAuthError("Invalid tenant access token expiry") from exc
        self._tenant_token = token
        self._tenant_token_expire_at = now + max(0, expires_in - 60)
        self._tenant_cred_key = cred_key
        return token

    async def _request_authed(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        try:
            response = await self._get_client().request(
                method,
                f"{self.BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    **({"Content-Type": "application/json; charset=utf-8"} if json_body else {}),
                },
                params=params,
                json=json_body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FeishuAPIError(f"HTTP error on {method} {path}: {exc}") from exc
        except httpx.RequestError as exc:
            raise FeishuAPIError(f"Request error on {method} {path}: {exc}") from exc
        return self._api_data(response, f"on {method} {path}")

    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: dict[str, Any],
        receive_id_type: str = "user_id",
    ) -> dict[str, Any]:
        return await self._request_authed(
            "POST",
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
        )

    async def send_text(
        self, receive_id: str, text: str, receive_id_type: str = "user_id"
    ) -> dict[str, Any]:
        return await self.send_message(receive_id, "text", {"text": text}, receive_id_type)

    async def send_card(
        self, receive_id: str, card: dict[str, Any], receive_id_type: str = "user_id"
    ) -> dict[str, Any]:
        return await self.send_message(receive_id, "interactive", card, receive_id_type)

    async def create_document(self, title: str) -> str:
        data = await self._request_authed(
            "POST", "/docx/v1/documents", json_body={"title": title[:800]}
        )
        document_id = data.get("document", {}).get("document_id")
        if not document_id:
            raise FeishuAPIError("create_document 未返回 document_id")
        return str(document_id)

    @staticmethod
    def _run(content: str, bold: bool = False, color: int | None = None) -> dict[str, Any]:
        run: dict[str, Any] = {"text_run": {"content": content}}
        style = {
            **({"bold": True} if bold else {}),
            **({"text_color": color} if color else {}),
        }
        if style:
            run["text_run"]["text_element_style"] = style
        return run

    @staticmethod
    def text_block(content: str) -> dict[str, Any]:
        return {"block_type": 2, "text": {"elements": [FeishuClient._run(content)]}}

    @staticmethod
    def rich_block(runs: list[tuple[Any, ...]]) -> dict[str, Any]:
        return {
            "block_type": 2,
            "text": {
                "elements": [
                    FeishuClient._run(
                        run[0], run[1] if len(run) > 1 else False, run[2] if len(run) > 2 else None
                    )
                    for run in runs
                ]
            },
        }

    @staticmethod
    def heading_block(content: str, level: int = 1) -> dict[str, Any]:
        return {
            "block_type": {1: 3, 2: 4, 3: 5}.get(level, 3),
            f"heading{level}": {"elements": [FeishuClient._run(content)]},
        }

    async def append_document_blocks(
        self, document_id: str, blocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for offset in range(0, len(blocks), 50):
            last = await self._request_authed(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                json_body={"children": blocks[offset : offset + 50]},
            )
            if offset + 50 < len(blocks):
                await asyncio.sleep(0.4)
        return last

    async def get_document_raw_content(self, document_id: str) -> str:
        return str(
            (
                await self._request_authed("GET", f"/docx/v1/documents/{document_id}/raw_content")
            ).get("content", "")
        )

    async def bitable_list_records(
        self,
        app_token: str,
        table_id: str,
        page_size: int = 100,
        filter_expr: str | None = None,
        max_records: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if filter_expr:
                params["filter"] = filter_expr
            if page_token:
                params["page_token"] = page_token
            data = await self._request_authed(
                "GET", f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params=params
            )
            items.extend(data.get("items") or [])
            if max_records is not None and len(items) >= max_records:
                return items[:max_records]
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return items

    async def bitable_create_record(
        self, app_token: str, table_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request_authed(
            "POST",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": fields},
        )

    async def bitable_update_record(
        self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request_authed(
            "PUT",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            json_body={"fields": fields},
        )

    async def list_departments(
        self, parent_department_id: str = "0", page_size: int = 50
    ) -> list[dict[str, Any]]:
        departments: list[dict[str, Any]] = []

        async def collect_children(department_id: str) -> None:
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {
                    "page_size": page_size,
                    "department_id_type": "open_department_id",
                }
                if page_token:
                    params["page_token"] = page_token
                data = await self._request_authed(
                    "GET", f"/contact/v3/departments/{department_id}/children", params=params
                )
                items = data.get("items") or []
                departments.extend(items)
                for item in items:
                    child_id = item.get("open_department_id")
                    if child_id:
                        await collect_children(child_id)
                page_token = data.get("page_token")
                if not data.get("has_more") or not page_token:
                    return

        await collect_children(parent_department_id)
        return departments

    async def list_users_by_department(
        self, department_id: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "department_id": department_id,
                "page_size": page_size,
                "department_id_type": "open_department_id",
            }
            if page_token:
                params["page_token"] = page_token
            data = await self._request_authed(
                "GET", "/contact/v3/users/find_by_department", params=params
            )
            users.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return users

    def oauth_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        app_id, _ = self._creds()
        return "https://open.feishu.cn/open-apis/authen/v1/authorize?" + urlencode(
            {
                "app_id": app_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": state,
            }
        )

    async def oauth_user_info(self, code: str) -> dict[str, Any]:
        return await self._request_authed(
            "POST",
            "/authen/v1/access_token",
            json_body={"grant_type": "authorization_code", "code": code},
        )


feishu_client = FeishuClient()

__all__ = ["FeishuAPIError", "FeishuAuthError", "FeishuClient", "feishu_client"]
