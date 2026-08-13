"""发送邮件编排（send_email）单测（离线）——红线两步拆分（compose→机械发送）：
- compose `parse`/`execute`：解析发信指令 → 草稿 artifact，★零发送★，回待验收 note；
  收件人按 username 发布时解析邮箱，故不嵌 creator_id。
- 机械发送半（`send_email_publish`）：进 MECHANICAL/AUTOMATIC、不入 REGISTRY、对规划器不可见；
  由 pair_publish_steps 配对 compose 步生成，注入 publisher 按 publish_key 派发（自开 session）。
- operations.send_to_username：按 username 解析邮箱 + 缺配置/缺账号/缺邮箱如实跳过（不臆造地址）。
全程 mock，不连真 SMTP、不发真实邮件。"""

from __future__ import annotations

import uuid

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
from app.contexts.foundations.integration.send_email.entrypoints import (
    agent_capability,
    operations,
)
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="发信助理", prompt_template="x", tools=[])


class _User:
    def __init__(self, email: str | None) -> None:
        self.id = uuid.uuid4()
        self.email = email


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


# ── parse（账号|主题|正文 → 草稿 dict，零外部调用）────────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【发送邮件】alice|周报|本周进展如下") == [
        {
            "kind": "email",
            "publish_key": "send_email_publish",
            "username": "alice",
            "subject": "周报",
            "body": "本周进展如下",
        }
    ]


def test_parse_multiline_body() -> None:
    text = "【发送邮件】bob|会议纪要|第一行\n第二行\n第三行"
    drafts = agent_capability.parse(text)
    assert drafts[0]["body"] == "第一行\n第二行\n第三行"


def test_parse_caps_at_three() -> None:
    text = "\n".join(f"【发送邮件】u{i}|主题{i}|正文{i}" for i in range(5))
    drafts = agent_capability.parse(text)
    assert [d["username"] for d in drafts] == ["u0", "u1", "u2"]


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无发信指令") == []


def test_parse_requires_all_fields() -> None:
    assert agent_capability.parse("【发送邮件】alice|周报|") == []
    assert agent_capability.parse("【发送邮件】|周报|正文") == []


# ── compose execute()：产草稿 + 待验收 note，★零发送、不嵌 creator★──
async def test_execute_produces_draft_without_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _send(session, *, username, subject, body):  # 不应被调用
        raise AssertionError("compose 步不得发信")

    monkeypatch.setattr(operations, "send_to_username", _send)
    res = await agent_capability.execute(
        None,  # type: ignore[arg-type]
        _role(),
        "【发送邮件】alice|周报|本周进展",
        user_id=uuid.uuid4(),
    )
    assert len(res.artifacts) == 1
    assert res.artifacts[0]["publish_key"] == "send_email_publish"
    assert res.artifacts[0]["username"] == "alice"
    # 收件人在发布时按 username 解析 → 不嵌 creator_id（对比 convene）
    assert "creator_id" not in res.artifacts[0]
    assert any("草稿" in note and "验收" in note for note in res.notes)


async def test_execute_no_directive_is_silent() -> None:
    res = await agent_capability.execute(None, _role(), "普通回复")  # type: ignore[arg-type]
    assert res.notes == [] and res.artifacts == []


# ── send_to_username()：按 username 解析邮箱 + 缺配置/缺账号/缺邮箱如实跳过──
async def test_send_to_username_sends_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_to: dict[str, str] = {}

    monkeypatch.setattr(operations, "_smtp_config", lambda: operations.SmtpConfig(
        host="smtp.x.com", port=587, username="u", password="p", from_addr="from@x.com"
    ))

    async def _get_user(session, *, username):
        return _User(email="alice@x.com")

    async def _send_email(config, *, to, subject, body):
        sent_to["to"] = to
        return True

    monkeypatch.setattr(operations.identity, "get_user_by_username", _get_user)
    monkeypatch.setattr(operations, "send_email", _send_email)

    result = await operations.send_to_username(None, username="alice", subject="s", body="b")  # type: ignore[arg-type]
    assert result.sent is True
    assert sent_to["to"] == "alice@x.com"


async def test_send_to_username_skips_when_smtp_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operations, "_smtp_config", lambda: operations.SmtpConfig(
        host="", port=587, username="", password="", from_addr=""
    ))
    result = await operations.send_to_username(None, username="alice", subject="s", body="b")  # type: ignore[arg-type]
    assert result.sent is False and "未配置" in (result.reason or "")


async def test_send_to_username_skips_unknown_and_no_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operations, "_smtp_config", lambda: operations.SmtpConfig(
        host="smtp.x.com", port=587, username="u", password="p", from_addr="from@x.com"
    ))

    async def _get_unknown(session, *, username):
        return None

    monkeypatch.setattr(operations.identity, "get_user_by_username", _get_unknown)
    unknown = await operations.send_to_username(None, username="ghost", subject="s", body="b")  # type: ignore[arg-type]
    assert unknown.sent is False and "未找到" in (unknown.reason or "")

    async def _get_no_email(session, *, username):
        return _User(email=None)

    monkeypatch.setattr(operations.identity, "get_user_by_username", _get_no_email)
    no_email = await operations.send_to_username(None, username="bob", subject="s", body="b")  # type: ignore[arg-type]
    assert no_email.sent is False and "无工作邮箱" in (no_email.reason or "")


# ── 机械发送步（_FeishuMechanicalPublisher 按 publish_key 派发，自开 session）──
def _draft(username: str = "alice") -> dict:
    return {
        "kind": "email",
        "publish_key": "send_email_publish",
        "username": username,
        "subject": "周报",
        "body": "本周进展",
    }


async def test_publisher_sends_and_emits_email_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _send(session, *, username, subject, body):
        assert username == "alice"
        return operations.SendEmailResult(sent=True)

    monkeypatch.setattr(operations, "send_to_username", _send)
    monkeypatch.setattr(workflow_events, "async_session_factory", _FakeSession)
    out = await _FeishuMechanicalPublisher().publish(_draft())
    assert out["kind"] == "email_sent"


async def test_publisher_records_skip_reason_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _send(session, *, username, subject, body):
        return operations.SendEmailResult(sent=False, reason="SMTP 未配置，已安全跳过")

    monkeypatch.setattr(operations, "send_to_username", _send)
    monkeypatch.setattr(workflow_events, "async_session_factory", _FakeSession)
    out = await _FeishuMechanicalPublisher().publish(_draft())
    assert out["kind"] == "email_skipped"
    assert out["reason"] == "SMTP 未配置，已安全跳过"


async def test_publisher_missing_username_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _send(session, *, username, subject, body):
        raise AssertionError("缺 username 不得发信")

    monkeypatch.setattr(operations, "send_to_username", _send)
    monkeypatch.setattr(workflow_events, "async_session_factory", _FakeSession)
    out = await _FeishuMechanicalPublisher().publish(_draft(username=""))
    assert out["kind"] == "email_skipped"


# ── prompt_section（无门控，随能力授予即可见）─────────────────────
async def test_prompt_section_advertises() -> None:
    section = await agent_capability.prompt_section()
    assert "【发送邮件】" in section


# ── 注册表成员 + 红线 + 机械配对 ─────────────────────────────────
def test_compose_registry_membership_and_red_line() -> None:
    assert "send_email" in REGISTRY
    skill = REGISTRY["send_email"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is None  # compose 无结构化/机械步调用
    assert skill.default_on is False  # 默认不启用，需管理员显式授予
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 仅默认集
    assert "send_email" not in keys
    # 红线：对外发信不在 AUTOMATIC_CAPABILITIES → 编排步执行前必停 waiting_human
    assert requires_human_review("send_email") is True


def test_publish_key_is_mechanical_and_invisible() -> None:
    assert "send_email_publish" not in REGISTRY
    assert is_mechanical("send_email_publish") is True
    assert "send_email_publish" in MECHANICAL_CAPABILITIES
    # 机械发送步草稿已真人验收 → 免二次红线（进 AUTOMATIC）
    assert "send_email_publish" in AUTOMATIC_CAPABILITIES
    assert requires_human_review("send_email_publish") is False


def test_compose_step_pairs_mechanical_publish() -> None:
    compose = WorkflowLaunchStep(
        number=1,
        title="整理邮件草稿",
        capability_key="send_email",
        instruction="把已确认内容整理成邮件草稿",
        depends_on=(),
    )
    paired = pair_publish_steps((compose,))
    assert [s.capability_key for s in paired] == ["send_email", "send_email_publish"]
    assert paired[1].depends_on == (compose.number,)  # 依赖 compose → 验收前结构性不就绪
