"""案例检索（knowledge_search）单测（离线）：查询解析与上限、命中回喂 / 空结果如实声明、
prompt_section 广告、search_visible 经 public 端口 + 可见范围检索、注册表成员（AUTOMATIC·非红线）。
仿 test_feishu_notify_person_skill.py，全程 mock，不连真实知识库/PG。"""

import uuid

import pytest

from app.agents.contracts import AgentSubject, ExecutionContext
from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    requires_human_review,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import KnowledgeHit
from app.contexts.foundations.knowledge.knowledge_search.entrypoints import (
    agent_capability,
    operations,
)
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="舆情助理", prompt_template="x", tools=[])


def _subject() -> AgentSubject:
    return AgentSubject(expert_id=uuid.uuid4(), name="舆情助理", department_id=uuid.uuid4())


def _hit(
    name: str = "2024竞品降价应对纪要", content: str = "统一口径后 48h 内响应"
) -> KnowledgeHit:
    return KnowledgeHit(
        document_id=uuid.uuid4(),
        document_name=name,
        chunk_index=0,
        content=content,
        score_distance=0.1,
    )


# ── parse（查询解析，零外部调用）──────────────────────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【检索案例】竞品降价应对") == ["竞品降价应对"]


def test_parse_caps_at_two() -> None:
    text = "\n".join(f"【检索案例】查询{i}" for i in range(3))
    assert agent_capability.parse(text) == ["查询0", "查询1"]


def test_parse_stops_at_line_end() -> None:
    assert agent_capability.parse("【检索案例】只查这句\n这行是普通正文") == ["只查这句"]


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无检索指令") == []


# ── execute：命中回喂 / 空结果如实声明（不臆造）─────────────────────
async def test_execute_no_hits_states_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _search(db, subject, query, top_k=5):  # type: ignore[no-untyped-def]
        return ()

    monkeypatch.setattr(operations, "search_visible", _search)
    res = await agent_capability.execute(None, _role(), "【检索案例】不存在的事件")  # type: ignore[arg-type]
    assert any("未检索到同类历史案例" in note for note in res.notes)
    assert res.datasets == []


async def test_execute_hits_recorded_and_no_runner_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _search(db, subject, query, top_k=5):  # type: ignore[no-untyped-def]
        return (_hit(),)

    monkeypatch.setattr(operations, "search_visible", _search)
    # 无 AgentRunner → 命中入 datasets 但走「缺少 AgentRunner」note，不崩。
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【检索案例】竞品降价",
        execution_context=ExecutionContext(agent_runner=None),
    )
    assert len(res.datasets) == 1
    assert res.datasets[0]["hits"][0]["document_name"] == "2024竞品降价应对纪要"
    assert any("缺少 AgentRunner" in note for note in res.notes)


async def test_execute_no_directive_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _search(db, subject, query, top_k=5):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return (_hit(),)

    monkeypatch.setattr(operations, "search_visible", _search)
    res = await agent_capability.execute(None, _role(), "普通回复")  # type: ignore[arg-type]
    assert res.datasets == [] and res.notes == [] and called is False


# ── render / prompt_section ───────────────────────────────────────
def test_render_hits() -> None:
    text = agent_capability.render_hits((_hit(),))
    assert "《2024竞品降价应对纪要》" in text and "统一口径" in text


async def test_prompt_section_advertises() -> None:
    section = await agent_capability.prompt_section()
    assert "【检索案例】" in section


# ── search_visible 经 public 端口 + 可见范围（跨 Context 只走门面）──
async def test_search_visible_scopes_and_uses_port(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    kb_id = uuid.uuid4()

    async def _visible(session, *, department_id, owner_agent_id):  # type: ignore[no-untyped-def]
        seen["owner"] = owner_agent_id
        return [kb_id]

    class _Port:
        async def search(self, query):  # type: ignore[no-untyped-def]
            seen["kb"] = query.visible_knowledge_base_ids
            seen["q"] = query.query

            class _R:
                hits = (_hit(),)

            return _R()

    monkeypatch.setattr(operations, "agent_visible_knowledge_base_ids", _visible)
    monkeypatch.setattr(operations, "build_knowledge_search_port", lambda session: _Port())
    subject = _subject()
    hits = await operations.search_visible(None, subject, "竞品降价")  # type: ignore[arg-type]
    assert len(hits) == 1
    assert seen["owner"] == subject.expert_id  # 归属 agent = subject.expert_id
    assert seen["kb"] == (kb_id,)
    assert seen["q"] == "竞品降价"


# ── 注册表成员 + AUTOMATIC（只读·无真人停点）────────────────────────
def test_registry_membership_and_automatic() -> None:
    assert "knowledge_search" in REGISTRY
    skill = REGISTRY["knowledge_search"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is not None  # 结构化步亦可调
    assert skill.default_on is True  # 默认启用（只读检索）
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 默认集
    assert "knowledge_search" in keys
    # 只读检索无对外效果 → 进 AUTOMATIC_CAPABILITIES → 编排步免真人停点。
    assert requires_human_review("knowledge_search") is False
