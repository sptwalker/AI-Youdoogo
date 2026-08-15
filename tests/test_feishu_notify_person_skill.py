"""定向飞书通知（feishu_notify_person）单测（离线）——红线两步拆分（compose→机械发布）：
- compose `parse`/`execute`：解析 【定向飞书】收件人|正文 → 草稿 artifact，★零飞书调用★，
  回「待验收」note；open_id/chat_id 按前缀路由。
- 机械发布半（`feishu_notify_person_publish`）：进 MECHANICAL/AUTOMATIC、不入 REGISTRY、对规划器
  不可见；由 pair_publish_steps 配对 compose 步生成，注入 publisher 按 publish_key 派发真发。
- 红线：compose 不在 AUTOMATIC → 编排步执行前必停 waiting_human；机械步草稿已验收 → 免二次红线。
自门控（prompt_section 按开关）、send_to_recipient 透传 notify、publisher 派发亦覆盖。全程 mock，
不发真实飞书。"""

import uuid

import pytest

from app.agents.skill_registry import REGISTRY, enabled_skills
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
from app.contexts.foundations.integration.feishu_notify_person.entrypoints import (
    agent_capability,
    operations,
)
from app.core import runtime_config
from app.integrations.feishu import notify
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="通知助理", prompt_template="x", tools=[])


# ── parse（收件人|正文 → 草稿 dict，零外部调用）──────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【定向飞书】ou_abc|简报已生成") == [
        {
            "kind": "feishu_notify_person",
            "publish_key": "feishu_notify_person_publish",
            "recipient": "ou_abc",
            "is_chat": False,
            "text": "简报已生成",
        }
    ]


def test_parse_caps_at_three() -> None:
    text = "\n".join(f"【定向飞书】ou_{i}|通知{i}" for i in range(4))
    drafts = agent_capability.parse(text)
    assert [(d["recipient"], d["text"]) for d in drafts] == [
        ("ou_0", "通知0"),
        ("ou_1", "通知1"),
        ("ou_2", "通知2"),
    ]


def test_parse_stops_at_line_end() -> None:
    # `.` 默认不跨行 → 只吃本行，不吞并下一行普通正文
    drafts = agent_capability.parse("【定向飞书】oc_g|只发这句\n这行是普通正文")
    assert len(drafts) == 1
    assert drafts[0]["recipient"] == "oc_g" and drafts[0]["text"] == "只发这句"
    assert drafts[0]["is_chat"] is True  # oc_ → 群


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无定向指令") == []


def test_parse_requires_recipient_and_body() -> None:
    # 缺 `|` 或正文空 → 不成条
    assert agent_capability.parse("【定向飞书】ou_abc") == []
    assert agent_capability.parse("【定向飞书】ou_abc|   ") == []


def test_is_chat_routes_by_prefix() -> None:
    assert agent_capability._is_chat("oc_group") is True
    assert agent_capability._is_chat("ou_person") is False


# ── compose execute()：只产草稿 + 待验收 note，★零飞书调用★──────────
async def test_execute_produces_draft_without_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = False

    async def _send(recipient: str, is_chat: bool, text: str) -> bool:  # 不应被调用
        nonlocal sent
        sent = True
        return True

    monkeypatch.setattr(operations, "send_to_recipient", _send)
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【定向飞书】ou_p|给个人\n【定向飞书】oc_g|给群",
    )
    assert sent is False  # compose 步零外部调用
    assert len(res.artifacts) == 2
    assert res.artifacts[0]["publish_key"] == "feishu_notify_person_publish"
    assert any("草稿" in note and "验收" in note for note in res.notes)


async def test_execute_no_directive_is_silent() -> None:
    res = await agent_capability.execute(None, _role(), "普通回复")  # type: ignore[arg-type]
    assert res.notes == [] and res.artifacts == []


# ── 机械发布：注入 publisher 按 publish_key 派发（读已验收草稿 → 真发）──
def _draft(recipient: str = "ou_abc", is_chat: bool = False) -> dict:
    return {
        "kind": "feishu_notify_person",
        "publish_key": "feishu_notify_person_publish",
        "recipient": recipient,
        "is_chat": is_chat,
        "text": "简报已生成",
    }


async def test_publisher_dispatches_notify_person(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool, str]] = []

    async def _send(recipient: str, is_chat: bool, text: str) -> bool:
        calls.append((recipient, is_chat, text))
        return True

    monkeypatch.setattr(operations, "send_to_recipient", _send)
    out = await _FeishuMechanicalPublisher().publish(_draft("oc_g", is_chat=True))
    assert calls == [("oc_g", True, "简报已生成")]
    assert out["kind"] == "feishu_notify_person_sent"


async def test_publisher_skips_without_fabricating(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _send(recipient: str, is_chat: bool, text: str) -> bool:
        return False  # 开关关/收件人无效 → notify no-op

    monkeypatch.setattr(operations, "send_to_recipient", _send)
    out = await _FeishuMechanicalPublisher().publish(_draft())
    # 计成功（回 artifact）不空转重试，但如实标记未发出
    assert out["kind"] == "feishu_notify_person_skipped"


async def test_publisher_available_follows_notify_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _output_unavailable() -> bool:
        return False

    from app.contexts.foundations.integration.feishu_output.entrypoints import (
        operations as feishu_output_ops,
    )

    monkeypatch.setattr(feishu_output_ops, "feishu_output_available", _output_unavailable)
    monkeypatch.setattr(operations, "feishu_notify_person_available", lambda: True)
    assert await _FeishuMechanicalPublisher().available() is True
    monkeypatch.setattr(operations, "feishu_notify_person_available", lambda: False)
    assert await _FeishuMechanicalPublisher().available() is False


# ── 自门控（prompt_section 按开关门控）────────────────────────────
async def test_prompt_section_advertises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operations, "feishu_notify_person_available", lambda: True)
    section = await agent_capability.prompt_section()
    assert "【定向飞书】" in section


async def test_prompt_section_gated_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operations, "feishu_notify_person_available", lambda: False)
    assert await agent_capability.prompt_section() == ""


def test_available_follows_enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "effective", lambda key, default="": "true")
    assert operations.feishu_notify_person_available() is True
    monkeypatch.setattr(runtime_config, "effective", lambda key, default="": "false")
    assert operations.feishu_notify_person_available() is False


# ── send_to_recipient 透传 notify（个人走 user、群走 chat）────────
async def test_send_delegates_to_user_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _user(open_id: str, text: str) -> bool:
        seen.append(f"user:{open_id}:{text}")
        return True

    async def _chat(chat_id: str, text: str) -> bool:
        seen.append(f"chat:{chat_id}:{text}")
        return True

    monkeypatch.setattr(notify, "send_text_to_user", _user)
    monkeypatch.setattr(notify, "send_text_to_chat", _chat)
    assert await operations.send_to_recipient("ou_p", False, "hi") is True
    assert await operations.send_to_recipient("oc_g", True, "yo") is True
    assert seen == ["user:ou_p:hi", "chat:oc_g:yo"]


# ── B2.3 番茄钟单点拦截（仅影响发给本人的通知，不改对外红线）──────────
async def test_send_intercepted_during_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.contexts.business.time_management import public as tm_public

    sent = False

    async def _user(open_id: str, text: str) -> bool:
        nonlocal sent
        sent = True
        return True

    async def _intercepting(session: object, user_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(notify, "send_text_to_user", _user)
    monkeypatch.setattr(tm_public, "is_user_focus_intercepting", _intercepting)
    result = await operations.send_to_recipient(
        "ou_self", False, "别打扰", session=object(), recipient_user_id=uuid.uuid4()
    )
    assert result is False and sent is False  # 专注期内发给本人 → 被跳过


async def test_send_proceeds_when_not_focusing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.contexts.business.time_management import public as tm_public

    async def _user(open_id: str, text: str) -> bool:
        return True

    async def _not_intercepting(session: object, user_id: uuid.UUID) -> bool:
        return False

    monkeypatch.setattr(notify, "send_text_to_user", _user)
    monkeypatch.setattr(tm_public, "is_user_focus_intercepting", _not_intercepting)
    result = await operations.send_to_recipient(
        "ou_self", False, "在线提醒", session=object(), recipient_user_id=uuid.uuid4()
    )
    assert result is True  # 非专注期正常发送


async def test_outbound_send_never_checks_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    # 对外定向发送（不带本人身份）→ 绝不触发拦截判定，红线路径不受影响
    from app.contexts.business.time_management import public as tm_public

    checked = False

    async def _user(open_id: str, text: str) -> bool:
        return True

    async def _spy(session: object, user_id: uuid.UUID) -> bool:
        nonlocal checked
        checked = True
        return True

    monkeypatch.setattr(notify, "send_text_to_user", _user)
    monkeypatch.setattr(tm_public, "is_user_focus_intercepting", _spy)
    assert await operations.send_to_recipient("ou_other", False, "对外通知") is True
    assert checked is False  # 未提供 recipient_user_id → 不判专注拦截


# ── 注册表成员 + 红线 + 机械配对 ─────────────────────────────────
def test_compose_registry_membership_and_red_line() -> None:
    assert "feishu_notify_person" in REGISTRY
    skill = REGISTRY["feishu_notify_person"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is None  # compose 无结构化/机械步调用
    assert skill.default_on is False  # 默认不启用，需管理员显式授予
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 仅默认集
    assert "feishu_notify_person" not in keys  # 非默认启用
    # 红线：点对点对外触达不在 AUTOMATIC_CAPABILITIES → 编排步执行前必停 waiting_human
    assert requires_human_review("feishu_notify_person") is True


def test_publish_key_is_mechanical_and_invisible() -> None:
    # 机械发布键：不入 REGISTRY（镜像 feishu_publish），对规划器/对话不可见
    assert "feishu_notify_person_publish" not in REGISTRY
    assert is_mechanical("feishu_notify_person_publish") is True
    assert "feishu_notify_person_publish" in MECHANICAL_CAPABILITIES
    # 机械发布步草稿已真人验收 → 免二次红线（进 AUTOMATIC）
    assert "feishu_notify_person_publish" in AUTOMATIC_CAPABILITIES
    assert requires_human_review("feishu_notify_person_publish") is False


def test_compose_step_pairs_mechanical_publish() -> None:
    compose = WorkflowLaunchStep(
        number=1,
        title="整理定向飞书草稿",
        capability_key="feishu_notify_person",
        instruction="把结论整理成定向飞书草稿",
        depends_on=(),
    )
    paired = pair_publish_steps((compose,))
    assert [s.capability_key for s in paired] == [
        "feishu_notify_person",
        "feishu_notify_person_publish",
    ]
    publish = paired[1]
    assert publish.depends_on == (compose.number,)  # 依赖 compose → 验收前结构性不就绪
