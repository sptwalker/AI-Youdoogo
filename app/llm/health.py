"""LLM provider 运行时健康度（进程内熔断器）— 移植自 Bottleneck-Hunter llm_clients.health。

- ProviderHealth：进程内熔断记忆。某 provider 失败即按原因进入冷却期，
  冷却期内 rank_providers 把它沉底，避免对已知失效模型反复耗超时。
- rank_providers：简化排序 —— 健康(未熔断)优先，同组内保持传入顺序（稳定排序）。

相对源实现的减法：删除逐用户隔离（key 只有 provider）、遥测落库、成功率/能力分/
用户策略加权排序。多 worker 需跨进程共享时再上 Redis。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence

logger = logging.getLogger(__name__)

# 各失败原因的冷却秒数（原因串来自 fallback.classify_reason）
_COOLDOWN_BY_REASON: dict[str, int] = {
    "认证失败(密钥无效)": 300,  # 硬故障：Key 无效，长冷却
    "频率限制/额度不足": 120,
    "服务端错误": 60,
    "连接失败": 60,
    "请求超时": 45,
    "调用异常": 30,
}
_DEFAULT_COOLDOWN = 30
_CANCEL_REASON = "调用被取消"  # 用户主动取消，不惩罚


class ProviderHealth:
    """进程内熔断记忆：provider → 冷却截止时刻(monotonic)。线程安全。"""

    def __init__(self) -> None:
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def record_failure(self, provider: str, reason: str = "") -> None:
        """记一次失败：按原因设定冷却期（取消不惩罚）。"""
        if reason == _CANCEL_REASON:
            return
        cd = _COOLDOWN_BY_REASON.get(reason, _DEFAULT_COOLDOWN)
        if cd <= 0:
            return
        with self._lock:
            self._until[(provider or "").lower().strip()] = time.monotonic() + cd

    def record_success(self, provider: str) -> None:
        """记一次成功：清除该 provider 的熔断状态。"""
        with self._lock:
            self._until.pop((provider or "").lower().strip(), None)

    def is_open(self, provider: str) -> bool:
        """True = 该 provider 处于冷却期，应沉底/避免选作主模型。"""
        key = (provider or "").lower().strip()
        with self._lock:
            t = self._until.get(key)
            if t is None:
                return False
            if time.monotonic() >= t:
                self._until.pop(key, None)
                return False
            return True

    def cooldown_remaining(self, provider: str) -> int:
        """剩余冷却秒数（未熔断为 0）。"""
        key = (provider or "").lower().strip()
        with self._lock:
            t = self._until.get(key)
            return max(0, int(t - time.monotonic())) if t else 0

    def reset(self) -> None:
        """清空全部熔断状态（测试用）。"""
        with self._lock:
            self._until.clear()


health = ProviderHealth()


def rank_providers(providers: Sequence[str]) -> list[str]:
    """健康(未熔断)优先，同组内保持传入顺序（Python sorted 稳定排序）。"""
    return sorted(providers, key=lambda p: health.is_open(p))
