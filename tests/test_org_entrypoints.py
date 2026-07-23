"""Organization HTTP adapter and remaining facade boundary tests."""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import org as org_routes
from app.contexts.foundations.organization_structure.contracts import DepartmentSnapshot
from app.models.system import SysUser
from app.schemas.org import NodeCreate

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


def test_org_route_has_no_legacy_service_or_orm_imports() -> None:
    imports = _runtime_imports(ROOT / "app" / "api" / "v1" / "org.py")
    assert not {
        module
        for module in imports
        if module == "app.models"
        or module.startswith("app.models.")
        or module == "app.services"
        or module.startswith("app.services.")
    }


def test_org_facades_do_not_own_queries_transactions_or_models() -> None:
    for name in ("org_service.py", "org_sync_service.py"):
        source = (ROOT / "app" / "services" / name).read_text(encoding="utf-8")
        assert ".commit(" not in source
        assert ".rollback(" not in source
        assert "select(" not in source
        assert "app.models" not in source
    assert not (ROOT / "app" / "services" / "org_template.py").exists()

    adapters = (
        ROOT
        / "app"
        / "contexts"
        / "foundations"
        / "organization_structure"
        / "infrastructure"
        / "adapters.py"
    ).read_text(encoding="utf-8")
    assert "app.models.discussion" not in adapters
    assert "Temporary Group Messaging adapter" not in adapters


async def test_create_node_delegates_to_context_and_preserves_audit_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    department_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    snapshot = DepartmentSnapshot(
        department_id=department_id,
        version="v1",
        name="研发部",
        code="rd",
        node_type="dept_l1",
        level=1,
        path=f"/{department_id}/",
        parent_id=uuid.uuid4(),
        supervisor_user_id=None,
        sort_order=1,
        create_time=datetime(2026, 7, 23, tzinfo=UTC),
    )
    captured: dict[str, object] = {}

    async def fake_create(*args: object, **kwargs: object) -> DepartmentSnapshot:
        captured["create"] = kwargs
        return snapshot

    async def fake_audit(*args: object, **kwargs: object) -> None:
        captured["audit"] = args[1]

    monkeypatch.setattr(org_routes.operations, "create_department", fake_create)
    monkeypatch.setattr(org_routes, "append_audit_record", fake_audit)
    admin = SysUser(
        id=actor_id,
        username="admin",
        password_hash="x",
        role_code="admin",
    )

    response = await org_routes.create_node(
        NodeCreate(name="研发部", parent_id=cast(uuid.UUID, snapshot.parent_id), code="rd"),
        cast(AsyncSession, object()),
        admin,
    )

    assert captured["create"]["name"] == "研发部"
    audit = captured["audit"]
    assert audit.action == "org.node.create"
    assert audit.target_id == department_id
    assert response["code"] == 0
    assert response["data"]["id"] == str(department_id)


async def test_sync_route_uses_published_operation_and_audits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    async def fake_sync(*args: object, **kwargs: object) -> dict[str, int]:
        return {"departments": 2, "users_created": 1, "users_updated": 3}

    async def fake_audit(*args: object, **kwargs: object) -> None:
        captured.append(args[1])

    monkeypatch.setattr(org_routes.operations, "sync_from_feishu", fake_sync)
    monkeypatch.setattr(org_routes, "append_audit_record", fake_audit)
    admin = SysUser(
        id=uuid.uuid4(),
        username="admin",
        password_hash="x",
        role_code="admin",
    )

    response = await org_routes.sync_feishu(cast(AsyncSession, object()), admin)

    assert len(captured) == 1
    assert captured[0].action == "org.sync_feishu"
    assert response == {
        "code": 0,
        "msg": "ok",
        "data": {"departments": 2, "users_created": 1, "users_updated": 3},
    }
