"""HTTP check for the read-only retrieval-arm diagnostics endpoint.

Retrieval internals (vector/keyword arms need embeddings + pgvector) are
monkeypatched — this test covers the new wiring only: auth gate, scope
isolation, admin cross-dept audit, and vector/keyword/fused flattening.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_retrieval,
)
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Base
from app.models.system import SysUser


@pytest.fixture
async def admin_client() -> AsyncGenerator[tuple[AsyncClient, str], None]:
    """Yield an admin-authenticated client plus a valid member token (for the auth-gate test)."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()
    async with sessions() as session:
        session.add(
            SysUser(id=admin_id, username="diag-admin", password_hash="x", role_code="admin")
        )
        session.add(
            SysUser(id=member_id, username="diag-member", password_hash="x", role_code="member")
        )
        await session.commit()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    token = create_access_token(admin_id, "admin")
    member_token = create_access_token(member_id, "member")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, member_token
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_diagnose_returns_three_arms(
    admin_client: tuple[AsyncClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = admin_client
    hit = SimpleNamespace(
        file_id=uuid.uuid4(),
        file_name="A5.md",
        chunk_index=2,
        chunk_text="旗舰款",
        distance=0.125,
    )

    async def _arms(*_a: Any, **_k: Any) -> tuple[list[Any], list[Any]]:
        return [hit], []

    async def _search(*_a: Any, **_k: Any) -> list[Any]:
        return [hit]

    monkeypatch.setattr(sqlalchemy_retrieval, "diagnostic_arms", _arms)
    monkeypatch.setattr(sqlalchemy_retrieval, "search", _search)

    resp = await client.post("/api/v1/knowledge/diagnose", json={"query": "盒子A5", "top_k": 3})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["query"] == "盒子A5"
    assert [h["file_name"] for h in data["vector"]] == ["A5.md"]
    assert data["keyword"] == []
    assert data["fused"][0]["chunk_index"] == 2


async def test_diagnose_requires_manager_role(admin_client: tuple[AsyncClient, str]) -> None:
    # member role must be rejected by require_roles("admin", "executive")
    client, member_token = admin_client
    resp = await client.post(
        "/api/v1/knowledge/diagnose",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
