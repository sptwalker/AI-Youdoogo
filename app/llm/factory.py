"""多模型网关 — LLM 客户端工厂（移植自 Bottleneck-Hunter llm_clients.factory，做减法）。

支持 provider：deepseek / qwen / glm / kimi / minimax / siliconflow / openrouter /
openai / anthropic，以及自定义 OpenAI 兼容端点。

密钥统一从 app.core.config.get_settings() 读取（.env → Settings），没有密钥的
provider 视为不可用（provider_available=False，构建候选时跳过，不报错）。
国产模型全部走 langchain_openai.ChatOpenAI + base_url；anthropic 分支保留，
但 langchain-anthropic 未安装时视为不可用（lazy import 优雅降级）。
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """该 provider 当前不可用（未配置密钥 / 依赖未安装）。"""

    def __init__(self, provider: str, reason: str = "未配置 API Key 或依赖未安装"):
        self.provider = provider
        super().__init__(f"LLM provider 不可用: {provider}（{reason}）")


class NoAvailableProviderError(RuntimeError):
    """整条候选链上没有任何可用 provider。"""

    def __init__(self, chain: Sequence[str]):
        self.chain = list(chain)
        super().__init__(
            f"候选链 {self.chain} 上没有任何可用的 LLM provider，请在 .env 配置至少一个 API Key"
        )


# provider → Settings 字段名。未列出的内置 provider 暂无密钥来源 → 不可用。
_PROVIDER_KEY_FIELD: dict[str, str] = {
    "deepseek": "deepseek_api_key",
    "qwen": "dashscope_api_key",
    "glm": "zhipu_api_key",
    "anthropic": "anthropic_api_key",
}

# 各 provider 的默认模型（种子；可被 create_llm 显式 model 或自定义端点覆盖）
PROVIDER_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "glm": "glm-4-flash",
    "kimi": "moonshot-v1-8k",
    "minimax": "MiniMax-Text-01",
    "siliconflow": "deepseek-ai/DeepSeek-V3",
    "openrouter": "deepseek/deepseek-chat",
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
}

# 内置 OpenAI 兼容 provider 的官方端点。openai/anthropic 走各自 SDK 默认端点，不在此表。
_BUILTIN_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "kimi": "https://api.moonshot.cn/v1",
    "minimax": "https://api.minimax.chat/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# ── 自定义 OpenAI 兼容端点（进程内注册表）─────────────────────
_CUSTOM_PROVIDERS: dict[str, dict[str, str]] = {}


def register_custom_provider(
    provider_id: str, base_url: str, api_key: str = "", default_model: str = ""
) -> None:
    """注册自定义 OpenAI 兼容端点（api_key 由调用方从环境变量取得后传入）。"""
    _CUSTOM_PROVIDERS[provider_id.lower().strip()] = {
        "base_url": base_url,
        "api_key": api_key,
        "default_model": default_model,
    }
    logger.info("已注册自定义 provider: %s (%s)", provider_id, base_url)


def unregister_custom_provider(provider_id: str) -> None:
    """从注册表移除自定义 provider。"""
    _CUSTOM_PROVIDERS.pop(provider_id.lower().strip(), None)


def get_custom_provider(provider_id: str) -> dict[str, str] | None:
    """查询自定义 provider 信息。"""
    return _CUSTOM_PROVIDERS.get(provider_id.lower().strip())


def _provider_api_key(provider: str) -> str:
    """解析某 provider 的 API Key：自定义端点注册值 → Settings 字段。无则空串。"""
    custom = _CUSTOM_PROVIDERS.get(provider)
    if custom is not None:
        return custom.get("api_key", "")
    field = _PROVIDER_KEY_FIELD.get(provider)
    if not field:
        return ""
    return str(getattr(get_settings(), field, "") or "")


def provider_available(provider: str) -> bool:
    """该 provider 当前是否可用（有密钥且依赖已安装）。

    自定义端点注册即视为可用（本地端点可无 Key）；anthropic 额外要求
    langchain-anthropic 已安装。
    """
    p = (provider or "").lower().strip()
    if not p:
        return False
    if p in _CUSTOM_PROVIDERS:
        return True
    if p == "anthropic" and importlib.util.find_spec("langchain_anthropic") is None:
        return False
    return bool(_provider_api_key(p))


def resolve_provider_model(provider: str) -> str:
    """解析某 provider 应使用的默认模型：自定义端点 → 种子常量。"""
    p = (provider or "").lower().strip()
    custom = _CUSTOM_PROVIDERS.get(p)
    if custom and custom.get("default_model"):
        return custom["default_model"]
    return PROVIDER_MODELS.get(p, "")


def resolve_provider_base_url(provider: str) -> str | None:
    """解析某 provider 的 base_url。None 表示走 SDK 默认端点（openai/anthropic）。"""
    p = (provider or "").lower().strip()
    custom = _CUSTOM_PROVIDERS.get(p)
    if custom and custom.get("base_url"):
        return custom["base_url"]
    return _BUILTIN_BASE_URLS.get(p)


def _create_raw_llm(
    provider: str, model: str = "", base_url: str | None = None, **kwargs: Any
) -> BaseChatModel:
    """构建单个裸 LLM 实例（不含 failover 包装）。provider 不可用即抛异常。"""
    p = (provider or "").lower().strip()
    if not provider_available(p):
        raise ProviderUnavailableError(p)
    key = _provider_api_key(p)
    resolved_model = model or resolve_provider_model(p)
    if not resolved_model:
        raise ValueError(f"provider {p} 未指定模型且无默认模型")
    resolved_base = base_url or resolve_provider_base_url(p)

    if p == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if resolved_base:
            return ChatAnthropic(
                model=resolved_model, api_key=key, base_url=resolved_base, **kwargs
            )
        return ChatAnthropic(model=resolved_model, api_key=key, **kwargs)

    # 其余全部走 OpenAI 兼容：openai 官方端点(base_url=None) / 内置国产 / 自定义端点
    from langchain_openai import ChatOpenAI

    if p == "openai" and not resolved_base:
        return ChatOpenAI(model=resolved_model, api_key=SecretStr(key), **kwargs)
    if not resolved_base:
        raise ValueError(f"不支持的 LLM provider: {p}（无 base_url，且非 openai/anthropic）")
    return ChatOpenAI(
        model=resolved_model,
        api_key=SecretStr(key or "not-needed"),
        base_url=resolved_base,
        **kwargs,
    )


def build_candidates(
    specs: Sequence[tuple[str, str]], **kwargs: Any
) -> list[tuple[BaseChatModel, str, str]]:
    """按顺序为 (provider, model) 列表构建裸模型候选，跳过不可用/构建失败的 provider。

    model 传空串则用该 provider 的默认模型；同一 provider 去重（首个生效）。
    """
    out: list[tuple[BaseChatModel, str, str]] = []
    seen: set[str] = set()
    for provider, model in specs:
        p = (provider or "").lower().strip()
        if not p or p in seen:
            continue
        seen.add(p)
        if not provider_available(p):
            continue
        m = model or resolve_provider_model(p)
        if not m:
            continue
        try:
            out.append((_create_raw_llm(p, m, **kwargs), p, m))
        except Exception as e:  # noqa: BLE001 - 单个候选构建失败不影响其余
            logger.warning("构建候选 %s/%s 失败: %s", p, m, e)
    return out


# 默认降级链（决策见 docs/09-模型网关设计）：DeepSeek 主力 → Qwen → GLM
DEFAULT_FALLBACK_CHAIN: tuple[str, ...] = ("qwen", "glm")


def create_llm(
    provider: str,
    model: str = "",
    *,
    base_url: str | None = None,
    with_fallback: bool = True,
    fallback_chain: Sequence[str] = DEFAULT_FALLBACK_CHAIN,
    **kwargs: Any,
) -> BaseChatModel:
    """创建 LLM 实例（网关主入口）。

    Args:
        provider: provider 标识（内置或自定义）。不可用即抛 ProviderUnavailableError。
        model: 模型名；留空用该 provider 默认模型。
        base_url: 显式端点（最高优先级）。
        with_fallback: True(默认) 包一层 FallbackChatModel（失败自动切换备选）；
            测试/冒烟类调用（要测这一个具体模型）传 False。
        fallback_chain: 备选 provider 顺序（不含主 provider），健康者优先。
        **kwargs: 透传给底层模型（如 temperature）。
    """
    llm = _create_raw_llm(provider, model, base_url=base_url, **kwargs)
    if not with_fallback:
        return llm

    from app.llm.fallback import FallbackChatModel
    from app.llm.health import rank_providers

    p = provider.lower().strip()
    resolved_model = model or resolve_provider_model(p)
    backups = build_candidates(
        [(bp, "") for bp in rank_providers([c for c in fallback_chain if c != p])], **kwargs
    )
    if not backups:
        return llm  # 无可用备选 → 不套壳
    return FallbackChatModel(candidates=[(llm, p, resolved_model), *backups])
