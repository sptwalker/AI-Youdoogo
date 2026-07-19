"""LLM provider 运行时健康度（熔断器）。

- ProviderHealth：熔断记忆，某 provider 失败即按原因进入冷却期，
  冷却期内 rank_providers 把它沉底，避免对已知失效模型反复耗超时。
- rank_providers：简化排序 —— 健康(未熔断)优先，同组内保持传入顺序（稳定排序）。

跨 worker 一致（H1.4，docs/16 P0-4）:冷却态委托 app.core.shared_state（Redis + 本地兜底），
多 worker 共享同一冷却记忆;Redis 不可用时自动降级进程内本地态，接口不变。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.core import shared_state

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
    """熔断记忆（委托 shared_state，跨 worker 一致 + 本地兜底）。接口不变。"""

    def record_failure(self, provider: str, reason: str = "") -> None:
        """记一次失败：按原因设定冷却期（取消不惩罚）。"""
        if reason == _CANCEL_REASON:
            return
        cd = _COOLDOWN_BY_REASON.get(reason, _DEFAULT_COOLDOWN)
        shared_state.cooldown_set(provider, cd)

    def record_success(self, provider: str) -> None:
        """记一次成功：清除该 provider 的熔断状态。"""
        shared_state.cooldown_clear(provider)

    def is_open(self, provider: str) -> bool:
        """True = 该 provider 处于冷却期，应沉底/避免选作主模型。"""
        return shared_state.cooldown_active(provider)

    def cooldown_remaining(self, provider: str) -> int:
        """剩余冷却秒数（未熔断为 0）。"""
        return shared_state.cooldown_ttl(provider)

    def reset(self) -> None:
        """清空本地兜底熔断状态（测试用）。"""
        shared_state.reset()


health = ProviderHealth()


def rank_providers(providers: Sequence[str]) -> list[str]:
    """健康(未熔断)优先，同组内保持传入顺序（Python sorted 稳定排序）。"""
    return sorted(providers, key=lambda p: health.is_open(p))
