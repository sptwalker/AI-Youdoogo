"""Static guardrails for the DDD modular-monolith package structure."""

from __future__ import annotations

import ast
from pathlib import Path

from app.contexts.foundations.integration.governed_data_query import check_sql
from app.core import database as legacy_database
from app.models import base as legacy_model_base
from app.models import workflow as legacy_workflow_models
from app.platform import database as platform_database
from app.platform.outbox import model as outbox_model
from app.platform.outbox import repository as outbox_repository
from app.services import outbox_service, sql_guard

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _imports(path: Path) -> set[str]:
    """Return absolute import module names used by one Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    """Collect forbidden imports with stable repo-relative diagnostics."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for imported in sorted(_imports(path)):
            if imported.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    return violations


def test_platform_does_not_depend_on_business_code() -> None:
    """Technical mechanisms must remain reusable without any bounded context."""
    forbidden = (
        "app.contexts",
        "app.api",
        "app.services",
        "app.models",
        "app.agents",
        "app.knowledge",
        "app.llm",
        "app.integrations",
    )
    assert _violations(APP / "platform", forbidden) == []


def test_context_application_does_not_import_outer_layers() -> None:
    """Application policy may use pure libraries but not delivery or persistence details."""
    application_roots = [
        path for path in (APP / "contexts").rglob("application") if path.is_dir()
    ]
    forbidden = (
        "app.api",
        "app.bootstrap",
        "app.core.database",
        "app.models",
        "app.services",
        "app.platform",
        "fastapi",
        "sqlalchemy",
        "redis",
        "httpx",
        "minio",
    )
    violations = [
        violation
        for application_root in application_roots
        for violation in _violations(application_root, forbidden)
    ]
    assert violations == []


def test_context_domain_does_not_import_framework_or_outer_layers() -> None:
    """Domain errors and rules must remain independent from delivery and persistence."""
    domain_roots = [path for path in (APP / "contexts").rglob("domain") if path.is_dir()]
    forbidden = (
        "app.api",
        "app.bootstrap",
        "app.core",
        "app.models",
        "app.services",
        "app.platform",
        "fastapi",
        "sqlalchemy",
        "redis",
        "httpx",
        "minio",
    )
    violations = [
        violation
        for domain_root in domain_roots
        for violation in _violations(domain_root, forbidden)
    ]
    assert violations == []


def test_shared_kernel_is_transport_and_framework_agnostic() -> None:
    """Cross-context failure categories must remain a tiny dependency-free contract."""
    forbidden = (
        "app.api",
        "app.bootstrap",
        "app.core",
        "app.models",
        "app.services",
        "app.platform",
        "fastapi",
        "sqlalchemy",
        "redis",
        "httpx",
        "minio",
    )
    assert _violations(APP / "contexts" / "shared_kernel", forbidden) == []


def test_bootstrap_owns_composition_and_main_is_only_a_facade() -> None:
    """The stable ASGI path must not regain route or infrastructure wiring."""
    assert _imports(APP / "main.py") == {"app.bootstrap.app"}
    assert (APP / "bootstrap" / "app.py").exists()
    assert (APP / "bootstrap" / "lifecycle.py").exists()
    assert (APP / "bootstrap" / "wiring.py").exists()


def test_legacy_facades_preserve_public_object_identity() -> None:
    """Incremental migration keeps old imports working without duplicate implementations."""
    assert legacy_database.engine is platform_database.engine
    assert legacy_database.async_session_factory is platform_database.async_session_factory
    assert legacy_model_base.Base is platform_database.Base
    assert legacy_workflow_models.OutboxEvent is outbox_model.OutboxEvent
    assert outbox_service.enqueue is outbox_repository.enqueue
    assert outbox_service.claim_next is outbox_repository.claim_next
    assert sql_guard.check_sql is check_sql


def test_proposal_service_uses_context_errors_instead_of_shared_generic_errors() -> None:
    """The migrated proposal slice must keep its domain-specific failure language."""
    imports = _imports(APP / "services" / "proposal_service.py")
    assert "app.contexts.shared_kernel" not in imports
    assert "app.contexts.business.proposal_management" in imports


def test_legacy_error_facades_are_fully_removed() -> None:
    """No runtime module may regain the deleted transport-shaped error API."""
    assert not (APP / "core" / "application_error.py").exists()
    assert not (APP / "core" / "exceptions.py").exists()
    violations = []
    runtime_roots = (APP, ROOT / "scripts")
    for runtime_root in runtime_roots:
        for path in sorted(runtime_root.rglob("*.py")):
            for imported in _imports(path):
                if imported in {"app.core.application_error", "app.core.exceptions"}:
                    violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []
