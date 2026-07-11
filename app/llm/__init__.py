"""多模型网关（app/llm）— 统一出入口。

用法：
    from app.llm import create_llm, get_llm_for_role
    llm = get_llm_for_role("ops_director")   # 带 failover 的角色模型
    raw = create_llm("deepseek", "deepseek-chat", with_fallback=False)  # 裸模型
"""

from app.llm.factory import (
    DEFAULT_FALLBACK_CHAIN,
    PROVIDER_MODELS,
    NoAvailableProviderError,
    ProviderUnavailableError,
    create_llm,
    provider_available,
    register_custom_provider,
    unregister_custom_provider,
)
from app.llm.fallback import FallbackChatModel
from app.llm.health import ProviderHealth, health, rank_providers
from app.llm.roles import ROLE_REGISTRY, RoleDefinition, get_llm_for_role, get_role, register_role

__all__ = [
    "DEFAULT_FALLBACK_CHAIN",
    "PROVIDER_MODELS",
    "ROLE_REGISTRY",
    "FallbackChatModel",
    "NoAvailableProviderError",
    "ProviderHealth",
    "ProviderUnavailableError",
    "RoleDefinition",
    "create_llm",
    "get_llm_for_role",
    "get_role",
    "health",
    "provider_available",
    "rank_providers",
    "register_custom_provider",
    "register_role",
    "unregister_custom_provider",
]
