"""Static guardrails for the DDD modular-monolith package structure."""

from __future__ import annotations

import ast
from collections import defaultdict
from functools import cache
from pathlib import Path

from app.contexts.foundations.knowledge import storage_gateway as knowledge_storage
from app.core import database as legacy_database
from app.knowledge import storage as legacy_storage
from app.models import base as legacy_model_base
from app.models import workflow as legacy_workflow_models
from app.platform import database as platform_database
from app.platform.object_storage import gateway as object_storage
from app.platform.outbox import model as outbox_model
from app.platform.outbox import repository as outbox_repository
from app.services import outbox_service
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
    for package in ("app.agents", "app.bootstrap", "app.knowledge"):
        assert graph.edges[package] == frozenset()
        tree = ast.parse(graph.modules[package].path.read_text(encoding="utf-8"))
        assert len(tree.body) == 1
        assert isinstance(tree.body[0], ast.Expr)
        assert isinstance(tree.body[0].value, ast.Constant)
        assert isinstance(tree.body[0].value.value, str)


def test_runtime_callers_use_agent_and_knowledge_leaf_modules() -> None:
    package_roots = {"app.agents", "app.knowledge"}
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
    """Production modules use canonical boundaries; old paths remain external shims."""
    migrated_facades = {
        "app.services.collab_protocol",
        "app.services.deliver_service",
        "app.services.environment_service",
        "app.services.query_skill",
        "app.services.realtime_service",
    }
    violations = [
        f"{module} -> {dependency}"
        for module, dependencies in sorted(_app_graph().edges.items())
        for dependency in sorted(dependencies & migrated_facades)
    ]
    assert violations == []


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
    application_roots = [path for path in (APP / "contexts").rglob("application") if path.is_dir()]
    forbidden = (
        "app.api",
        "app.bootstrap",
        "app.core.database",
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


def test_legacy_facades_preserve_public_object_identity() -> None:
    """Incremental migration keeps old imports working without duplicate implementations."""
    assert legacy_database.engine is platform_database.engine
    assert legacy_database.async_session_factory is platform_database.async_session_factory
    assert legacy_model_base.Base is platform_database.Base
    assert legacy_workflow_models.OutboxEvent is outbox_model.OutboxEvent
    assert outbox_service.enqueue is outbox_repository.enqueue
    assert outbox_service.claim_next is outbox_repository.claim_next
    assert legacy_storage.put_object is object_storage.put_object
    assert legacy_storage.get_object_bytes is object_storage.get_object_bytes
    assert knowledge_storage.put_object is object_storage.put_object
    assert knowledge_storage.get_object_bytes is object_storage.get_object_bytes


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


def test_zero_caller_legacy_facades_are_removed() -> None:
    removed = (
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
    assert [path.relative_to(ROOT) for path in removed if path.exists()] == []


# ── model_gateway 接缝守卫（ADR 0001）────────────────────────────────
_LLM_COMPLETION_NAMES = {"get_llm_for_role", "create_llm", "BaseChatModel"}

# 未迁移的 LLM 完成直连家族：显式挂账，随后续单模块逐个收编而递减（ADR 0001）。
# Phase 0 已全部收编，白名单清空——任何新增直连都会被守卫直接判为越界。
_LLM_COMPLETION_MIGRATION_DEBT: set[str] = set()

# 本模块已收编、必须真正脱离直连的家族（不得回到白名单/直连）。
_LLM_COMPLETION_MIGRATED = {
    "app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py",
    "app/contexts/foundations/governance/system_configuration/connectivity/infrastructure/adapters.py",
    "app/contexts/foundations/execution/agent_execution/infrastructure/composition.py",
    "app/contexts/foundations/execution/agent_execution/infrastructure/langchain_gateway.py",
    "app/contexts/foundations/governance/ai_quality/infrastructure/composition.py",
    "app/contexts/foundations/governance/ai_quality/infrastructure/legacy_execution.py",
    "app/contexts/foundations/execution/work_planning/infrastructure/langchain_planner.py",
    "app/contexts/foundations/knowledge/organizational_memory/infrastructure/llm_distillation.py",
    "app/contexts/business/assistant_conversations/infrastructure/adapters.py",
    "app/contexts/business/group_messaging/infrastructure/adapters.py",
}


def _touches_llm_completion(path: Path) -> bool:
    """A file touches the LLM completion seam if it pulls in vendor chat types or the role factory.

    仅针对「完成」语义：langchain*、``get_llm_for_role``/``create_llm``/``BaseChatModel``。
    ``app.llm.usage``（用量记录，ADR 0001 记为独立债务）与 ``app.llm.factory``/embedding 不计入。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("langchain") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("langchain"):
                return True
            if any(alias.name in _LLM_COMPLETION_NAMES for alias in node.names):
                return True
    return False


def test_llm_completion_flows_through_model_gateway_seam() -> None:
    """所有 LLM 完成调用必须经 model_gateway 接缝；未迁移家族须显式挂账，已迁移家族须真正脱离。"""
    seam = APP / "contexts" / "foundations" / "model_gateway"
    touching = {
        path.relative_to(ROOT).as_posix()
        for path in (APP / "contexts").rglob("*.py")
        if _touches_llm_completion(path)
    }
    offenders = sorted(
        rel
        for rel in touching
        if not (ROOT / rel).is_relative_to(seam) and rel not in _LLM_COMPLETION_MIGRATION_DEBT
    )
    assert offenders == [], f"新增 LLM 完成直连（应经 model_gateway.public）：{offenders}"
    # 已迁移的家族确实脱离直连。
    regressed = sorted(_LLM_COMPLETION_MIGRATED & touching)
    assert regressed == [], f"已收编家族回退为直连：{regressed}"
    # 债务白名单精确——不留已消除项，避免虚假债务。
    stale = sorted(_LLM_COMPLETION_MIGRATION_DEBT - touching)
    assert stale == [], f"债务白名单存在冗余项（已消除应删除）：{stale}"


# ── knowledge_retrieval 检索接缝守卫（ADR 0002 · A1）──────────────────
_KNOWLEDGE_SESSION_ENTRYPOINTS = {
    "search_knowledge",
    "answer_knowledge",
    "diagnose_retrieval_arms",
}
_KNOWLEDGE_RETRIEVAL_CTX = (
    APP / "contexts" / "foundations" / "knowledge" / "knowledge_retrieval"
)


def _imports_knowledge_session_entrypoint(path: Path) -> bool:
    """文件是否直引会话级知识检索 entrypoint（应改经端口工厂）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("knowledge_retrieval.public") or module.endswith(
                "knowledge_retrieval.entrypoints.operations"
            ):
                if any(alias.name in _KNOWLEDGE_SESSION_ENTRYPOINTS for alias in node.names):
                    return True
    return False


def test_knowledge_search_flows_through_port_seam() -> None:
    """跨 Context 知识检索须经 KnowledgeSearchPort 端口；禁止直引会话级 entrypoint 函数。

    ``knowledge_retrieval`` 自身（public/operations 内部装配）与 ``app/api``、``app/agents``
    等 legacy facade 不在 ``app/contexts`` 扫描面内，故不受约束。
    """
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (APP / "contexts").rglob("*.py")
        if not path.is_relative_to(_KNOWLEDGE_RETRIEVAL_CTX)
        and _imports_knowledge_session_entrypoint(path)
    )
    assert offenders == [], (
        f"跨 Context 直引会话级知识检索 entrypoint（应经端口工厂）：{offenders}"
    )


# ── usage_budget 记账接缝守卫（ADR 0002 · A2）────────────────────────
def test_usage_recording_flows_through_usage_budget_public() -> None:
    """``app/contexts`` 下 LLM 用量记账一律经 usage_budget.public；禁止引 legacy ``app.llm.usage``。

    ``app/agents``、``app/services`` 等迁移期 facade 仍可用旧路径（不在扫描面内）。
    """
    offenders = _violations(APP / "contexts", ("app.llm.usage",))
    assert offenders == [], (
        f"新增 legacy app.llm.usage 直引（应经 usage_budget.public）：{offenders}"
    )
