"""留存知识库（knowledge_index）技能单测（离线）：指令解析与上限、执行落库/无归属跳过、
prompt_section 广告、免红线（进 AUTOMATIC_CAPABILITIES）、传输资格 EVENT_GATED、注册表成员。
仿 test_feishu_notify_skill.py，全程 mock，不触真实知识库写入。"""

import uuid

import pytest

from app.agents.contracts import ExecutionContext, SkillRequest
from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityTransport,
    capability_transport,
)
from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
    CAPABILITY_DEFINITIONS,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    requires_human_review,
)
from app.contexts.foundations.knowledge.knowledge_indexing import public as index_public
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints import (
    agent_capability,
)
from app.contexts.foundations.knowledge.wiki_management import public as wiki_public
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="运营助理", prompt_template="x", tools=[])


def _request(title: str = "月度经营报告", body: str = "结论...") -> SkillRequest:
    return SkillRequest(
        skill_key="knowledge_index",
        action_index=0,
        arguments={"title": title, "body": body},
    )


class _FakeDoc:
    file_name = "月度经营报告.md"


class _FakeBase:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


class _FakePort:
    def __init__(self) -> None:
        self.captured: IndexTextCommand | None = None

    async def index_text(self, command: IndexTextCommand) -> _FakeDoc:
        self.captured = command
        return _FakeDoc()


# ── parse（指令解析，零外部调用）────────────────────────────
def test_parse_single() -> None:
    text = "好的\n【留存知识库】标题：季度小结\n```\n第一行\n第二行\n```"
    assert agent_capability.parse(text) == [("季度小结", "第一行\n第二行")]


def test_parse_caps_at_two() -> None:
    block = "【留存知识库】标题：T{i}\n```\nB{i}\n```"
    text = "\n".join(block.replace("{i}", str(i)) for i in range(3))
    assert len(agent_capability.parse(text)) == 2


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无留存指令") == []


# ── execute（落库 / 无归属跳过）─────────────────────────────
async def test_execute_indexes_to_default_base(monkeypatch: pytest.MonkeyPatch) -> None:
    port, base = _FakePort(), _FakeBase()
    monkeypatch.setattr(index_public, "build_knowledge_index_port", lambda _s: port)

    async def _default_base(_s: object) -> _FakeBase:
        return base

    monkeypatch.setattr(wiki_public, "get_default_knowledge_base", _default_base)
    ctx = ExecutionContext(user_id=uuid.uuid4())
    res = await agent_capability.KnowledgeIndexSkillExecutor().execute(
        None, _role(), _request(), ctx  # type: ignore[arg-type]
    )
    assert port.captured is not None
    assert port.captured.title == "月度经营报告"
    assert port.captured.category == "report"
    assert port.captured.knowledge_base_id == base.id
    assert port.captured.uploader_id == ctx.user_id
    assert any("已留存到知识库" in note for note in res.notes)


async def test_execute_skips_without_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _boom(_s: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("无归属不应触达写侧端口")

    monkeypatch.setattr(index_public, "build_knowledge_index_port", _boom)
    res = await agent_capability.KnowledgeIndexSkillExecutor().execute(
        None, _role(), _request(), ExecutionContext(user_id=None)  # type: ignore[arg-type]
    )
    assert called is False
    assert any("已跳过留存" in note for note in res.notes)


# ── prompt_section（恒广告，内部写无凭证依赖）──────────────
async def test_prompt_section_advertises() -> None:
    assert "【留存知识库】" in await agent_capability.prompt_section()


# ── 免红线：内部写属辅助执行，进 AUTOMATIC_CAPABILITIES ─────
def test_knowledge_index_is_not_red_line() -> None:
    assert requires_human_review("knowledge_index") is False


# ── 传输资格：INTERNAL_WRITE → EVENT_GATED（同 collab）──────
def test_transport_is_event_gated() -> None:
    definition = next(d for d in CAPABILITY_DEFINITIONS if d.key == "knowledge_index")
    assert capability_transport(definition) is CapabilityTransport.EVENT_GATED


# ── 注册表成员（文本 + 结构化双路径、默认开）──────────────
def test_registry_membership() -> None:
    assert "knowledge_index" in REGISTRY
    skill = REGISTRY["knowledge_index"]
    assert skill.executor_factory is not None  # 结构化/编排步可调
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.default_on is True
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 默认全开
    assert "knowledge_index" in keys
