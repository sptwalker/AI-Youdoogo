"""HTTP compatibility checks for migrated governance, identity, and access routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token
from app.llm import factory
from app.main import app
from app.models import Base
from app.models.sys_config import SysConfig
from app.models.system import SysUser
from app.platform.database import get_db


@pytest.fixture
async def governance_client() -> AsyncGenerator[tuple[AsyncClient, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    admin_id = uuid.uuid4()
    async with sessions() as session:
        session.add(
            SysUser(
                id=admin_id,
                username="governance-admin",
                password_hash="unused",
                role_code="admin",
            )
        )
        session.add(
            SysConfig(
                key="feature_flag",
                value=False,
                value_type="bool",
                category="feature",
            )
        )
        await session.commit()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    token = create_access_token(admin_id, "admin")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, admin_id
    app.dependency_overrides.clear()
    factory.clear_card_providers()
    factory.set_provider_status([], {}, {})
    await engine.dispose()


async def test_config_and_audit_routes_preserve_envelopes(
    governance_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    client, _ = governance_client

    listed = await client.get("/api/v1/configs")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["key"] == "feature_flag"

    updated = await client.patch(
        "/api/v1/configs/feature_flag",
        json={"value": True},
    )
    assert updated.status_code == 200
    assert updated.json()["data"] == {"key": "feature_flag", "value": True}

    logs = await client.get(
        "/api/v1/audit-logs",
        params={"action": "config.update"},
    )
    assert logs.status_code == 200
    body = logs.json()["data"]
    assert body["total"] >= 1
    assert body["items"][0]["action"] == "config.update"


async def test_grant_route_uses_access_control_and_audit_boundaries(
    governance_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    client, _ = governance_client
    resource_id = uuid.uuid4()
    grantee_id = uuid.uuid4()

    created = await client.post(
        "/api/v1/resource-grants",
        json={
            "resource_type": "data_source",
            "resource_id": str(resource_id),
            "grantee_type": "user",
            "grantee_id": str(grantee_id),
            "perm": "write",
        },
    )
    assert created.status_code == 200
    grant_id = created.json()["data"]["id"]

    listed = await client.get("/api/v1/resource-grants")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["perm"] == "write"

    revoked = await client.delete(f"/api/v1/resource-grants/{grant_id}")
    assert revoked.status_code == 200


async def test_ai_provider_and_eval_crud_routes_use_context_operations(
    governance_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    client, _ = governance_client

    provider = await client.post(
        "/api/v1/ai-providers",
        json={
            "name": "测试卡片",
            "tier": "daily",
            "base_url": "https://example.test",
            "api_key": "secret-1234",
            "model": "test-model",
        },
    )
    assert provider.status_code == 200
    provider_id = provider.json()["data"]["id"]

    providers = await client.get("/api/v1/ai-providers")
    assert providers.status_code == 200
    assert providers.json()["data"][0]["api_key_hint"] == "****1234"
    assert "api_key" not in providers.json()["data"][0]

    toggled = await client.post(
        f"/api/v1/ai-providers/{provider_id}/toggle",
        json={"active": False},
    )
    assert toggled.status_code == 200
    assert toggled.json()["data"]["is_active"] is False

    case = await client.post(
        "/api/v1/eval/cases",
        json={"name": "准确性", "input_text": "请回答", "rubric": "准确"},
    )
    assert case.status_code == 200
    case_id = case.json()["data"]["id"]

    cases = await client.get("/api/v1/eval/cases")
    assert cases.status_code == 200
    assert cases.json()["data"][0]["name"] == "准确性"

    deleted = await client.delete(f"/api/v1/eval/cases/{case_id}")
    assert deleted.status_code == 200
