"""select_agent_execution 分支 + 单次 canary 抽样（docs/23 §6.2 Branch-by-Abstraction）。

回归锁 bug#1「canary 双抽样」：未命中/本地路径只抽一次 expert canary——旧码 else 分支再经
build_expert_execution_llm_port 二抽同档，使 P(remote)=2p−p²。只验选择器语义与抽样次数，不发真请求。
选择器仅读 settings 的 4 个字段，用 SimpleNamespace 替身绕开无关的 Settings 校验（PEM/url 必填等）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    AgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.infrastructure import composition
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_application import (
    RemoteAgentExecutionApplication,
)


def _fake_settings(mode: str, *, url: str = "", canary: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        expert_execution_mode=mode,
        expert_platform_url=url,
        expert_platform_canary_percent=canary,
        expert_forward_gateway_token=False,
    )


class _Roller:
    """替身 _route_remote：记抽样次数，返回固定命中/未命中。"""

    def __init__(self, hit: bool) -> None:
        self.hit = hit
        self.calls = 0

    def __call__(self, percent: int) -> bool:
        self.calls += 1
        return self.hit


def _select(
    monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace, roller: _Roller
) -> object:
    monkeypatch.setattr(composition, "get_settings", lambda: settings)
    monkeypatch.setattr(composition, "_route_remote", roller)
    stub = cast(AsyncSession, object())  # 选择器只存不用这些端口，object() 足矣
    return composition.select_agent_execution(
        stub,
        prompt_port=stub, knowledge_port=stub, usage_authorization=stub,  # type: ignore[arg-type]
        recorder=stub, clock=stub, external_boundary=stub,  # type: ignore[arg-type]
    )


def test_local_mode_never_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    roller = _Roller(hit=True)  # 即便替身恒命中，local 模式也不该抽样
    app = _select(monkeypatch, _fake_settings("local"), roller)
    assert isinstance(app, AgentExecutionApplication)
    assert roller.calls == 0


def test_remote_hit_single_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    roller = _Roller(hit=True)
    settings = _fake_settings("remote", url="http://expert:8080", canary=50)
    app = _select(monkeypatch, settings, roller)
    assert isinstance(app, RemoteAgentExecutionApplication)
    assert roller.calls == 1


def test_remote_miss_single_sample_local(monkeypatch: pytest.MonkeyPatch) -> None:
    # bug#1 回归锁：未命中 → 纯本地 app，且 expert canary 只抽一次（旧码此处二抽同档）。
    roller = _Roller(hit=False)
    settings = _fake_settings("remote", url="http://expert:8080", canary=50)
    app = _select(monkeypatch, settings, roller)
    assert isinstance(app, AgentExecutionApplication)
    assert not isinstance(app, RemoteAgentExecutionApplication)
    assert roller.calls == 1
