"""运营提案能力（create_operational_proposal）单测（离线）——内部顾问输出·非红线：
- parse：解析 【运营提案】<议题>（上限 1）。
- execute：把议题交给运营总监助理产提案（经 execution_context.agent_runner 注入的假 runner +
  monkeypatch 专家查询），成功回 artifact + note、失败如实声明；★notify=False 无对外发送★。
  无 runner / 未配专家 → 如实声明未生成、不臆造。
- 注册表成员：文本可触发（legacy_executor）、进 AUTOMATIC（编排步免红线）、default_enabled=True。
全程 mock，不触真实 LLM/DB。

★架构：本技能对 app.agents 零静态依赖（改经注入 runner 运行子 Agent），断
app.agents→operational_analytics→agent_execution→app.agents 环。"""

from __future__ import annotations

import uuid

import pytest

from app.agents.contracts import ExecutionContext
from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.business.operational_analytics.entrypoints import agent_capability
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    AUTOMATIC_CAPABILITIES,
    requires_human_review,
)
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="运营助理", prompt_template="x", tools=[])


class _Record:
    """agent_runner 返回的 legacy 记录桩（agent_execution_result 按鸭子类型归一）。"""

    def __init__(self, status: str, output: str | None = None, err: str | None = None) -> None:
        self.status = status
        self.output_content = output
        self.error_msg = err


class _Expert:
    """_load_ops_director 返回的专家执行快照桩（execute 只透传给 runner）。"""


def _ctx(runner: object | None) -> ExecutionContext:
    return ExecutionContext(agent_runner=runner)


# ── parse（议题解析，上限 1）─────────────────────────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【运营提案】提升次留") == ["提升次留"]


def test_parse_caps_at_one() -> None:
    text = "\n".join(f"【运营提案】议题{i}" for i in range(3))
    assert agent_capability.parse(text) == ["议题0"]


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无提案指令") == []


def test_parse_requires_topic() -> None:
    assert agent_capability.parse("【运营提案】   ") == []


# ── execute：产提案回 artifact（notify=False 无对外发送）──────────
async def test_execute_produces_proposal_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[object, str, str, str]] = []
    expert = _Expert()

    async def _load(db: object) -> object:
        return expert

    async def _runner(db, role, *, task_type, input_summary, user_message, **kwargs):  # noqa: ANN001,ANN003
        seen.append((role, task_type, input_summary, user_message))
        return _Record("success", output="【提案】背景/目标/方案…")

    monkeypatch.setattr(agent_capability, "_load_ops_director", _load)
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【运营提案】提升次留",
        user_intent="Q3 次留下滑",
        execution_context=_ctx(_runner),
    )
    assert len(seen) == 1
    role, task_type, _summary, message = seen[0]
    assert role is expert and task_type == "proposal"
    assert "提升次留" in message and "Q3 次留下滑" in message  # 议题 + 参考信息入 prompt
    assert len(res.artifacts) == 1
    assert res.artifacts[0]["kind"] == "operational_proposal"
    assert res.artifacts[0]["topic"] == "提升次留"
    assert res.artifacts[0]["body"] == "【提案】背景/目标/方案…"
    assert any("已生成运营提案" in note for note in res.notes)


async def test_execute_reports_failure_without_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load(db: object) -> object:
        return _Expert()

    async def _runner(db, role, **kwargs):  # noqa: ANN001,ANN003
        return _Record("failed", err="模型超时")

    monkeypatch.setattr(agent_capability, "_load_ops_director", _load)
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【运营提案】X",
        execution_context=_ctx(_runner),
    )
    assert res.artifacts == []
    assert any("未生成" in note and "模型超时" in note for note in res.notes)


async def test_execute_without_runner_declares_unavailable() -> None:
    # 无注入 runner（对话未接编排）→ 如实声明未生成、不臆造、不抛错
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【运营提案】X",
        execution_context=_ctx(None),
    )
    assert res.artifacts == []
    assert any("未生成" in note for note in res.notes)


async def test_execute_without_expert_declares_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _load(db: object) -> object | None:
        return None  # 骨架未初始化

    monkeypatch.setattr(agent_capability, "_load_ops_director", _load)

    async def _runner(db, role, **kwargs):  # noqa: ANN001,ANN003
        raise AssertionError("未配置专家时不得调用 runner")

    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【运营提案】X",
        execution_context=_ctx(_runner),
    )
    assert res.artifacts == []
    assert any("未配置" in note for note in res.notes)


async def test_execute_no_directive_is_silent() -> None:
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "普通回复",
        execution_context=_ctx(object()),
    )
    assert res.notes == [] and res.artifacts == []


async def test_prompt_section_advertises() -> None:
    assert "【运营提案】" in await agent_capability.prompt_section()


# ── 注册表成员：文本可触发 · 非红线 · 默认启用 ───────────────────
def test_registry_membership_non_red_line_and_automatic() -> None:
    assert "create_operational_proposal" in REGISTRY
    skill = REGISTRY["create_operational_proposal"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is None  # 无机械步/结构化调用
    assert skill.default_on is True  # 默认启用（内部顾问输出）
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 仅默认集
    assert "create_operational_proposal" in keys  # 默认可用
    # 非红线：内部顾问输出不对外发送 → 进 AUTOMATIC，编排步免停真人
    assert "create_operational_proposal" in AUTOMATIC_CAPABILITIES
    assert requires_human_review("create_operational_proposal") is False
