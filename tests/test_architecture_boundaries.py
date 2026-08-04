"""Static guardrails for the DDD modular-monolith package structure."""

from __future__ import annotations

import ast
from collections import defaultdict
from functools import cache
from pathlib import Path

from app.models import Base
from app.models import workflow as legacy_workflow_models
from app.platform import database as platform_database
from app.platform.database import model as platform_model
from app.platform.outbox import model as outbox_model
from app.platform.outbox import repository as outbox_repository
from scripts.import_graph import (
    ImportGraph,
    build_import_graph,
    format_cycles,
    runtime_import_names,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _imports(path: Path) -> set[str]:
    """Return absolute import module names used by one Python source file."""
    return runtime_import_names(path)


@cache
def _app_graph() -> ImportGraph:
    return build_import_graph(APP)


def _violations(root: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    """Collect forbidden imports with stable repo-relative diagnostics."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for imported in sorted(_imports(path)):
            if imported.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    return violations


def _write_modules(root: Path, sources: dict[str, str]) -> Path:
    package_root = root / "app"
    for module, source in sources.items():
        is_module = module.endswith(".py")
        parts = module.removesuffix(".py").split(".")
        path = root.joinpath(*parts)
        if is_module:
            path = path.with_suffix(".py")
        else:
            path = path / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return package_root


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = relative.parent.parts if relative.name == "__init__" else relative.parts
    return ".".join(parts)


@cache
def _context_roots() -> tuple[str, ...]:
    layer_names = {"application", "contracts", "domain", "entrypoints", "infrastructure"}
    roots = {
        _module_name(path.parent / "__init__.py")
        for path in (APP / "contexts").rglob("*")
        if path.is_dir() and path.name in layer_names
    }
    return tuple(sorted(roots, key=len, reverse=True))


def _owning_context(module: str) -> str | None:
    return next(
        (root for root in _context_roots() if module == root or module.startswith(f"{root}.")),
        None,
    )


def _context_layer(module: str, context: str) -> str | None:
    suffix = module.removeprefix(context).removeprefix(".")
    return suffix.split(".", 1)[0] if suffix else None


def _has_path(graph: ImportGraph, source: str, target: str) -> bool:
    pending = [source]
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module == target:
            return True
        if module in visited:
            continue
        visited.add(module)
        pending.extend(graph.edges[module] - visited)
    return False


def _persistent_context_writers() -> dict[str, set[str]]:
    """Map ORM models to Contexts that persist or mutate them."""
    writers: defaultdict[str, set[str]] = defaultdict(set)
    contexts = APP / "contexts"
    for path in sorted(contexts.rglob("*.py")):
        relative_parts = path.relative_to(contexts).parts
        if "infrastructure" not in relative_parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        models: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module or not node.module.startswith("app.models"):
                continue
            for imported in node.names:
                models[imported.asname or imported.name] = f"{node.module}.{imported.name}"
        if not models:
            continue

        factories: dict[str, str] = {}
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for function in functions:
            constructed = {
                models[call.func.id]
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id in models
            }
            if len(constructed) == 1 and any(
                isinstance(node, ast.Return) for node in ast.walk(function)
            ):
                factories[function.name] = next(iter(constructed))

        context = "/".join(relative_parts[: relative_parts.index("infrastructure")])
        for function in functions:
            variables: dict[str, str] = {}
            for node in ast.walk(function):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value.value if isinstance(node.value, ast.Await) else node.value
                    model = None
                    if isinstance(value, ast.Call):
                        if isinstance(value.func, ast.Name):
                            model = models.get(value.func.id) or factories.get(value.func.id)
                        elif (
                            isinstance(value.func, ast.Attribute)
                            and value.func.attr == "get"
                            and value.args
                            and isinstance(value.args[0], ast.Name)
                        ):
                            model = models.get(value.args[0].id)
                    if model is not None:
                        for target in targets:
                            if isinstance(target, ast.Name):
                                variables[target.id] = model

                if isinstance(node, ast.Call):
                    model = None
                    if (
                        isinstance(node.func, ast.Name)
                        and node.func.id in {"delete", "insert", "update"}
                        and node.args
                        and isinstance(node.args[0], ast.Name)
                    ):
                        model = models.get(node.args[0].id)
                    elif (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"add", "delete"}
                        and node.args
                    ):
                        argument = node.args[0]
                        if isinstance(argument, ast.Name):
                            model = variables.get(argument.id)
                        elif isinstance(argument, ast.Call) and isinstance(argument.func, ast.Name):
                            model = models.get(argument.func.id) or factories.get(argument.func.id)
                    if model is not None:
                        writers[model].add(context)

                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id in variables
                        ):
                            writers[variables[target.value.id]].add(context)
    return dict(writers)


def test_import_graph_characterizes_the_three_pre_p0_components(tmp_path: Path) -> None:
    """The analyzer retains a regression fixture for the three removed legacy SCCs."""
    package_root = _write_modules(
        tmp_path,
        {
            "app": "",
            "app.agents": (
                "from app.agents.base import run_agent\n"
                "from app.agents.ops import generate\n"
                "from app.agents.scheduler import run_task\n"
            ),
            "app.agents.base.py": ("def prepare():\n    from app.agents import skills\n"),
            "app.agents.ops.py": "from app.agents.base import run_agent\n",
            "app.agents.scheduler.py": (
                "from app.agents.base import run_agent\n"
                "def execute():\n"
                "    from app.agents import skills\n"
            ),
            "app.agents.skills.py": "",
            "app.knowledge": (
                "from app.knowledge.ingest import ingest_text\n"
                "from app.knowledge.retrieval import search\n"
            ),
            "app.knowledge.ingest.py": "from app.knowledge import storage\n",
            "app.knowledge.retrieval.py": ("def search():\n    from app.knowledge import rerank\n"),
            "app.knowledge.rerank.py": "",
            "app.knowledge.storage.py": "",
            "app.services": "",
            "app.services.environment_service.py": (
                "from app.services import (\n"
                "    agent_role_service, auth_service, data_source_service, org_service\n"
                ")\n"
            ),
            "app.services.agent_role_service.py": (
                "def refresh():\n    from app.services import environment_service\n"
            ),
            "app.services.auth_service.py": (
                "def refresh():\n    from app.services import environment_service\n"
            ),
            "app.services.data_source_service.py": (
                "def refresh():\n    from app.services import environment_service\n"
            ),
            "app.services.org_service.py": (
                "def refresh():\n    from app.services import environment_service\n"
            ),
        },
    )

    assert build_import_graph(package_root).cycles() == (
        frozenset(
            {
                "app.agents",
                "app.agents.base",
                "app.agents.ops",
                "app.agents.scheduler",
            }
        ),
        frozenset(
            {
                "app.knowledge",
                "app.knowledge.ingest",
                "app.knowledge.retrieval",
            }
        ),
        frozenset(
            {
                "app.services.agent_role_service",
                "app.services.auth_service",
                "app.services.data_source_service",
                "app.services.environment_service",
                "app.services.org_service",
            }
        ),
    )


def test_import_graph_counts_function_imports_but_ignores_type_checking(
    tmp_path: Path,
) -> None:
    package_root = _write_modules(
        tmp_path,
        {
            "app": "",
            "app.consumer.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    import app.type_only\n"
                "def execute():\n"
                "    import app.runtime_dependency\n"
            ),
            "app.runtime_dependency.py": "",
            "app.type_only.py": "",
        },
    )

    graph = build_import_graph(package_root)
    assert graph.edges["app.consumer"] == frozenset({"app.runtime_dependency"})


def test_application_import_graph_is_acyclic() -> None:
    cycles = _app_graph().cycles()
    assert cycles == (), format_cycles(cycles)


def test_runtime_root_packages_are_side_effect_free() -> None:
    graph = _app_graph()
    for package in ("app.agents", "app.bootstrap"):
        assert graph.edges[package] == frozenset()
        tree = ast.parse(graph.modules[package].path.read_text(encoding="utf-8"))
        assert len(tree.body) == 1
        assert isinstance(tree.body[0], ast.Expr)
        assert isinstance(tree.body[0].value, ast.Constant)
        assert isinstance(tree.body[0].value.value, str)


def test_runtime_callers_use_agent_leaf_modules() -> None:
    package_roots = {"app.agents"}
    violations = [
        f"{module} -> {dependency}"
        for module, dependencies in sorted(_app_graph().edges.items())
        if module not in package_roots
        for dependency in sorted(dependencies & package_roots)
    ]
    assert violations == []


def test_context_dependencies_point_inward() -> None:
    internal_layers = {"application", "domain", "entrypoints", "infrastructure"}
    violations: list[str] = []
    for source, dependencies in sorted(_app_graph().edges.items()):
        source_context = _owning_context(source)
        if source_context is None:
            continue
        source_layer = _context_layer(source, source_context)
        for target in sorted(dependencies):
            target_context = _owning_context(target)
            if target_context is None:
                continue
            target_layer = _context_layer(target, target_context)
            if source_context != target_context and target_layer in internal_layers:
                violations.append(f"{source} -> {target}")
            elif source_layer == "domain" and target_layer in {
                "application",
                "entrypoints",
                "infrastructure",
            }:
                violations.append(f"{source} -> {target}")
            elif source_layer == "application" and target_layer in {
                "entrypoints",
                "infrastructure",
            }:
                violations.append(f"{source} -> {target}")
    assert violations == []


def test_migrated_orm_models_have_one_persistent_context_writer() -> None:
    """Read adapters may share models, but each persisted fact has one Context writer."""
    duplicates = {
        model: sorted(contexts)
        for model, contexts in _persistent_context_writers().items()
        if len(contexts) > 1
    }
    assert duplicates == {}


def test_legacy_to_canonical_facade_edges_are_one_way() -> None:
    graph = _app_graph()
    legacy_prefixes = (
        "app.agents",
        "app.core",
        "app.knowledge",
        "app.models",
        "app.services",
    )
    canonical_prefixes = ("app.contexts", "app.platform")
    violations = [
        f"{canonical} -> ... -> {facade}"
        for facade, dependencies in sorted(graph.edges.items())
        if facade.startswith(legacy_prefixes)
        for canonical in sorted(dependencies)
        if canonical.startswith(canonical_prefixes)
        if _has_path(graph, canonical, facade)
    ]
    assert violations == []


def test_runtime_skips_migrated_capability_projection_and_realtime_facades() -> None:
    """Retired horizontal facade packages must not be recreated."""
    assert list((APP / "services").glob("*.py")) == []
    assert list((APP / "knowledge").glob("*.py")) == []


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


def test_contexts_do_not_import_legacy_service_facades() -> None:
    """Bounded contexts collaborate through published APIs, never legacy service shims."""
    assert _violations(APP / "contexts", ("app.services",)) == []


def test_context_application_does_not_import_outer_layers() -> None:
    """Application policy may use pure libraries but not delivery or persistence details."""
    application_roots = [path for path in (APP / "contexts").rglob("application") if path.is_dir()]
    forbidden = (
        "app.api",
        "app.bootstrap",
        "app.models",
        "app.services",
        "app.agents",
        "app.knowledge",
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
        "app.agents",
        "app.knowledge",
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


def test_migrated_http_routes_do_not_import_business_implementations() -> None:
    """Migrated transport adapters may use DTOs/use cases, never ORM or legacy behavior."""
    forbidden = (
        "app.models",
        "app.services",
        "app.agents",
        "app.knowledge",
        "app.llm",
        "app.integrations",
    )
    routes = (
        APP / "api" / "deps.py",
        APP / "api" / "v1" / "admin.py",
        APP / "api" / "v1" / "agents.py",
        APP / "api" / "v1" / "ai_providers.py",
        APP / "api" / "v1" / "collab.py",
        APP / "api" / "v1" / "data_sources.py",
        APP / "api" / "v1" / "desktop.py",
        APP / "api" / "v1" / "discussion.py",
        APP / "api" / "v1" / "eval.py",
        APP / "api" / "v1" / "grants.py",
        APP / "api" / "v1" / "knowledge.py",
        APP / "api" / "v1" / "knowledge_bases.py",
        APP / "api" / "v1" / "meetings.py",
        APP / "api" / "v1" / "ops_data.py",
        APP / "api" / "v1" / "org.py",
        APP / "api" / "v1" / "proposals.py",
        APP / "api" / "v1" / "semantic.py",
        APP / "api" / "v1" / "tasks.py",
        APP / "api" / "v1" / "users.py",
    )
    violations = [
        f"{route.relative_to(ROOT)} -> {dependency}"
        for route in routes
        for dependency in sorted(_imports(route))
        if dependency.startswith(forbidden)
    ]
    assert violations == []


def test_migrated_http_routes_do_not_import_context_infrastructure() -> None:
    """Delivery adapters depend on published operations, never concrete adapters."""
    routes = (APP / "api" / "deps.py", *sorted((APP / "api" / "v1").glob("*.py")))
    violations = [
        f"{route.relative_to(ROOT)} -> {dependency}"
        for route in routes
        for dependency in sorted(_imports(route))
        if dependency.startswith("app.contexts.") and ".infrastructure" in dependency
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


def test_model_and_database_exports_preserve_public_object_identity() -> None:
    """The formal model and database exports share their Platform-owned objects."""
    assert Base is platform_database.Base
    assert Base is platform_model.Base
    assert legacy_workflow_models.OutboxEvent is outbox_model.OutboxEvent
    assert outbox_model.OutboxEvent is outbox_repository.OutboxEvent


def test_runtime_has_no_retired_horizontal_facade_imports() -> None:
    forbidden = ("app.services", "app.knowledge")
    violations = [
        violation
        for root in (APP, ROOT / "scripts")
        for violation in _violations(root, forbidden)
    ]
    assert violations == []


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


def test_agent_role_orm_mapping_stays_behind_explicit_compatibility_seams() -> None:
    """AgentRole must not cross Context boundaries as runtime collaboration data."""
    allowed_files = {
        APP / "models" / "__init__.py",
        APP
        / "contexts"
        / "foundations"
        / "execution"
        / "agent_execution"
        / "entrypoints"
        / "operations.py",
    }
    expert_infrastructure = (
        APP
        / "contexts"
        / "foundations"
        / "workforce"
        / "expert_management"
        / "infrastructure"
    )
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path in allowed_files or path.is_relative_to(expert_infrastructure):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module in {"app.models", "app.models.agent"}
                and any(imported.name == "AgentRole" for imported in node.names)
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import) and any(
                imported.name == "app.models.agent" for imported in node.names
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_zero_caller_legacy_facades_are_removed() -> None:
    removed = (
        APP / "contexts" / "foundations" / "knowledge" / "storage_gateway.py",
        APP / "agents" / "scheduler.py",
        APP / "agents" / "workflow_engine.py",
        APP / "knowledge" / "chunk.py",
        APP / "knowledge" / "extract.py",
        APP / "knowledge" / "rerank.py",
        APP / "knowledge" / "retrieval.py",
        APP / "knowledge" / "scope.py",
        APP
        / "contexts"
        / "foundations"
        / "execution"
        / "workflow_runtime"
        / "infrastructure"
        / "legacy_taskcard_runtime.py",
        APP / "services" / "anomaly.py",
        APP / "services" / "connectivity_service.py",
        APP / "services" / "desktop_chat_repository.py",
        APP / "services" / "desktop_chat_service.py",
        APP / "services" / "desktop_chat_streaming.py",
        APP / "services" / "desktop_service.py",
        APP / "services" / "data_catalog_service.py",
        APP / "services" / "data_source_service.py",
        APP / "services" / "feishu_oauth_config.py",
        APP / "services" / "feishu_oauth_store.py",
        APP / "services" / "knowledge_base_service.py",
        APP / "services" / "legacy_orchestration.py",
        APP / "services" / "meeting_ai_actions.py",
        APP / "services" / "meeting_service.py",
        APP / "services" / "ops_data.py",
        APP / "services" / "org_template.py",
        APP / "services" / "resource_grant_service.py",
        APP / "services" / "semantic_service.py",
        APP / "services" / "sql_guard.py",
        APP / "services" / "td_event_service.py",
        APP / "services" / "tool_execution_service.py",
    )
    remaining = [path.relative_to(ROOT) for path in removed if path.exists()]
    remaining.extend(path.relative_to(ROOT) for path in (APP / "services").glob("*.py"))
    remaining.extend(path.relative_to(ROOT) for path in (APP / "knowledge").glob("*.py"))
    assert remaining == []
