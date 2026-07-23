"""Focused checks for thin Knowledge, Semantic, and Ops Data HTTP adapters."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.v1 import ops_data
from app.contexts.foundations.governance.audit_trail import public as audit_public
from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    QueryAuditEvidence,
)
from app.contexts.foundations.integration.governed_data_query.contracts import (
    GovernedQueryRequest,
    GovernedQueryResult,
)
from app.contexts.foundations.integration.governed_data_query.infrastructure.audit_adapter import (
    PublishedAuditEvidenceAdapter,
)

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (
    ROOT / "app/api/v1/knowledge.py",
    ROOT / "app/api/v1/semantic.py",
    ROOT / "app/api/v1/ops_data.py",
)


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_routes_depend_on_published_boundaries_not_concrete_implementations() -> None:
    forbidden_prefixes = (
        "app.models",
        "app.services",
        "app.agents",
        "app.knowledge",
        "app.llm",
    )
    violations = [
        f"{route.name} -> {dependency}"
        for route in ROUTES
        for dependency in sorted(_imports(route))
        if dependency.startswith(forbidden_prefixes)
        or (
            dependency.startswith("app.contexts.")
            and ".infrastructure" in dependency
        )
    ]
    assert violations == []


async def test_ops_query_route_passes_only_plain_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_id = uuid.uuid4()
    session = object()
    captured: list[object] = []

    async def fake_run_query(received_session: object, request: object) -> GovernedQueryResult:
        captured.extend((received_session, request))
        return GovernedQueryResult(status="ok", row_count=0)

    monkeypatch.setattr(ops_data.governed_query, "run_query", fake_run_query)

    response = await ops_data.run_query(
        ops_data.SqlQuery(sql="select * from v_event_4"),
        session,  # type: ignore[arg-type]
        SimpleNamespace(id=actor_id, role_code="admin"),
    )

    assert captured[0] is session
    request = captured[1]
    assert isinstance(request, GovernedQueryRequest)
    assert request.sql == "select * from v_event_4"
    assert request.actor_id == actor_id
    assert request.actor_role == "admin"
    assert request.source == "manual"
    assert response == {
        "code": 0,
        "msg": "ok",
        "data": {
            "status": "ok",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
        },
    }


async def test_published_audit_adapter_maps_query_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    actor_id = uuid.uuid4()
    recorded: list[tuple[object, audit_public.AppendAuditRecordCommand]] = []

    async def fake_append(
        received_session: object,
        command: audit_public.AppendAuditRecordCommand,
    ) -> None:
        recorded.append((received_session, command))

    monkeypatch.setattr(audit_public, "append_audit_record", fake_append)
    adapter = PublishedAuditEvidenceAdapter(session)  # type: ignore[arg-type]
    await adapter.record(
        QueryAuditEvidence(
            actor_id=actor_id,
            actor_role="admin",
            sql="select event_name from v_event_4 limit 10",
            source="manual",
            result="ok",
            detail={"row_count": 2},
        )
    )

    received_session, command = recorded[0]
    assert received_session is session
    assert command.actor_id == actor_id
    assert command.action == "data.query"
    assert command.result == "ok"
    assert command.detail == {
        "sql": "select event_name from v_event_4 limit 10",
        "source": "manual",
        "row_count": 2,
    }
