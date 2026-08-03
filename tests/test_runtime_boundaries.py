"""Static regression checks for the canonical modular runtime boundaries."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import app.agents.skill_registry as skill_registry
import app.agents.tool_dispatcher as tool_dispatcher
from scripts.import_graph import ImportGraph, build_import_graph, format_cycles

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
RUNTIME_MODULES = {
    "app.bootstrap.workflow_events",
    "app.bootstrap.workflow_worker",
    "app.agents.contracts",
    "app.agents.legacy_skill_adapters",
    "app.agents.skill_registry",
    "app.agents.tool_dispatcher",
    "app.contexts.foundations.execution.agent_execution.entrypoints.operations",
    "app.contexts.business.task_management.infrastructure.legacy_workflow",
    "app.contexts.business.task_management.entrypoints.operations",
    "app.contexts.foundations.execution.work_planning.entrypoints.operations",
    "app.contexts.foundations.execution.workflow_runtime.entrypoints.operations",
    "app.contexts.foundations.execution.workflow_runtime.infrastructure.worker",
}


@cache
def _app_graph() -> ImportGraph:
    return build_import_graph(APP)


def _imports(module: str) -> set[str]:
    return set(_app_graph().edges[module])


def test_runtime_modules_are_acyclic() -> None:
    app_graph = _app_graph()
    graph = ImportGraph(
        modules={module: app_graph.modules[module] for module in RUNTIME_MODULES},
        edges={
            module: frozenset(app_graph.edges[module] & RUNTIME_MODULES)
            for module in RUNTIME_MODULES
        },
    )
    cycles = graph.cycles()
    assert cycles == (), format_cycles(cycles)


def test_tool_dispatcher_uses_the_canonical_registry() -> None:
    assert tool_dispatcher.ToolDispatcher().registry is skill_registry.REGISTRY


def test_bootstrap_worker_uses_canonical_runtime_modules() -> None:
    imports = _imports("app.bootstrap.workflow_worker") | _imports(
        "app.bootstrap.workflow_events"
    )
    assert not {
        dependency
        for dependency in imports
        if dependency.startswith(("app.services", "app.knowledge"))
    }
    assert "app.contexts.foundations.execution.workflow_runtime.infrastructure.worker" in _imports(
        "app.bootstrap.workflow_worker"
    )


def test_skill_runtime_uses_context_capabilities_directly() -> None:
    for module in ("app.agents.legacy_skill_adapters", "app.agents.skill_registry"):
        assert not {
            dependency
            for dependency in _imports(module)
            if dependency.startswith("app.services")
        }


def test_planning_cannot_bypass_durable_runtime() -> None:
    imports = _imports(
        "app.contexts.foundations.execution.work_planning.entrypoints.operations"
    )
    assert not {
        dependency
        for dependency in imports
        if "workflow_runtime.infrastructure" in dependency
        or dependency.startswith("app.platform.outbox")
    }


def test_retired_runtime_facades_are_absent() -> None:
    retired = (
        APP / "services",
        APP / "knowledge",
        APP / "agents" / "scheduler.py",
        APP / "agents" / "skills.py",
        APP / "agents" / "base.py",
        APP / "agents" / "runtime_adapters.py",
        APP / "agents" / "workflow_engine.py",
    )
    remaining = [
        path.relative_to(ROOT)
        for path in retired
        if path.is_file() or (path.is_dir() and any(path.glob("*.py")))
    ]
    assert remaining == []
