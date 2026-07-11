"""AI 角色注册表 — 角色 → 主模型 + 降级链的映射（本项目重写，非直接移植）。

每个角色对应一个 LLM 使用位置（如平台运营部总监、会商推理专家）。
新增角色只需 register_role()；获取模型统一走 get_llm_for_role()。
降级链统一 DeepSeek → Qwen → GLM（决策见 docs/09-模型网关设计）。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.factory import NoAvailableProviderError, build_candidates
from app.llm.fallback import FallbackChatModel
from app.llm.health import rank_providers

# 统一降级链：主 provider 失败后依次尝试
_DEFAULT_FALLBACK_CHAIN: tuple[str, ...] = ("qwen", "glm")


@dataclass(frozen=True)
class RoleDefinition:
    """角色定义：role_key 唯一标识 + 主模型 + 降级链。"""

    role_key: str
    label: str
    provider: str
    model: str
    fallback_chain: tuple[str, ...] = _DEFAULT_FALLBACK_CHAIN


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
    RoleDefinition("ops_director", "平台运营部总监", "deepseek", "deepseek-chat"),
    RoleDefinition("data_analyst", "数据分析师", "deepseek", "deepseek-chat"),
    RoleDefinition("meeting_expert", "会商推理专家", "deepseek", "deepseek-reasoner"),
    RoleDefinition("default", "默认角色", "deepseek", "deepseek-chat"),
]

for _r in _INIT_ROLES:
    register_role(_r)


def get_llm_for_role(role_key: str, **kwargs: object) -> FallbackChatModel:
    """按角色获取带 failover 的 LLM（网关主入口之一）。

    候选顺序 = 角色主模型 + 降级链（健康未熔断者优先，熔断者沉底但不剔除）；
    没有密钥的 provider 直接跳过。未知 role_key 回退 default 角色。

    Raises:
        NoAvailableProviderError: 整条链上没有任何 provider 配置了可用密钥
            （行为约定：无密钥抛明确异常，而非返回空）。
    """
    role = ROLE_REGISTRY.get(role_key) or ROLE_REGISTRY["default"]
    specs: list[tuple[str, str]] = [(role.provider, role.model)]
    specs += [(p, "") for p in rank_providers(role.fallback_chain)]
    candidates = build_candidates(specs, **kwargs)
    if not candidates:
        raise NoAvailableProviderError([role.provider, *role.fallback_chain])
    return FallbackChatModel(candidates=candidates)
