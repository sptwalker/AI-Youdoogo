"""HttpReleasePublisher.publish 发布推送契约（Module 2 / docs/23 §4.2）。

离线 ASGITransport 假 expert ``/releases`` 端点 + 私钥自签（真 mint→真 verify）；覆盖 publish 全体：
body 六字段 + 路径 expert_id + Bearer 是 aud=专家平台 scope=expert:publish 的真 JWT + ≥400 抛
RuntimeError（此前离线套件仅到构造，58-75 未覆盖）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.contexts.foundations.workforce.expert_management.domain.models import ExpertRelease
from app.contexts.foundations.workforce.expert_management.infrastructure.release_publisher import (
    HttpReleasePublisher,
)
from app.core.config import get_settings
from app.core.internal_token import verify_internal_token


@pytest.fixture(autouse=True)
def _internal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setattr(get_settings(), "internal_jwt_private_key", pem)


def _release() -> ExpertRelease:
    return ExpertRelease(
        id=uuid.uuid4(),
        expert_id=uuid.uuid4(),
        version_no=3,
        prompt_template="模板",
        model_role="daily",
        permission_scope_json="{}",
        tools_json="[]",
        duty=None,
        released_by=uuid.uuid4(),
        released_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _publisher(status: int) -> tuple[HttpReleasePublisher, dict[str, object], httpx.AsyncClient]:
    captured: dict[str, object] = {}
    fake = FastAPI()

    # body 直接收 dict（FastAPI 解析 JSON 体）；request 取 Authorization（Request 在模块 globals，
    # `from __future__ import annotations` 下字符串注解可解析）。
    @fake.post("/v1/experts/{expert_id}/releases")
    async def releases(expert_id: str, body: dict, request: Request) -> JSONResponse:
        captured["expert_id"] = expert_id
        captured["body"] = body
        captured["auth"] = request.headers.get("Authorization")
        return JSONResponse({}, status_code=status)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=fake), base_url="http://expert")
    return HttpReleasePublisher(base_url="http://expert", client=client), captured, client


async def test_publish_sends_snapshot_with_publish_token() -> None:
    publisher, captured, client = _publisher(200)
    release = _release()

    await publisher.publish(release)

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["release_id"] == str(release.id)
    assert body["version_no"] == 3
    assert body["prompt_template"] == "模板"
    assert body["model_role"] == "daily"
    assert body["released_by"] == str(release.released_by)
    assert body["released_at"] == release.released_at.isoformat()
    assert captured["expert_id"] == str(release.expert_id)
    # Bearer 是特权发布令牌：aud=专家平台、scope 含 expert:publish（与 execute 分离）。
    token = str(captured["auth"]).removeprefix("Bearer ")
    claims = verify_internal_token(token, audience="ai-expert-platform")
    assert "expert:publish" in claims.scope
    await client.aclose()


async def test_publish_raises_on_error_status() -> None:
    publisher, _, client = _publisher(500)
    with pytest.raises(RuntimeError):
        await publisher.publish(_release())
    await client.aclose()
