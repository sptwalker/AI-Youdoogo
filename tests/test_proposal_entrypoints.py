"""Proposal HTTP/facade compatibility after switching to the Context slice."""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import proposals as proposal_routes
from app.contexts.business.proposal_management.application.contracts import ProposalResult
from app.models.system import SysUser
from app.schemas.proposal import ProposalCreate

ROOT = Path(__file__).resolve().parents[1]


def _runtime_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_http_route_no_longer_imports_legacy_proposal_collaborators() -> None:
    imports = _runtime_imports(ROOT / "app" / "api" / "v1" / "proposals.py")
    assert "app.services" not in imports
    assert "app.models.proposal" not in imports
    assert "app.models.task" not in imports


def test_retired_proposal_facade_is_removed() -> None:
    assert not (ROOT / "app" / "services" / "proposal_service.py").exists()


async def test_create_route_preserves_success_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    creator_id = uuid.uuid4()
    result = ProposalResult(
        id=uuid.uuid4(),
        code="PROP-HTTP0001",
        title="HTTP 提案",
        department_id=None,
        background="背景",
        plan="方案",
        benefit_risk=None,
        priority="normal",
        status="draft",
        creator_id=creator_id,
        converted_task_id=None,
        create_time=datetime(2026, 7, 23, 12, tzinfo=UTC),
    )

    async def _create(*args: object, **kwargs: object) -> ProposalResult:
        return result

    monkeypatch.setattr(proposal_routes.operations, "create_proposal", _create)
    user = SysUser(
        id=creator_id,
        username="member",
        password_hash="x",
        role_code="member",
    )

    response = await proposal_routes.create_proposal(
        ProposalCreate(title="HTTP 提案", background="背景", plan="方案"),
        cast(AsyncSession, object()),
        user,
    )

    assert response["code"] == 0
    assert response["msg"] == "ok"
    assert response["data"]["code"] == "PROP-HTTP0001"
    assert response["data"]["status"] == "draft"
