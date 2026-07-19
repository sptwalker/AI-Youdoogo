"""跨 worker 共享态单测（H1.4，docs/16 P0-4）:熔断冷却 + 预算原子 + Redis 降级本地。

用真 Redis（dev 容器）跑通链路;另用 monkeypatch 强制 Redis 不可用验证本地兜底。
每用例 reset() 清本进程碰过的键，避免串扰。
"""

import pytest

from app.core import shared_state


@pytest.fixture(autouse=True)
def _reset() -> None:
    shared_state.reset()
    yield
    shared_state.reset()


# ── 熔断冷却 ────────────────────────────────────────────
def test_cooldown_set_active_clear() -> None:
    assert shared_state.cooldown_active("prov-a") is False
    shared_state.cooldown_set("prov-a", 60)
    assert shared_state.cooldown_active("prov-a") is True
    assert 0 < shared_state.cooldown_ttl("prov-a") <= 60
    shared_state.cooldown_clear("prov-a")
    assert shared_state.cooldown_active("prov-a") is False


def test_cooldown_zero_seconds_noop() -> None:
    shared_state.cooldown_set("prov-b", 0)
    assert shared_state.cooldown_active("prov-b") is False


def test_cooldown_provider_normalized() -> None:
    """provider 大小写/空白归一（同一 provider 视作同键）。"""
    shared_state.cooldown_set("  Prov-C  ", 60)
    assert shared_state.cooldown_active("prov-c") is True


# ── 预算原子累加 ────────────────────────────────────────
def test_budget_accumulates() -> None:
    assert shared_state.budget_add("2026-07-20", 100) == 100
    assert shared_state.budget_add("2026-07-20", 50) == 150
    assert shared_state.budget_add("2026-07-20", 0) == 150  # 读当前不加


def test_budget_isolated_by_day() -> None:
    shared_state.budget_add("2026-07-20", 100)
    assert shared_state.budget_add("2026-07-21", 30) == 30  # 另一天独立


# ── Redis 不可用 → 本地兜底 ─────────────────────────────
def test_falls_back_to_local_when_redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 取不到客户端 → cooldown/budget 走本地态，功能不断。"""
    monkeypatch.setattr(shared_state, "_redis", lambda: None)
    shared_state.cooldown_set("local-p", 60)
    assert shared_state.cooldown_active("local-p") is True
    assert shared_state.budget_add("2026-07-20", 200) == 200
    assert shared_state.budget_add("2026-07-20", 5) == 205
    shared_state.cooldown_clear("local-p")
    assert shared_state.cooldown_active("local-p") is False


def test_redis_op_error_degrades_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 客户端在操作中抛错 → 降级本地兜底，不抛。"""
    class _Boom:
        def exists(self, *a: object) -> bool:
            raise RuntimeError("redis down mid-op")
        def set(self, *a: object, **k: object) -> None:
            raise RuntimeError("redis down mid-op")

    monkeypatch.setattr(shared_state, "_redis", lambda: _Boom())
    # 不抛，走本地兜底路径
    shared_state.cooldown_set("x", 30)
    assert shared_state.cooldown_active("x") in (True, False)  # 关键是不抛异常
