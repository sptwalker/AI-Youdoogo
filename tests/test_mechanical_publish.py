"""跨模块机械发布编排（feishu_publish）红线单测（离线·全 mock，不发真实飞书请求）：

- pair_publish_steps：为 compose 步配对机械发布步 / 无 compose 时不动 / 剔除上游混入的裸 publish 步
- 策略：feishu_publish 非红线且 is_mechanical；compose_feishu 仍红线（停真人验收）
- ready_steps 门控（红线核心）：发布步在 compose 步被真人验收（SUCCEEDED）前结构性无法就绪
- ExecuteWorkflowStep 机械分支：跳过 agent，直调能力端口
- 能力适配器机械分支：有草稿+已配 → run_publish；未配凭证 → 跳过，绝不触发对外写
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionResult,
    AgentExecutionStatus,
    ExecutionTrace,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    WorkflowAgentExecutionPort,
    WorkflowCapabilityExecutionPort,
)
from app.contexts.foundations.execution.workflow_runtime.application.step_execution import (
    ExecuteWorkflowStep,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    ExecuteWorkflowStepResult,
    PreparedWorkflowStep,
    WorkflowLaunchStep,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    is_mechanical,
    pair_publish_steps,
    requires_human_review,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.legacy_execution import (
    _LegacyCapabilityExecutionAdapter,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.step_leases import (
    ready_steps,
)
from app.models.workflow import (
    STEP_QUEUED,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowStep,
)


def _launch(no: int, key: str, deps: tuple[int, ...] = ()) -> WorkflowLaunchStep:
    return WorkflowLaunchStep(
        number=no, title=f"步骤{no}", capability_key=key, instruction="做事", depends_on=deps
    )


def _synthetic() -> AgentExecutionResult:
    return AgentExecutionResult(status=AgentExecutionStatus.SUCCEEDED, trace=ExecutionTrace())


def _prepared(
    capability_key: str, input_data: tuple[tuple[str, object], ...] = ()
) -> PreparedWorkflowStep:
    claim = ClaimedWorkflowStep(
        workflow_id=uuid.uuid4(),
        step_id=uuid.uuid4(),
        task_card_id=None,
        expert_id=None,
        worker_id="w",
        attempt=1,
        version=0,
        lease_until=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return PreparedWorkflowStep(
        claim=claim,
        trace_id=uuid.uuid4(),
        creator_id=uuid.uuid4(),
        request_text="req",
        title="发布",
        capability_key=capability_key,
        instruction="做事",
        expert=None,
        input_data=input_data,
    )


# ── pair_publish_steps（配对，纯函数）────────────────────────────
def test_pairing_appends_publish_step() -> None:
    steps = (_launch(1, "data_query"), _launch(2, "compose_feishu", (1,)))
    paired = pair_publish_steps(steps)
    assert [s.capability_key for s in paired] == [
        "data_query",
        "compose_feishu",
        "feishu_publish",
    ]
    assert paired[-1].depends_on == (2,)  # 发布步依赖 compose 步


def test_pairing_strips_stray_bare_publish() -> None:
    # 上游若混入裸 feishu_publish 步一律丢弃，配对只由本函数生成（防绕过真人停点）
    steps = (_launch(1, "compose_feishu"), _launch(2, "feishu_publish", (1,)))
    paired = pair_publish_steps(steps)
    assert sum(s.capability_key == "feishu_publish" for s in paired) == 1


def test_pairing_noop_without_compose() -> None:
    steps = (_launch(1, "data_query"), _launch(2, "deliver", (1,)))
    assert pair_publish_steps(steps) == steps


# ── 策略（红线归属）────────────────────────────────────────────
def test_publish_is_mechanical_not_red_line() -> None:
    assert is_mechanical("feishu_publish") is True
    assert requires_human_review("feishu_publish") is False  # 机械步不再二次停点
    assert requires_human_review("compose_feishu") is True  # compose 仍红线停真人验收


# ── ready_steps 门控（红线核心：真人验收前发布步不就绪）──────────
def test_ready_steps_gate_publish_until_compose_accepted() -> None:
    compose_id = uuid.uuid4()
    compose = WorkflowStep(id=compose_id, status=STEP_WAITING_HUMAN, depends_on=[])
    publish = WorkflowStep(
        id=uuid.uuid4(), status=STEP_QUEUED, depends_on=[str(compose_id)]
    )
    # compose 停在 WAITING_HUMAN（红线）→ publish 结构性未就绪
    assert publish not in ready_steps([compose, publish])
    # 真人验收 → compose SUCCEEDED → publish 方就绪
    compose.status = STEP_SUCCEEDED
    assert publish in ready_steps([compose, publish])


# ── ExecuteWorkflowStep 机械分支（跳过 agent）────────────────────
async def test_execute_workflow_step_mechanical_skips_agent() -> None:
    calls = {"agent": 0, "cap": 0}

    class _Agents:
        async def execute(self, request: Any) -> AgentExecutionResult:
            calls["agent"] += 1
            raise AssertionError("机械发布步不得调用 agent")

    class _Caps:
        async def execute(
            self, prepared: PreparedWorkflowStep, agent_result: AgentExecutionResult
        ) -> ExecuteWorkflowStepResult:
            calls["cap"] += 1
            return ExecuteWorkflowStepResult(succeeded=True, content="ok")

    use_case = ExecuteWorkflowStep(
        cast(WorkflowAgentExecutionPort, _Agents()),
        cast(WorkflowCapabilityExecutionPort, _Caps()),
    )
    res = await use_case.execute(_prepared("feishu_publish"))
    assert calls == {"agent": 0, "cap": 1}
    assert res.succeeded is True


# ── 能力适配器机械分支（有草稿+已配 → 发；未配 → 跳过）────────────
class _FakePublisher:
    def __init__(self, available: bool) -> None:
        self._available = available
        self.published: list[dict[str, Any]] = []

    async def available(self) -> bool:
        return self._available

    async def publish(self, draft: dict[str, object]) -> dict[str, object]:
        self.published.append(dict(draft))
        return {"ok": True}


async def test_mechanical_publish_sends_when_configured() -> None:
    publisher = _FakePublisher(available=True)
    draft = {"publish_key": "feishu_publish", "kind": "docx", "title": "月报"}
    other = {"publish_key": "send_email_publish", "kind": "email"}  # 不匹配本步键 → 忽略
    adapter = _LegacyCapabilityExecutionAdapter(
        cast(Any, None), cast(Any, None), cast(Any, publisher)
    )
    res = await adapter.execute(
        _prepared("feishu_publish", (("artifacts", [draft, other]),)), _synthetic()
    )
    assert publisher.published == [draft]
    assert res.succeeded is True and "已发布 1" in res.content


async def test_mechanical_publish_skips_when_unconfigured() -> None:
    publisher = _FakePublisher(available=False)
    adapter = _LegacyCapabilityExecutionAdapter(
        cast(Any, None), cast(Any, None), cast(Any, publisher)
    )
    res = await adapter.execute(
        _prepared(
            "feishu_publish",
            (("artifacts", [{"publish_key": "feishu_publish", "kind": "docx"}]),),
        ),
        _synthetic(),
    )
    assert publisher.published == []  # 未配置凭证 → 绝不触发对外写
    assert res.succeeded is True and "跳过发布" in res.content
