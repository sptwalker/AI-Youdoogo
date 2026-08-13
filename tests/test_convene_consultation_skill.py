"""紧急会商编排（convene_consultation）单测（离线）——红线两步拆分（compose→机械会商）：
- compose `parse`/`execute`：解析 【紧急会商】议题 → 草稿 artifact（带 topic + 嵌入 creator_id），
  ★零建会、零通知★，回「待验收」note。
- 机械会商半（`convene_consultation_publish`）：进 MECHANICAL/AUTOMATIC、不入 REGISTRY、对规划
  器不可见；由 pair_publish_steps 配对 compose 步生成，注入 publisher 按 publish_key 派发真建会 +
  四部门定位通知（无 session/user_id，自开 session，读 draft 嵌入的 creator_id）。
- operations.convene：建会 + 按 dept code 解析四部门负责人 + 缺失安全跳过（不臆造），定位人回吐。
全程 mock，不建真会议、不发真实飞书。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.agents.skill_registry import REGISTRY, enabled_skills
from app.bootstrap import workflow_events
from app.bootstrap.workflow_events import _FeishuMechanicalPublisher
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowLaunchStep,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    AUTOMATIC_CAPABILITIES,
    MECHANICAL_CAPABILITIES,
    is_mechanical,
    pair_publish_steps,
    requires_human_review,
)
from app.contexts.foundations.integration.convene_consultation.entrypoints import (
    agent_capability,
    operations,
)
from app.contexts.foundations.organization_structure.public import (
    DepartmentSnapshot,
    OrganizationSnapshot,
    OrganizationTreeNodeSnapshot,
)
from app.models.agent import AgentRole

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="会商编排助理", prompt_template="x", tools=[])


def _department(code: str, supervisor_user_id: uuid.UUID | None) -> DepartmentSnapshot:
    return DepartmentSnapshot(
        department_id=uuid.uuid4(),
        version="v1",
        name=code,
        code=code,
        node_type="department",
        level=1,
        path=f"/{code}",
        parent_id=None,
        supervisor_user_id=supervisor_user_id,
        sort_order=0,
        create_time=NOW,
    )


class _User:
    def __init__(self, feishu_open_id: str | None, email: str | None = None) -> None:
        self.id = uuid.uuid4()
        self.feishu_open_id = feishu_open_id
        self.email = email


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


# ── parse（议题 → 草稿 dict，零外部调用）──────────────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【紧急会商】线下门店客诉激增") == [
        {
            "kind": "convene_consultation",
            "publish_key": "convene_consultation_publish",
            "topic": "线下门店客诉激增",
        }
    ]


def test_parse_caps_at_one() -> None:
    text = "\n".join(f"【紧急会商】议题{i}" for i in range(3))
    drafts = agent_capability.parse(text)
    assert [d["topic"] for d in drafts] == ["议题0"]


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无会商指令") == []


def test_parse_requires_topic() -> None:
    assert agent_capability.parse("【紧急会商】   ") == []


# ── compose execute()：产草稿 + 嵌 creator_id + 待验收 note，★零建会、零通知★──
async def test_execute_produces_draft_without_convening(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _convene(db, *, topic, creator_id):  # 不应被调用
        raise AssertionError("compose 步不得建会")

    monkeypatch.setattr(operations, "convene", _convene)
    user_id = uuid.uuid4()
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【紧急会商】线下门店客诉激增",
        user_id=user_id,
    )
    assert len(res.artifacts) == 1
    assert res.artifacts[0]["publish_key"] == "convene_consultation_publish"
    assert res.artifacts[0]["topic"] == "线下门店客诉激增"
    # 机械会商步只拿到 draft → compose 必须把发起人嵌进草稿供其建会
    assert res.artifacts[0]["creator_id"] == str(user_id)
    assert any("草稿" in note and "验收" in note for note in res.notes)


async def test_execute_without_user_id_omits_creator() -> None:
    res = await agent_capability.execute(None, _role(), "【紧急会商】舆情")  # type: ignore[arg-type]
    assert len(res.artifacts) == 1
    assert "creator_id" not in res.artifacts[0]  # 无发起人不臆造


async def test_execute_no_directive_is_silent() -> None:
    res = await agent_capability.execute(None, _role(), "普通回复")  # type: ignore[arg-type]
    assert res.notes == [] and res.artifacts == []


# ── convene()：建会 + 按 dept code 解析四部门 + 缺失安全跳过（不臆造）──
async def test_convene_notifies_all_departments_when_data_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    added_discussions: list[str] = []

    async def _create_meeting(session, *, title, creator_id, meeting_type, initial_status=None):
        assert meeting_type == "consultation"
        assert initial_status == "in_progress"
        return type("R", (), {"id": meeting_id})()

    async def _add_discussion(session, mid, *, speaker_id, speaker_name, content):
        added_discussions.append(content)

    async def _get_snapshot(session):
        departments = [
            _department(code, uuid.uuid4()) for code in operations.TARGET_DEPARTMENT_CODES
        ]
        nodes = tuple(
            OrganizationTreeNodeSnapshot(department=dept, employee_count=1, children=())
            for dept in departments
        )
        return OrganizationSnapshot(version="v1", roots=nodes)

    async def _get_user_by_id(session, *, user_id):
        return _User(feishu_open_id="ou_abc", email="dir@x.com")

    async def _send_to_recipient(recipient, is_chat, text):
        return True

    monkeypatch.setattr(operations.meetings, "create_meeting", _create_meeting)
    monkeypatch.setattr(operations.meetings, "add_discussion", _add_discussion)
    monkeypatch.setattr(operations.organization, "get_snapshot", _get_snapshot)
    monkeypatch.setattr(operations.identity, "get_user_by_id", _get_user_by_id)
    monkeypatch.setattr(operations.feishu_notify_person, "send_to_recipient", _send_to_recipient)

    result = await operations.convene(None, topic="紧急舆情", creator_id=creator_id)  # type: ignore[arg-type]

    assert result.meeting_id == meeting_id
    assert set(result.notified) == set(operations.TARGET_DEPARTMENT_CODES)
    assert result.skipped == ()
    assert added_discussions == ["紧急会商议题：紧急舆情"]
    # 四部门负责人齐全 → 四位与会人 + 四个邮箱一并回吐（供下游纪要/邮件步）
    assert len(result.participant_user_ids) == 4
    assert result.participant_emails == ("dir@x.com",) * 4


async def test_convene_skips_missing_department_and_missing_feishu_without_fabricating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """品牌部未配置、销售部无负责人、产品部负责人无飞书、法务部齐全 → 三条如实跳过说明。"""
    meeting_id = uuid.uuid4()
    codes = operations.TARGET_DEPARTMENT_CODES  # (brand, marketing, product_base, legal)

    async def _create_meeting(session, *, title, creator_id, meeting_type, initial_status=None):
        return type("R", (), {"id": meeting_id})()

    async def _add_discussion(session, mid, *, speaker_id, speaker_name, content):
        return None

    product_supervisor = uuid.uuid4()
    legal_supervisor = uuid.uuid4()

    async def _get_snapshot(session):
        marketing = _department(codes[1], None)  # 无负责人
        product = _department(codes[2], product_supervisor)  # 负责人无飞书
        legal = _department(codes[3], legal_supervisor)  # 齐全
        # 品牌部（codes[0]）故意不放进树 → 未配置
        nodes = tuple(
            OrganizationTreeNodeSnapshot(department=dept, employee_count=1, children=())
            for dept in (marketing, product, legal)
        )
        return OrganizationSnapshot(version="v1", roots=nodes)

    async def _get_user_by_id(session, *, user_id):
        if user_id == product_supervisor:
            return _User(feishu_open_id=None, email="prod@x.com")  # 无飞书但有邮箱
        return _User(feishu_open_id="ou_legal", email="legal@x.com")

    async def _send_to_recipient(recipient, is_chat, text):
        return True

    monkeypatch.setattr(operations.meetings, "create_meeting", _create_meeting)
    monkeypatch.setattr(operations.meetings, "add_discussion", _add_discussion)
    monkeypatch.setattr(operations.organization, "get_snapshot", _get_snapshot)
    monkeypatch.setattr(operations.identity, "get_user_by_id", _get_user_by_id)
    monkeypatch.setattr(operations.feishu_notify_person, "send_to_recipient", _send_to_recipient)

    result = await operations.convene(None, topic="紧急舆情", creator_id=uuid.uuid4())  # type: ignore[arg-type]

    assert result.notified == (codes[3],)  # 仅法务真通知
    assert result.skipped == (
        f"{codes[0]}部门未配置",
        f"{codes[1]}部门负责人未配置",
        f"{codes[2]}部门负责人无飞书",
    )
    # 定位到负责人即入会（无飞书只是不发通知）→ 产品 + 法务两位与会人 + 两个邮箱
    assert len(result.participant_user_ids) == 2
    assert set(result.participant_emails) == {"prod@x.com", "legal@x.com"}


# ── 机械会商步（_FeishuMechanicalPublisher 按 publish_key 派发，自开 session 真建会）──
def _draft(topic: str = "线下门店客诉激增", creator_id: str | None = "seeded") -> dict:
    draft: dict = {
        "kind": "convene_consultation",
        "publish_key": "convene_consultation_publish",
        "topic": topic,
    }
    if creator_id is not None:
        draft["creator_id"] = creator_id if creator_id != "seeded" else str(uuid.uuid4())
    return draft


async def test_publisher_convenes_and_emits_meeting_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meeting_id = uuid.uuid4()
    p1, p2 = uuid.uuid4(), uuid.uuid4()

    async def _convene(session, *, topic, creator_id):
        assert topic == "线下门店客诉激增"
        return operations.ConsultationResult(
            meeting_id=meeting_id,
            notified=("dept_legal",),
            skipped=("dept_brand部门未配置",),
            participant_user_ids=(p1, p2),
            participant_emails=("a@x.com", "b@x.com"),
        )

    monkeypatch.setattr(operations, "convene", _convene)
    monkeypatch.setattr(workflow_events, "async_session_factory", _FakeSession)
    out = await _FeishuMechanicalPublisher().publish(_draft())

    # 结构化 meeting 数据供下游 generate_minutes / send_email 步消费
    assert out["kind"] == "meeting"
    assert out["meeting_id"] == str(meeting_id)
    assert out["participant_user_ids"] == [str(p1), str(p2)]
    assert out["participant_emails"] == ["a@x.com", "b@x.com"]
    assert out["notified"] == ["dept_legal"]
    assert out["skipped"] == ["dept_brand部门未配置"]


async def test_publisher_without_creator_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _convene(session, *, topic, creator_id):
        raise AssertionError("缺 creator_id 不得建会")

    monkeypatch.setattr(operations, "convene", _convene)
    monkeypatch.setattr(workflow_events, "async_session_factory", _FakeSession)
    out = await _FeishuMechanicalPublisher().publish(_draft(creator_id=None))
    assert out["kind"] == "convene_consultation_skipped"


# ── prompt_section（无门控，随能力授予即可见）─────────────────────
async def test_prompt_section_advertises() -> None:
    section = await agent_capability.prompt_section()
    assert "【紧急会商】" in section


# ── 注册表成员 + 红线 + 机械配对 ─────────────────────────────────
def test_compose_registry_membership_and_red_line() -> None:
    assert "convene_consultation" in REGISTRY
    skill = REGISTRY["convene_consultation"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is None  # compose 无结构化/机械步调用
    assert skill.default_on is False  # 默认不启用，需管理员显式授予
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 仅默认集
    assert "convene_consultation" not in keys  # 非默认启用
    # 红线：跨部门紧急会商编排对外触达不在 AUTOMATIC_CAPABILITIES → 编排步执行前必停 waiting_human
    assert requires_human_review("convene_consultation") is True


def test_publish_key_is_mechanical_and_invisible() -> None:
    # 机械会商键：不入 REGISTRY（镜像 feishu_notify_person_publish），对规划器/对话不可见
    assert "convene_consultation_publish" not in REGISTRY
    assert is_mechanical("convene_consultation_publish") is True
    assert "convene_consultation_publish" in MECHANICAL_CAPABILITIES
    # 机械会商步草稿已真人验收 → 免二次红线（进 AUTOMATIC）
    assert "convene_consultation_publish" in AUTOMATIC_CAPABILITIES
    assert requires_human_review("convene_consultation_publish") is False


def test_compose_step_pairs_mechanical_publish() -> None:
    compose = WorkflowLaunchStep(
        number=1,
        title="整理紧急会商草稿",
        capability_key="convene_consultation",
        instruction="把研判议题整理成会商草稿",
        depends_on=(),
    )
    paired = pair_publish_steps((compose,))
    assert [s.capability_key for s in paired] == [
        "convene_consultation",
        "convene_consultation_publish",
    ]
    publish = paired[1]
    assert publish.depends_on == (compose.number,)  # 依赖 compose → 验收前结构性不就绪
