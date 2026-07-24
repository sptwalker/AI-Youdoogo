"""Static regression checks for modular runtime dependency boundaries."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import app.agents.skill_registry as skill_registry
import app.agents.skills as skills
import app.agents.tool_dispatcher as tool_dispatcher
from app.services import (
    orchestration_service,
    workflow_projection,
    workflow_repository,
    workflow_service,
    workflow_state,
)
from scripts.import_graph import ImportGraph, build_import_graph, format_cycles

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
RUNTIME_MODULES = {
    "app.bootstrap.workflow_events",
    "app.bootstrap.workflow_worker",
    "app.agents.base",
    "app.agents.contracts",
    "app.agents.legacy_skill_adapters",
    "app.agents.skill_registry",
    "app.agents.skills",
    "app.agents.tool_dispatcher",
    "app.agents.workflow_engine",
    "app.contexts.business.task_management.infrastructure.legacy_workflow",
    "app.contexts.business.task_management.legacy_public",
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


def test_workflow_and_skill_facades_preserve_public_exports() -> None:
    from app.bootstrap import workflow_events
    from app.bootstrap import workflow_worker as bootstrap_worker
    from app.services import workflow_event_handler
    from app.services import workflow_worker as legacy_worker

    assert workflow_service.create_workflow is workflow_repository.create_workflow
    assert workflow_service.progress is workflow_projection.progress
    assert workflow_service.claim_step_result is workflow_state.claim_step_result
    assert skills.REGISTRY is skill_registry.REGISTRY
    assert skills.ToolDispatcher is tool_dispatcher.ToolDispatcher
    assert orchestration_service.PlanStep.__module__ == "app.services.workflow_planning"
    assert workflow_event_handler.handle_event is workflow_events.handle_event
    assert (
        legacy_worker.outbox_lease_heartbeat
        is bootstrap_worker.outbox_lease_heartbeat
    )


def test_bootstrap_worker_skips_intermediate_workflow_facades() -> None:
    worker_imports = _imports("app.bootstrap.workflow_worker")
    event_imports = _imports("app.bootstrap.workflow_events")
    assert not worker_imports & {
        "app.services.workflow_event_handler",
        "app.services.workflow_recovery",
        "app.services.workflow_service",
    }
    assert not event_imports & {
        "app.services.environment_service",
        "app.services.discussion_service",
        "app.services.workflow_service",
        "app.services.workflow_step_executor",
    }


def test_skill_services_depend_on_contracts_not_agent_base() -> None:
    for module in (
        "app.services.collab_protocol",
        "app.services.deliver_service",
        "app.services.query_skill",
    ):
        imports = _imports(module)
        assert "app.agents.contracts" in imports
        assert "app.agents.base" not in imports


def test_skill_runtime_skips_migrated_capability_facades() -> None:
    for module in ("app.agents.legacy_skill_adapters", "app.agents.skill_registry"):
        assert not _imports(module) & {
            "app.services.collab_protocol",
            "app.services.deliver_service",
            "app.services.query_skill",
        }


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
    engine_source = _app_graph().modules[
        "app.agents.workflow_engine"
    ].path.read_text(encoding="utf-8")
    assert "workflow_service.create_workflow" in engine_source
    assert "workflow_service.accept_human_step" in engine_source


def test_taskcard_fallback_has_no_intermediate_runtime_facades() -> None:
    orchestration_imports = _imports("app.services.orchestration_service")
    assert "app.contexts.business.task_management.legacy_public" in orchestration_imports
    assert "app.services.legacy_orchestration" not in orchestration_imports
    assert (
        "app.contexts.foundations.execution.workflow_runtime.infrastructure.legacy_taskcard_runtime"
        not in orchestration_imports
    )
