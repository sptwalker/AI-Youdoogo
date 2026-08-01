"""Release 发布推送 HTTP 实现（Module 2 / docs/23 §4.2）。

发布后把冻结快照 POST 到远端 ``/v1/experts/{id}/releases``（远端存内存快照供 ``_prepare`` 组装）。
令牌：``mint_internal_token(aud=ai-expert-platform, scope=expert:publish)``——特权写与 execute
分离（least-privilege）；私钥只在本服务。日志红线（§5）：只记状态码，不打印 Authorization /
prompt_template 明文。失败抛错，由 ``publish_release`` 调用点 log+swallow（youdoo 真源，尽力而为）。
"""

from __future__ import annotations

import httpx

from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertRelease,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_EXPERT_AUDIENCE = "ai-expert-platform"
_SCHEMA_VERSION = "v1"


class HttpReleasePublisher:
    """Push a frozen release snapshot to the remote expert platform."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        tenant_key: str = "youdoogo",
        caller_service: str = "ai-youdoogo",
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url.rstrip("/")
        self._client = client  # 可注入（离线测试）；None → 每次现开一次性 client
        self._tenant_key = tenant_key
        self._caller_service = caller_service
        self._timeout = settings.expert_platform_timeout if timeout is None else timeout

    def _headers(self) -> dict[str, str]:
        token = mint_internal_token(
            service_id="ai-youdoogo",
            audience=_EXPERT_AUDIENCE,
            scope=("expert:publish",),
        )
        return {
            "Authorization": f"Bearer {token}",
            "X-Request-ID": get_trace_id(),
            "X-Tenant-Key": self._tenant_key,
            "X-Caller-Service": self._caller_service,
            "X-Schema-Version": _SCHEMA_VERSION,
            "Content-Type": "application/json",
        }

    async def publish(self, release: ExpertRelease) -> None:
        body: dict[str, object] = {
            "release_id": str(release.id),
            "version_no": release.version_no,
            "prompt_template": release.prompt_template,
            "model_role": release.model_role,
            "released_by": str(release.released_by) if release.released_by else None,
            "released_at": release.released_at.isoformat(),
        }
        path = f"{self._base_url}/v1/experts/{release.expert_id}/releases"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(path, json=body, headers=self._headers())
        finally:
            if self._client is None:
                await client.aclose()
        if resp.status_code >= 400:
            raise RuntimeError(f"专家平台发布返回 {resp.status_code}")
