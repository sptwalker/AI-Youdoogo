"""AI 角色注册表 — 角色 → 档位(tier) 的映射（卡片化后重写）。

每个角色对应一个 LLM 使用位置（如平台运营部总监、会商推理专家），归属一个档位：
daily（日常）/ reasoning（推理）。获取模型统一走 get_llm_for_role()：按角色档位取该档
「主用卡片 + 同档 active 卡片」作候选链（真源 ai_provider 表，经 factory 状态缓存）。
必须先在「AI 配置」页建卡片，否则该档无候选 → 抛 NoAvailableProviderError。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.factory import NoAvailableProviderError, build_candidates, providers_for_tier
from app.llm.fallback import FallbackChatModel
from app.llm.health import rank_providers
from app.models.ai_provider import TIER_DAILY


@dataclass(frozen=True)
class RoleDefinition:
    """角色定义：role_key 唯一标识 + 显示名 + 所属档位（daily/reasoning）。"""

    role_key: str
    label: str
    tier: str = TIER_DAILY


ROLE_REGISTRY: dict[str, RoleDefinition] = {}


def register_role(role: RoleDefinition) -> None:
    """注册（或覆盖）一个角色定义。"""
    ROLE_REGISTRY[role.role_key] = role


def get_role(role_key: str) -> RoleDefinition | None:
    """按 key 查角色定义，无则 None。"""
    return ROLE_REGISTRY.get(role_key)


def list_roles() -> list[RoleDefinition]:
    """列出全部已注册角色。"""
    return list(ROLE_REGISTRY.values())


_INIT_ROLES = [
    RoleDefinition("ops_director", "平台运营部总监", "daily"),
    RoleDefinition("data_analyst", "数据分析师", "daily"),
    RoleDefinition("meeting_expert", "会商推理专家", "reasoning"),
    RoleDefinition("default", "默认角色", "daily"),
]

for _r in _INIT_ROLES:
    register_role(_r)


def get_llm_for_role(role_key: str, **kwargs: object) -> FallbackChatModel:
    """按角色档位获取带 failover 的 LLM（网关主入口之一）。

    候选 = 该档位「主用卡片 + 同档 active 卡片」（健康未熔断者优先，熔断者沉底但不剔除）；
    每张卡片用自身 default_model。未知 role_key 回退 default 角色（daily 档）。

    Raises:
        NoAvailableProviderError: 该档位没有任何可用卡片（约定：请先在「AI 配置」页建卡片）。
    """
    role = ROLE_REGISTRY.get(role_key) or ROLE_REGISTRY["default"]
    provider_ids = rank_providers(providers_for_tier(role.tier))
    specs = [(pid, "") for pid in provider_ids]  # model 留空 → 取卡片 default_model
    candidates = build_candidates(specs, **kwargs)
    if not candidates:
        raise NoAvailableProviderError([role.tier])
    return FallbackChatModel(candidates=candidates)
