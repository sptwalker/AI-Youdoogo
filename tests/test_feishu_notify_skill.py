"""飞书运营群播报（feishu_notify）单测（离线）：播报内容解析与上限、执行播报/no-op 的 note、
自门控（开关+运营群）、prompt_section 广告/门控、run_broadcast 透传 notify、注册表成员。
仿 test_feishu_output_skill.py / test_feishu_notify.py，全程 mock，不发真实飞书请求。"""

import uuid
from typing import Any

import pytest

from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.foundations.integration.feishu_notify.entrypoints import (
    agent_capability,
    operations,
)
from app.core import runtime_config
from app.integrations.feishu import notify
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="播报助理", prompt_template="x", tools=[])


# ── parse（播报内容解析，零外部调用）──────────────────────────
def test_parse_single() -> None:
    assert agent_capability.parse("【飞书播报】本月营收达标") == ["本月营收达标"]


def test_parse_caps_at_two() -> None:
    text = "\n".join(f"【飞书播报】通知{i}" for i in range(3))
    assert agent_capability.parse(text) == ["通知0", "通知1"]


def test_parse_stops_at_line_end() -> None:
    # `.` 默认不跨行 → 只吃本行，不吞并下一行普通正文
    assert agent_capability.parse("【飞书播报】只播这句\n这行是普通正文") == ["只播这句"]


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无播报指令") == []


# ── execute（播报生效 / no-op 的 note）─────────────────────────
async def test_execute_broadcasts_when_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    async def _run(text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(operations, "run_broadcast", _run)
    res = await agent_capability.execute(None, _role(), "【飞书播报】季度目标已达成")  # type: ignore[arg-type]
    assert sent == ["季度目标已达成"]
    assert any("已向运营群播报" in note for note in res.notes)


async def test_execute_noop_note_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run(text: str) -> bool:
        return False  # 开关关/未配群 → notify no-op

    monkeypatch.setattr(operations, "run_broadcast", _run)
    res = await agent_capability.execute(None, _role(), "【飞书播报】测试")  # type: ignore[arg-type]
    assert any("未生效" in note for note in res.notes)


async def test_execute_no_directive_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _run(text: str) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(operations, "run_broadcast", _run)
    res = await agent_capability.execute(None, _role(), "普通回复")  # type: ignore[arg-type]
    assert res.notes == [] and called is False


# ── 自门控（prompt_section 按开关+运营群门控）────────────────
async def test_prompt_section_advertises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operations, "feishu_notify_available", lambda: True)
    section = await agent_capability.prompt_section()
    assert "【飞书播报】" in section


async def test_prompt_section_gated_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(operations, "feishu_notify_available", lambda: False)
    assert await agent_capability.prompt_section() == ""


# ── feishu_notify_available（开关 + 运营群双条件）──────────────
def test_available_when_enabled_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"feishu_notify_enabled": "true", "feishu_ops_chat_id": "oc_ops"}
    monkeypatch.setattr(
        runtime_config, "effective", lambda key, default="": values.get(key, default)
    )
    assert operations.feishu_notify_available() is True


def test_unavailable_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"feishu_notify_enabled": "false", "feishu_ops_chat_id": "oc_ops"}
    monkeypatch.setattr(
        runtime_config, "effective", lambda key, default="": values.get(key, default)
    )
    assert operations.feishu_notify_available() is False


def test_unavailable_when_no_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"feishu_notify_enabled": "true", "feishu_ops_chat_id": ""}
    monkeypatch.setattr(
        runtime_config, "effective", lambda key, default="": values.get(key, default)
    )
    assert operations.feishu_notify_available() is False


# ── run_broadcast 透传 notify.push_ops_message ────────────────
async def test_run_broadcast_delegates_to_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: dict[str, Any] = {}

    async def _push(text: str) -> bool:
        pushed["text"] = text
        return True

    monkeypatch.setattr(notify, "push_ops_message", _push)
    assert await operations.run_broadcast("运营快讯") is True
    assert pushed == {"text": "运营快讯"}


# ── 注册表成员（文本路径可触发、默认广告）──────────────────────
def test_registry_membership() -> None:
    assert "feishu_notify" in REGISTRY
    skill = REGISTRY["feishu_notify"]
    assert skill.legacy_executor is not None  # 文本指令路径可触发
    assert skill.executor_factory is None  # 无结构化/机械步调用
    assert skill.default_on is True  # 进默认启用集（是否广告再由 prompt_section 自门控）
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 默认全开
    assert "feishu_notify" in keys
