"""Meeting HTTP adapter and canonical entrypoint boundary tests."""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import meetings as meeting_routes
from app.contexts.business.meeting_management.application.contracts import ResolutionResult
from app.contexts.foundations.identity.contracts import PrincipalType
from app.models.system import SysUser

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


def test_http_route_uses_meeting_context_instead_of_legacy_business_modules() -> None:
    imports = _runtime_imports(ROOT / "app" / "api" / "v1" / "meetings.py")
    assert not {
        module
        for module in imports
        if module == "app.models"
        or module.startswith("app.models.")
        or module == "app.services"
        or module.startswith("app.services.")
    }


def test_zero_caller_meeting_facades_are_removed() -> None:
    assert not (ROOT / "app" / "services" / "meeting_service.py").exists()
    assert not (ROOT / "app" / "services" / "meeting_ai_actions.py").exists()


async def test_confirm_route_passes_human_principal_and_keeps_audit_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id = uuid.uuid4()
    resolution_id = uuid.uuid4()
    result = ResolutionResult(
        id=resolution_id,
        content="确认执行方案",
        owner_id=None,
        due_date=None,
        is_confirmed=True,
        confirmed_by=actor_id,
        converted_task_id=None,
        create_time=datetime(2026, 7, 23, 12, tzinfo=UTC),
    )
    captured: dict[str, object] = {}

    async def fake_confirm(*args: object, **kwargs: object) -> ResolutionResult:
        captured["principal"] = kwargs["principal"]
        return result

    async def fake_audit(*args: object, **kwargs: object) -> None:
        captured["audit"] = args[1]

    monkeypatch.setattr(meeting_routes.operations, "confirm_resolution", fake_confirm)
    monkeypatch.setattr(meeting_routes, "append_audit_record", fake_audit)
    manager = SysUser(
        id=actor_id,
        username="manager",
        password_hash="x",
        role_code="executive",
    )

    response = await meeting_routes.confirm_resolution(
        resolution_id,
        cast(AsyncSession, object()),
        manager,
    )

    principal = captured["principal"]
    assert principal.principal_type is PrincipalType.USER
    assert principal.principal_id == actor_id
    audit = captured["audit"]
    assert audit.action == "meeting.resolution.confirm"
    assert audit.target_id == resolution_id
    assert response["code"] == 0
    assert response["data"]["is_confirmed"] is True
