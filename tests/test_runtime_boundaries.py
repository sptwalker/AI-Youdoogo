"""Static regression checks for modular runtime dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

from app.agents import skill_registry, skills, tool_dispatcher
from app.services import (
    orchestration_service,
    workflow_projection,
    workflow_repository,
    workflow_service,
    workflow_state,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
RUNTIME_MODULES = {
    "app.agents.base",
    "app.agents.contracts",
    "app.agents.legacy_skill_adapters",
    "app.agents.skill_registry",
    "app.agents.skills",
    "app.agents.tool_dispatcher",
    "app.agents.workflow_engine",
    "app.services.legacy_orchestration",
    "app.services.orchestration_service",
    "app.services.workflow_event_handler",
    "app.services.workflow_planning",
    "app.services.workflow_projection",
    "app.services.workflow_recovery",
    "app.services.workflow_repository",
    "app.services.workflow_service",
    "app.services.workflow_state",
    "app.services.workflow_step_executor",
    "app.services.workflow_worker",
}


def _path(module: str) -> Path:
    return ROOT.joinpath(*module.split(".")).with_suffix(".py")


def _imports(module: str) -> set[str]:
    tree = ast.parse(_path(module).read_text(encoding="utf-8"))
    known = {
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in APP.rglob("*.py")
    }
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name in known)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in known:
                found.add(node.module)
            found.update(
                child
                for alias in node.names
                if (child := f"{node.module}.{alias.name}") in known
            )
    return found


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> list[str] | None:
        if module in visiting:
            start = visiting.index(module)
            return [*visiting[start:], module]
        if module in visited:
            return None
        visiting.append(module)
        for dependency in graph[module]:
            cycle = visit(dependency)
            if cycle:
                return cycle
        visiting.pop()
        visited.add(module)
        return None

    for module in sorted(graph):
        cycle = visit(module)
        if cycle:
            return cycle
    return None


def test_runtime_modules_are_acyclic() -> None:
    graph = {
        module: _imports(module) & RUNTIME_MODULES for module in RUNTIME_MODULES
    }
    assert _find_cycle(graph) is None


def test_workflow_and_skill_facades_preserve_public_exports() -> None:
    assert workflow_service.create_workflow is workflow_repository.create_workflow
    assert workflow_service.progress is workflow_projection.progress
    assert workflow_service.claim_step_result is workflow_state.claim_step_result
    assert skills.REGISTRY is skill_registry.REGISTRY
    assert skills.ToolDispatcher is tool_dispatcher.ToolDispatcher
    assert orchestration_service.PlanStep.__module__ == "app.services.workflow_planning"


def test_skill_services_depend_on_contracts_not_agent_base() -> None:
    for module in (
        "app.services.collab_protocol",
        "app.services.deliver_service",
        "app.services.query_skill",
    ):
        imports = _imports(module)
        assert "app.agents.contracts" in imports
        assert "app.agents.base" not in imports


def test_langgraph_planner_boundary_cannot_bypass_durable_runtime() -> None:
    planner_imports = _imports("app.services.workflow_planning")
    assert not planner_imports & {
        "app.services.outbox_service",
        "app.services.tool_execution_service",
        "app.services.workflow_repository",
        "app.services.workflow_state",
        "app.services.workflow_worker",
    }
    assert "app.services.workflow_planning" not in _imports(
        "app.services.workflow_step_executor"
    )
    engine_source = _path("app.agents.workflow_engine").read_text(encoding="utf-8")
    assert "workflow_service.create_workflow" in engine_source
    assert "workflow_service.accept_human_step" in engine_source
