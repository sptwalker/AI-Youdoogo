"""Knowledge Search canary 路由（Phase 2 / docs/21 §11）：按 knowledge_gateway_canary_percent
抽样选 Remote / Local。不发真实请求——只验证 build_knowledge_search_port 的选择器语义与边界。
"""

from __future__ import annotations

import pytest

from app.contexts.foundations.knowledge.knowledge_retrieval import public
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.local_adapter import (
    LocalKnowledgeSearchAdapter,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.remote_adapter import (
    RemoteKnowledgeSearchAdapter,
)
from app.core.config import Settings, get_settings


def _settings(**over: object) -> Settings:
    base = dict(
        knowledge_search_mode="local",
        knowledge_gateway_url="",
        knowledge_gateway_canary_percent=0,
    )
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


class _StubSession:
    """LocalKnowledgeSearchAdapter 仅在构造时存 session、search 时才用；选择器测试不触 search。"""


@pytest.fixture(autouse=True)
def _clear() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_route_remote_boundaries() -> None:
    assert public._route_remote(0) is False
    assert public._route_remote(100) is True
    trues = sum(public._route_remote(50) for _ in range(400))
    assert 120 < trues < 280


def test_local_when_mode_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings(knowledge_search_mode="local"))
    port = public.build_knowledge_search_port(_StubSession())  # type: ignore[arg-type]
    assert isinstance(port, LocalKnowledgeSearchAdapter)


def test_local_when_canary_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings(
        knowledge_search_mode="remote", knowledge_gateway_url="http://kb:8080",
        knowledge_gateway_canary_percent=0))
    port = public.build_knowledge_search_port(_StubSession())  # type: ignore[arg-type]
    assert isinstance(port, LocalKnowledgeSearchAdapter)


def test_remote_when_canary_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings(
        knowledge_search_mode="remote", knowledge_gateway_url="http://kb:8080",
        knowledge_gateway_canary_percent=100))
    port = public.build_knowledge_search_port(_StubSession())  # type: ignore[arg-type]
    assert isinstance(port, RemoteKnowledgeSearchAdapter)


def test_canary_percent_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="CANARY_PERCENT"):
        _settings(knowledge_gateway_canary_percent=101)


def test_remote_mode_without_url_rejected() -> None:
    with pytest.raises(ValueError, match="KNOWLEDGE_GATEWAY_URL"):
        _settings(knowledge_search_mode="remote", knowledge_gateway_url="")
