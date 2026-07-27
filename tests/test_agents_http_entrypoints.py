"""Agent HTTP adapters delegate to Context operations without legacy dependencies."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.api.v1 import agents
from app.contexts.business.operational_analytics.agent_contracts import (
    AnomalyCheckResult,
    MetricAlert,
)
from app.contexts.foundations.execution.agent_execution.contracts.consult import (
    ConsultExpertResult,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
    CapabilityRisk,
    CapabilitySideEffect,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    FeedbackResult,
    PromptImprovementSuggestion,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)
from app.schemas.agent import (
    AgentRoleCreate,
    AgentRoleUpdate,
    AnomalyCheckRequest,
    DailyReportRequest,
    FeedbackRequest,
    ProposalRequest,
)

ROOT = Path(__file__).resolve().parents[1]


def _principal() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role_code="admin")


def _record(task_type: str = "daily_report") -> AgentExecutionRecordView:
    return AgentExecutionRecordView(
        id=uuid.uuid4(),
        agent_role_id=uuid.uuid4(),
        task_type=task_type,
        input_summary="summary",
        output_content="content",
        model_used="fake-model",
        status="success",
        error_msg=None,
        duration_ms=25,
        create_time=datetime(2026, 7, 23, tzinfo=UTC),
    )


def _expert() -> ExpertRosterSnapshot:
    return ExpertRosterSnapshot(
        expert_id=uuid.uuid4(),
        version="new",
        code=None,
        name="运营顾问",
        title="",
        tier="member",
        department_id=None,
        report_to_id=None,
        owner_user_id=None,
        duty="分析运营",
        prompt_template="内部提示词",
        model_role="daily",
        permission_scope_json='{"scope":"department"}',
        tools_json='["data_query"]',
        is_seed=False,
        is_active=True,
        create_time=datetime(2026, 7, 23, tzinfo=UTC),
    )


def test_agent_router_has_eleven_thin_endpoints_and_no_forbidden_imports() -> None:
    source = (ROOT / "app/api/v1/agents.py").read_text(encoding="utf-8")
    assert len(agents.router.routes) == 11
    for forbidden in (
        "app.models",
        "app.services",
        "app.agents",
        "app.llm",
        "app.integrations",
        "from sqlalchemy import select",
    ):
        assert forbidden not in source


async def test_operational_and_record_routes_delegate_to_contexts(monkeypatch) -> None:
    principal = _principal()
    report = _record()
    proposal = _record("proposal")
    alert_record = _record("anomaly_alert")

    async def daily(*args, **kwargs):
        assert kwargs["operator_id"] == principal.id
        assert kwargs["rows"][0]["product"] == "产品A"
        return report

    async def anomaly(*args, **kwargs):
        return AnomalyCheckResult(
            alerts=(MetricAlert("产品A", "dau", "warning", "下降"),),
            record=alert_record,
        )

    async def create_proposal(*args, **kwargs):
        return proposal

    async def records(*args, **kwargs):
        assert args[1] == 5
        return (report,)

    async def my_feedback(*args, **kwargs):
        return ()

    monkeypatch.setattr(agents.operational_operations, "create_daily_report", daily)
    monkeypatch.setattr(agents.operational_operations, "check_anomalies", anomaly)
    monkeypatch.setattr(
        agents.operational_operations,
        "create_operational_proposal",
        create_proposal,
    )
    monkeypatch.setattr(
        agents.agent_execution_operations,
        "list_execution_records",
        records,
    )
    monkeypatch.setattr(agents.quality_operations, "list_my_feedback", my_feedback)

    daily_response = await agents.ops_daily_report(
        DailyReportRequest(
            stat_date="2026-07-23",
            rows=[{"product": "产品A", "dau": 100}],
        ),
        object(),
        principal,
    )
    anomaly_response = await agents.ops_anomaly_check(
        AnomalyCheckRequest(stat_date="2026-07-23"), object(), principal
    )
    proposal_response = await agents.ops_proposal(
        ProposalRequest(topic="增长", context="背景"), object(), principal
    )
    records_response = await agents.list_records(object(), principal, 5)

    assert daily_response["data"]["task_type"] == "daily_report"
    assert anomaly_response["data"]["alerts"][0]["metric"] == "dau"
    assert proposal_response["data"]["task_type"] == "proposal"
    assert records_response["data"][0]["id"] == str(report.id)
    assert records_response["data"][0]["my_score"] is None


async def test_role_routes_delegate_to_expert_management_and_audit(monkeypatch) -> None:
    principal = _principal()
    expert = _expert()
    audited = []

    async def list_roster(*args, **kwargs):
        return (expert,)

    async def create_expert(*args, **kwargs):
        assert kwargs["name"] == expert.name
        return expert

    async def update_expert(*args, **kwargs):
        assert kwargs["prompt_template"] == "新提示词"
        return expert

    async def append_audit(*args, **kwargs):
        audited.append(args[1])

    monkeypatch.setattr(agents.expert_operations, "list_roster", list_roster)
    monkeypatch.setattr(agents.expert_operations, "create_expert", create_expert)
    monkeypatch.setattr(agents.expert_operations, "update_expert", update_expert)
    monkeypatch.setattr(agents, "append_audit_record", append_audit)

    listed = await agents.list_roles(object(), principal)
    created = await agents.create_role(
        AgentRoleCreate(name=expert.name, prompt_template="提示词"),
        object(),
        principal,
    )
    updated = await agents.update_role(
        expert.expert_id,
        AgentRoleUpdate(prompt_template="新提示词"),
        object(),
        principal,
    )

    assert listed["data"][0]["name"] == expert.name
    assert created["data"]["tools"] == ["data_query"]
    assert updated["data"]["name"] == expert.name
    assert audited[0].action == "agent.prompt.apply"
    assert audited[0].target_id == expert.expert_id


async def test_skill_feedback_optimize_and_consult_routes_delegate(monkeypatch) -> None:
    principal = _principal()
    record_id = uuid.uuid4()
    role_id = uuid.uuid4()
    feedback_id = uuid.uuid4()

    async def capabilities():
        return (
            CapabilityDefinition(
                key="data_query",
                version="1.0",
                label="数据取数",
                description="只读查询",
                input_schema_json="{}",
                output_schema_json="{}",
                risk=CapabilityRisk.LOW,
                side_effect=CapabilitySideEffect.NONE,
                permission_keys=(),
                handler_identity="query",
            ),
        )

    async def feedback(*args, **kwargs):
        command = args[1]
        assert command.task_record_id == record_id
        return FeedbackResult(feedback_id, record_id, principal.id, 5, "好")

    async def optimize(*args, **kwargs):
        return PromptImprovementSuggestion(role_id, "旧", "新", 2)

    async def consult(*args, **kwargs):
        command = args[1]
        assert command.history[-1].content == "上一轮"
        return ConsultExpertResult("建议", "success", uuid.uuid4())

    monkeypatch.setattr(agents.capability_operations, "list_capabilities", capabilities)
    monkeypatch.setattr(agents.quality_operations, "record_feedback", feedback)
    monkeypatch.setattr(
        agents.quality_operations,
        "suggest_prompt_improvement",
        optimize,
    )
    monkeypatch.setattr(agents.agent_execution_operations, "consult_expert", consult)

    skills = await agents.list_skills(principal)
    feedback_response = await agents.add_feedback(
        record_id,
        FeedbackRequest(score=5, comment="好"),
        object(),
        principal,
    )
    optimized = await agents.optimize_prompt(role_id, object(), principal)
    consulted = await agents.consult(
        role_id,
        agents.ConsultRequest(
            message="请建议",
            history=[{"role": "ai", "content": "上一轮"}],
        ),
        object(),
        principal,
    )

    assert skills["data"][0]["key"] == "data_query"
    assert feedback_response["data"] == {"id": str(feedback_id), "score": 5}
    assert optimized["data"]["suggested_prompt"] == "新"
    assert consulted["data"] == {"reply": "建议", "status": "success"}
