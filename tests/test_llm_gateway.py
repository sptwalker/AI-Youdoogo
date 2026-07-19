"""多模型网关单测：假模型 failover + 角色按档取卡片（不发真实请求、不消耗额度）。

卡片化后：provider 候选来自进程内卡片注册表（factory），不再读 .env 密钥。
"""

from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.llm import (
    FallbackChatModel,
    NoAvailableProviderError,
    factory,
    get_llm_for_role,
    health,
    provider_available,
    rank_providers,
)
from app.llm.validate import validate_output


class _BoomModel(BaseChatModel):
    """第一个候选：调用恒抛异常。"""

    @property
    def _llm_type(self) -> str:
        return "boom"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise TimeoutError("simulated timeout")


class _EchoModel(BaseChatModel):
    """第二个候选：返回固定文本。"""

    text: str = "备选模型的固定回复内容，足够长以避免触发拒答启发式判定。"

    @property
    def _llm_type(self) -> str:
        return "echo"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.text))])


@pytest.fixture(autouse=True)
def _reset_gateway() -> None:
    """每个用例前清空熔断 + 卡片注册/状态，避免用例间串扰。"""
    health.reset()
    factory.clear_card_providers()
    factory.set_provider_status([], {}, {})


def _register(tier_cards: dict[str, list[tuple[str, str, bool]]]) -> None:
    """注册卡片到 factory：{tier: [(provider_id, model, is_primary), ...]}（主用置顶）。"""
    factory.clear_card_providers()
    tier_ids: dict[str, list[str]] = {}
    primary: dict[str, str] = {}
    for tier, cards in tier_cards.items():
        for pid, model, is_primary in cards:
            factory.register_custom_provider(
                pid, "https://api.x.com", api_key="sk", default_model=model
            )
            tier_ids.setdefault(tier, [])
            if is_primary:
                tier_ids[tier].insert(0, pid)
                primary[tier] = pid
            else:
                tier_ids[tier].append(pid)
    factory.set_provider_status([], primary, tier_ids)


def test_fallback_switches_to_second_candidate() -> None:
    """主模型恒失败 → 自动切换到第二候选并返回其文本。"""
    echo = _EchoModel()
    fb = FallbackChatModel(
        candidates=[(_BoomModel(), "deepseek", "deepseek-chat"), (echo, "qwen", "qwen-plus")]
    )
    result = fb.invoke("你好")
    assert result.content == echo.text
    assert health.is_open("deepseek")
    assert not health.is_open("qwen")


def test_fallback_all_failed_raises() -> None:
    """全部候选失败 → 抛最后一个异常。"""
    fb = FallbackChatModel(candidates=[(_BoomModel(), "deepseek", "deepseek-chat")])
    with pytest.raises(TimeoutError):
        fb.invoke("你好")


# ── H2.1 调用护栏：尝试上限 + 总超时封顶 + 超时注入 ────────
def test_fallback_max_attempts_caps_candidates() -> None:
    """max_attempts=1 → 只试主候选，不碰备选（主失败即抛，不切换）。"""
    echo = _EchoModel()
    fb = FallbackChatModel(
        candidates=[(_BoomModel(), "deepseek", "deepseek-chat"), (echo, "qwen", "qwen-plus")],
        max_attempts=1,
    )
    with pytest.raises(TimeoutError):
        fb.invoke("你好")  # 被截断到 1 个候选，不 fallback 到 echo


def test_fallback_total_budget_stops_chain() -> None:
    """总墙钟预算耗尽 → 不再尝试后续候选（用极小预算 + 慢主候选模拟）。"""
    import time as _t

    class _SlowBoom(_BoomModel):
        def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None,
                      **kwargs: Any) -> Any:
            _t.sleep(0.05)
            raise TimeoutError("slow boom")

    echo = _EchoModel()
    fb = FallbackChatModel(
        candidates=[(_SlowBoom(), "deepseek", "deepseek-chat"), (echo, "qwen", "qwen-plus")],
        total_budget_s=0.01,  # 主候选就已超预算，第二个不再起
    )
    with pytest.raises(TimeoutError):
        fb.invoke("你好")  # 预算耗尽，不 fallback 到 echo


def test_active_respects_max_attempts() -> None:
    """_active 截取到 max_attempts 个候选。"""
    fb = FallbackChatModel(
        candidates=[(_EchoModel(), "a", "m"), (_EchoModel(), "b", "m"), (_EchoModel(), "c", "m")],
        max_attempts=2,
    )
    assert len(fb._active()) == 2
    fb2 = FallbackChatModel(candidates=fb.candidates)  # 默认 0 = 不限
    assert len(fb2._active()) == 3


def test_create_raw_llm_injects_timeout_and_retries() -> None:
    """_create_raw_llm 给底层模型注入 timeout + max_retries（H2.1）。"""
    factory.register_custom_provider("cardx", "https://api.x.com", api_key="sk", default_model="m")
    llm = factory._create_raw_llm("cardx", "m")
    from app.core.config import get_settings

    s = get_settings()
    assert llm.request_timeout == s.llm_request_timeout  # type: ignore[attr-defined]
    assert llm.max_retries == s.llm_max_retries  # type: ignore[attr-defined]


def test_get_llm_for_role_builds_from_tier_cards() -> None:
    """daily 档有卡片时 default 角色能构造 FallbackChatModel，主候选=主用卡片。"""
    _register({"daily": [("card_a", "m1", True), ("card_b", "m2", False)]})
    llm = get_llm_for_role("default")
    assert isinstance(llm, FallbackChatModel)
    assert llm.candidates[0][1:] == ("card_a", "m1")
    assert [c[1] for c in llm.candidates] == ["card_a", "card_b"]


def test_get_llm_for_role_no_card_raises() -> None:
    """该档无卡片 → 抛 NoAvailableProviderError（约定：请先建卡片）。"""
    with pytest.raises(NoAvailableProviderError):
        get_llm_for_role("default")


def test_unknown_role_falls_back_to_default() -> None:
    """未知 role_key 回退 default 角色（daily 档）。"""
    _register({"daily": [("card_a", "m1", True)]})
    llm = get_llm_for_role("no_such_role")
    assert llm.candidates[0][1:] == ("card_a", "m1")


def test_provider_available_card_and_inactive() -> None:
    """已注册卡片可用；被禁卡片不可用；未知 provider 恒不可用。"""
    factory.register_custom_provider("card_x", "https://api.x.com", api_key="sk", default_model="m")
    factory.register_custom_provider("card_y", "https://api.y.com", api_key="sk", default_model="m")
    factory.set_provider_status(["card_y"], {}, {})
    assert provider_available("card_x")
    assert not provider_available("card_y")  # 被禁
    assert not provider_available("nonexistent")


def test_rank_providers_sinks_open_circuit() -> None:
    """熔断中的 provider 沉底，其余保持原顺序。"""
    health.record_failure("qwen", "认证失败(密钥无效)")
    assert rank_providers(["qwen", "glm"]) == ["glm", "qwen"]
    health.record_success("qwen")
    assert rank_providers(["qwen", "glm"]) == ["qwen", "glm"]


def test_validate_output_basics() -> None:
    """格式校验：坏 JSON / 空 / 拒答判坏，中文散文与合法 JSON 放行。"""
    ok = lambda m: validate_output(AIMessage(content=m))[0]  # noqa: E731
    assert ok('{"a": 1}')
    assert ok("这是一段中文自由分析。")
    assert not ok("")
    assert not ok('{"a": 1,,,')
    assert not ok("作为AI语言模型，我无法提供该建议。")
