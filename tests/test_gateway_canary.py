"""docs/21 步骤5 canary 路由：按 llm_gateway_canary_percent 抽样选 Remote / Local。

不发真实请求——只验证 build_llm_completion_port 的选择器语义与边界。
"""

from __future__ import annotations

import pytest

from app.contexts.foundations.model_gateway import public
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import (
    LocalLlmAdapter,
)
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import (
    RemoteLlmAdapter,
)
from app.core.config import Settings, get_settings


def _settings(**over: object) -> Settings:
    base = dict(
        internal_jwt_private_key="", internal_jwt_public_key="",
        llm_completion_mode="local", llm_gateway_url="", llm_gateway_canary_percent=0,
    )
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_route_remote_boundaries() -> None:
    assert public._route_remote(0) is False  # 0 恒 local
    assert public._route_remote(100) is True  # 100 恒 remote
    # 抽样落在 [0,100)：p=1 时几乎总 local，p=99 时几乎总 remote（统计性，非断死）
    trues = sum(public._route_remote(50) for _ in range(400))
    assert 120 < trues < 280  # 50% 附近宽区间，抓死链退化（恒 True/False）


def test_local_when_mode_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings",
                        lambda: _settings(llm_completion_mode="local"))
    assert isinstance(public.build_llm_completion_port(), LocalLlmAdapter)


def test_local_when_canary_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # remote 模式但 percent=0 → 灰度未开，仍全 local（生产默认，安全）
    monkeypatch.setattr(public, "get_settings", lambda: _settings(
        llm_completion_mode="remote", llm_gateway_url="http://gw:8080",
        llm_gateway_canary_percent=0))
    assert isinstance(public.build_llm_completion_port(), LocalLlmAdapter)


def test_remote_when_canary_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings(
        llm_completion_mode="remote", llm_gateway_url="http://gw:8080",
        llm_gateway_canary_percent=100))
    assert isinstance(public.build_llm_completion_port(), RemoteLlmAdapter)


def test_canary_percent_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="CANARY_PERCENT"):
        _settings(llm_gateway_canary_percent=101)
