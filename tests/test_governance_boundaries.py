"""Pure governance decisions and evidence boundaries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.governance.ai_quality.application.use_cases import (
    CompareCandidatePrompt,
    RunEvaluation,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    EvaluationCaseView,
)
from app.contexts.foundations.governance.audit_trail.application.use_cases import (
    AppendAuditRecord,
)
from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
)
from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewRequest,
    ReviewRisk,
)
from app.contexts.foundations.governance.human_review.public import evaluate_review
from app.contexts.foundations.governance.system_configuration.application.use_cases import (
    UpdateConfiguration,
)
from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    ConfigView,
    UpdateConfigCommand,
)
from app.contexts.foundations.governance.usage_budget.contracts.usage import BudgetPolicy
from app.contexts.foundations.governance.usage_budget.domain.policies import authorize_usage
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class _AuditRepository:
    def __init__(self) -> None:
        self.commands: list[AppendAuditRecordCommand] = []

    async def add(self, command: AppendAuditRecordCommand) -> None:
        self.commands.append(command)


class _AuditUnit:
    def __init__(self, *, fail_commits: int = 0) -> None:
        self.records = _AuditRepository()
        self.fail_commits = fail_commits
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commits <= self.fail_commits:
            raise RuntimeError("db unavailable")

    async def rollback(self) -> None:
        self.rollbacks += 1


class _AuditFailures:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def record_failure(self, action: str, actor_id: uuid.UUID | None) -> None:
        del actor_id
        self.actions.append(action)


async def test_audit_is_redacted_append_only_and_best_effort() -> None:
    unit = _AuditUnit(fail_commits=2)
    failures = _AuditFailures()
    await AppendAuditRecord(lambda: unit, failures).execute(
        AppendAuditRecordCommand(
            action="data.query",
            summary="query evidence",
            detail={"sql": "select 1", "api_token": "secret"},
        )
    )

    assert unit.commits == 2
    assert unit.rollbacks == 2
    assert failures.actions == ["data.query"]
    assert unit.records.commands[0].detail == {
        "sql": "select 1",
        "api_token": "***",
    }


class _ConfigRepository:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.current = ConfigView(
            config_id=uuid.uuid4(),
            key="feature",
            value=False,
            value_type="bool",
            category="feature",
            is_editable=True,
            is_secret=False,
            is_set=True,
        )

    async def get(self, key: str) -> ConfigView | None:
        return self.current if key == self.current.key else None

    async def list(self) -> tuple[ConfigView, ...]:
        return (self.current,)

    async def update(
        self, key: str, value: object, updated_by: uuid.UUID | None
    ) -> ConfigView:
        del updated_by
        self._events.append("update")
        self.current = ConfigView(
            config_id=self.current.config_id,
            key=key,
            value=value,
            value_type=self.current.value_type,
            category=self.current.category,
            is_editable=True,
            is_secret=False,
            is_set=True,
        )
        return self.current


class _ConfigUnit:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.configurations = _ConfigRepository(events)

    async def commit(self) -> None:
        self._events.append("commit")

    async def rollback(self) -> None:
        self._events.append("rollback")


class _RuntimeConfig:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def set_override(self, key: str, value: object) -> None:
        del key, value
        self._events.append("runtime")


class _ConfigAudit:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def record_update(self, **kwargs: object) -> None:
        del kwargs
        self._events.append("audit")


async def test_configuration_commits_before_runtime_and_audit_evidence() -> None:
    events: list[str] = []
    unit = _ConfigUnit(events)
    result = await UpdateConfiguration(
        unit, _RuntimeConfig(events), _ConfigAudit(events)
    ).execute(
        UpdateConfigCommand(
            key="feature",
            value=True,
            updated_by=uuid.uuid4(),
            actor_role="admin",
        )
    )

    assert result.value is True
    assert events == ["update", "commit", "runtime", "audit"]


def test_human_review_returns_decision_without_source_state() -> None:
    request = ReviewRequest(
        action="deliver",
        target_type="capability",
        target_id="deliver",
        principal_id=uuid.uuid4(),
        risk=ReviewRisk.HIGH,
        payload_hash="sha256:value",
        policy_version="1",
    )
    decision = evaluate_review(request)

    assert decision.approved is True
    assert decision.requires_human is False
    assert request.target_id == "deliver"


def test_usage_authorization_is_a_decision_not_a_source_mutation() -> None:
    denied = authorize_usage(BudgetPolicy(100, True), current_tokens=100)
    soft = authorize_usage(BudgetPolicy(100, False), current_tokens=500)

    assert denied.allowed is False and denied.code == "budget_exceeded"
    assert soft.allowed is True


@dataclass
class _QualityUnit:
    cases: object
    feedback: object

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Cases:
    def __init__(self, case: EvaluationCaseView) -> None:
        self._case = case

    async def list_applicable(
        self, role_id: uuid.UUID
    ) -> tuple[EvaluationCaseView, ...]:
        del role_id
        return (self._case,)


class _Subjects:
    def __init__(self, subject: ExpertExecutionSnapshot) -> None:
        self.subject = subject

    async def get(self, role_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return self.subject if role_id == self.subject.expert_id else None


class _Executor:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def execute(
        self,
        subject: ExpertExecutionSnapshot,
        prompt: str,
        case: EvaluationCaseView,
        user_id: uuid.UUID | None,
    ) -> str:
        del subject, case, user_id
        self.prompts.append(prompt)
        return prompt


class _Judge:
    async def score(
        self, rubric: str, output: str, user_id: uuid.UUID | None
    ) -> int:
        del rubric, user_id
        return 5 if output == "candidate" else 3


async def test_ai_quality_compares_candidate_without_changing_expert_snapshot() -> None:
    role_id = uuid.uuid4()
    subject = ExpertExecutionSnapshot(
        expert_id=role_id,
        version="1",
        name="expert",
        title="",
        department_id=None,
        prompt_template="production",
        model_role="daily",
    )
    case = EvaluationCaseView(
        case_id=uuid.uuid4(),
        name="case",
        role_id=role_id,
        input_text="input",
        rubric="rubric",
    )
    executor = _Executor()
    evaluator = RunEvaluation(
        _QualityUnit(_Cases(case), object()),
        _Subjects(subject),
        executor,
        _Judge(),
    )

    result = await CompareCandidatePrompt(evaluator).execute(role_id, "candidate")

    assert result.improved is True and result.delta == 2.0
    assert executor.prompts == ["production", "candidate"]
    assert subject.prompt_template == "production"
