"""跨 worker 共享状态（H1.4，docs/16 P0-4）：熔断冷却 + 日预算计数走 Redis。

问题:LLM 熔断器与日预算原为每-worker 内存态，多 worker 下各自为政（失效 provider 被
N 倍试探、预算 N 份分别计）。本模块用 Redis 做跨进程一致，并保留本地兜底。

设计要点:
- **同步 Redis 客户端**:熔断在 LLM 主链路的 sync 路径（rank_providers/is_open）被调用，
  接口必须同步;用 redis-py 同步客户端 + 紧 socket 超时（0.3s）。
- **优雅降级**:Redis 不可用/超时 → 回退进程内本地态（= 迁移前行为），绝不阻断 LLM 调用。
  客户端故障后 30s 内不重连（避免每次调用都撞死 Redis）。
- **冷却用 TTL**:SETEX 键，Redis 自动过期即冷却结束;EXISTS 判是否熔断，TTL 取剩余。
- **预算原子**:INCRBY 日键 + 首次 EXPIRE，天然原子 + 跨 worker 一致。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SOCKET_TIMEOUT = 0.3  # 紧超时:Redis 慢即降级本地，不拖累 LLM 主链路
_RETRY_COOLDOWN = 30.0  # 客户端故障后重连冷却秒数

_client: Any | None = None
_next_retry = 0.0

# 本地兜底态（Redis 不可用时用）
_local_cooldown: dict[str, float] = {}  # provider → monotonic 截止
_local_budget: dict[str, int] = {}  # date_str → 累计 token
_touched: set[str] = set()  # 本进程写过的 Redis 键（供 reset 精确清理，测试隔离用）


def _redis() -> Any | None:
    """取同步 Redis 客户端（懒建 + ping 校验）。不可用返回 None，30s 内不重试。"""
    global _client, _next_retry
    if _client is not None:
        return _client
    if time.monotonic() < _next_retry:
        return None
    try:
        import redis

        c = redis.Redis.from_url(
            get_settings().redis_url,
            socket_timeout=_SOCKET_TIMEOUT,
            socket_connect_timeout=_SOCKET_TIMEOUT,
            decode_responses=True,
        )
        c.ping()
        _client = c
        return c
    except Exception:  # noqa: BLE001 - Redis 不可用即降级本地
        _next_retry = time.monotonic() + _RETRY_COOLDOWN
        return None


def _with_redis(fn: Callable[[Any], Any], fallback: Callable[[], Any]) -> Any:
    """执行 Redis 操作;客户端级异常 → 重置并降级本地兜底。"""
    global _client, _next_retry
    c = _redis()
    if c is None:
        return fallback()
    try:
        return fn(c)
    except Exception:  # noqa: BLE001 - 运行时故障降级本地，不阻断主链路
        _client = None
        _next_retry = time.monotonic() + _RETRY_COOLDOWN
        logger.warning("Redis 共享态操作失败，本次降级本地", exc_info=True)
        return fallback()


# ── 熔断冷却 ────────────────────────────────────────────
def _ck(provider: str) -> str:
    return f"llm:cooldown:{(provider or '').lower().strip()}"


def cooldown_set(provider: str, seconds: int) -> None:
    """设 provider 冷却 seconds 秒。"""
    if seconds <= 0:
        return
    key = _ck(provider)
    _touched.add(key)

    def _local() -> None:
        _local_cooldown[key] = time.monotonic() + seconds

    _with_redis(lambda c: c.set(key, "1", ex=seconds), _local)


def cooldown_active(provider: str) -> bool:
    """该 provider 是否处于冷却期。"""
    key = _ck(provider)

    def _local() -> bool:
        t = _local_cooldown.get(key)
        if t is None:
            return False
        if time.monotonic() >= t:
            _local_cooldown.pop(key, None)
            return False
        return True

    return bool(_with_redis(lambda c: c.exists(key), _local))


def cooldown_clear(provider: str) -> None:
    """清除该 provider 冷却（成功调用后）。"""
    key = _ck(provider)
    _with_redis(lambda c: c.delete(key), lambda: _local_cooldown.pop(key, None))


def cooldown_ttl(provider: str) -> int:
    """剩余冷却秒数（未熔断为 0）。"""
    key = _ck(provider)

    def _local() -> int:
        t = _local_cooldown.get(key)
        return max(0, int(t - time.monotonic())) if t else 0

    return int(_with_redis(lambda c: max(0, int(c.ttl(key) or 0)), _local))


# ── 日预算原子计数 ──────────────────────────────────────
def _bk(date_str: str) -> str:
    return f"llm:budget:{date_str}"


def budget_add(date_str: str, tokens: int) -> int:
    """原子累加当日 token 用量，返回累加后总量。跨 worker 一致。"""
    key = _bk(date_str)

    def _local() -> int:
        _local_budget[date_str] = _local_budget.get(date_str, 0) + max(0, tokens)
        return _local_budget[date_str]

    def _redis_op(c: Any) -> int:
        total = int(c.incrby(key, max(0, tokens)))
        c.expire(key, 172800)  # 2 天 TTL（够跨日告警，自动清理）
        return total

    _touched.add(key)
    return int(_with_redis(_redis_op, _local))


def reset() -> None:
    """清空本进程写过的共享态（本地 + Redis 里本进程碰过的键）。测试隔离用。"""
    _local_cooldown.clear()
    _local_budget.clear()
    keys = list(_touched)
    _touched.clear()
    if keys:
        _with_redis(lambda c: c.delete(*keys), lambda: None)
