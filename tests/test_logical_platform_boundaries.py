"""Contract and Local Adapter tests for the first remote-capable platform seams."""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.contexts.foundations.execution.agent_execution.application.ports import (
    LlmExecutionPort as LegacyLlmExecutionPort,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.application.use_cases import (
    KnowledgeRetrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    KnowledgeRetrievalArmDiagnostics,
    KnowledgeRetrievalPort,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.local_adapter import (
    LocalKnowledgeRetrievalAdapter,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort as LlmExecutionPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.management import (
    CreateExpertCommand,
    ExpertManagementPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.local_adapter import (
    LocalExpertManagementAdapter,
)

ROOT = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return tuple(imported)


def test_published_platform_contracts_are_framework_independent() -> None:
    contracts = (
        ROOT / "app/contexts/foundations/model_gateway/contracts/completion.py",
        ROOT / "app/contexts/foundations/knowledge/knowledge_retrieval/contracts.py",
        ROOT / "app/contexts/foundations/workforce/expert_management/contracts/management.py",
    )
    forbidden = (
        "fastapi",
        "httpx",
        "langchain",
        "sqlalchemy",
        "app.models",
        "app.services",
        "app.llm",
    )
    violations = [
        f"{path.relative_to(ROOT)} -> {module}"
        for path in contracts
        for module in _imported_modules(path)
        if module.startswith(forbidden)
    ]
    assert violations == []
    assert "AsyncSession" not in str(inspect.signature(ExpertManagementPort.get_roster))
    assert "AsyncSession" not in str(inspect.signature(ExpertManagementPort.create))


def test_local_adapters_keep_object_identity() -> None:
    assert LegacyLlmExecutionPort is LlmExecutionPort


class _RetrievalGateway:
    def __init__(self) -> None:
        self.queries: list[SearchKnowledgeQuery] = []

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        self.queries.append(query)
        return SearchKnowledgeResult(hits=(), query=query.query)

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
        return KnowledgeAnswer(answer=query.query, citations=())

    async def diagnose(self, query: SearchKnowledgeQuery) -> KnowledgeRetrievalArmDiagnostics:
        empty = SearchKnowledgeResult(hits=(), query=query.query)
        return KnowledgeRetrievalArmDiagnostics(vector=empty, keyword=empty, fused=empty)


async def test_local_knowledge_adapter_preserves_application_policy() -> None:
    gateway = _RetrievalGateway()
    local: KnowledgeRetrievalPort = LocalKnowledgeRetrievalAdapter(KnowledgeRetrieval(gateway))

    blank = await local.search(SearchKnowledgeQuery(query="  "))
    assert blank.hits == ()
    assert gateway.queries == []

    query = SearchKnowledgeQuery(query="审批制度")
    assert await local.search(query) == SearchKnowledgeResult(hits=(), query="审批制度")
    assert gateway.queries == [query]


def _roster(expert_id: uuid.UUID) -> ExpertRosterSnapshot:
    return ExpertRosterSnapshot(
        expert_id=expert_id,
        version="v1",
        code="ops",
        name="运营专家",
        title="总监",
        tier="director",
        department_id=None,
        report_to_id=None,
        owner_user_id=None,
        duty="分析",
        prompt_template="依据事实",
        model_role="reasoning",
        permission_scope_json="{}",
        tools_json="[]",
        is_seed=True,
        is_active=True,
        create_time=datetime.now(UTC),
    )


class _ExpertApplication:
    def __init__(self, snapshot: ExpertRosterSnapshot) -> None:
        self.snapshot = snapshot
        self.created: list[CreateExpertCommand] = []

    async def create(self, command: CreateExpertCommand) -> ExpertRosterSnapshot:
        self.created.append(command)
        return self.snapshot


class _ExpertRosterQuery:
    def __init__(self, snapshot: ExpertRosterSnapshot) -> None:
        self.snapshot = snapshot

    async def get_roster_by_id(self, expert_id: uuid.UUID) -> ExpertRosterSnapshot | None:
        return self.snapshot if expert_id == self.snapshot.expert_id else None


class _ExpertSnapshotQuery:
    def __init__(self, snapshot: ExpertExecutionSnapshot) -> None:
        self.snapshot = snapshot

    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return self.snapshot if expert_id == self.snapshot.expert_id else None


async def test_local_expert_adapter_exposes_session_free_object_api() -> None:
    expert_id = uuid.uuid4()
    roster = _roster(expert_id)
    execution = ExpertExecutionSnapshot(
        expert_id=expert_id,
        version="v1",
        name=roster.name,
        title=roster.title,
        department_id=None,
        prompt_template=roster.prompt_template,
        model_role=roster.model_role,
    )
    application = _ExpertApplication(roster)
    local: ExpertManagementPort = LocalExpertManagementAdapter(
        application=application,  # type: ignore[arg-type]
        roster=_ExpertRosterQuery(roster),  # type: ignore[arg-type]
        snapshots=_ExpertSnapshotQuery(execution),  # type: ignore[arg-type]
    )

    command = CreateExpertCommand(name="运营专家", prompt_template="依据事实")
    assert await local.create(command) == roster
    assert await local.get_roster(expert_id) == roster
    assert await local.get_execution(expert_id) == execution
    assert application.created == [command]
