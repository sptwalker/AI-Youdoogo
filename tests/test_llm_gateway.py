"""多模型网关单测：假模型 failover + 角色注册表（不发真实请求、不消耗额度）。"""

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

# factory 现经 runtime_config 取密钥；测试 patch 其读取的 get_settings。
from app.core import runtime_config as rc_mod
from app.llm import (
    FallbackChatModel,
    NoAvailableProviderError,
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
def _reset_health() -> None:
    """每个用例前清空熔断状态，避免用例间串扰。"""
    health.reset()


def _fake_settings(**keys: str) -> SimpleNamespace:
    base = {
        "deepseek_api_key": "",
        "dashscope_api_key": "",
        "zhipu_api_key": "",
        "anthropic_api_key": "",
    }
    base.update(keys)
    return SimpleNamespace(**base)


def test_fallback_switches_to_second_candidate() -> None:
    """主模型恒失败 → 自动切换到第二候选并返回其文本。"""
    echo = _EchoModel()
    fb = FallbackChatModel(
        candidates=[(_BoomModel(), "deepseek", "deepseek-chat"), (echo, "qwen", "qwen-plus")]
    )
    result = fb.invoke("你好")
    assert result.content == echo.text
    # 失败的 provider 应进入熔断冷却期
    assert health.is_open("deepseek")
    assert not health.is_open("qwen")


def test_fallback_all_failed_raises() -> None:
    """全部候选失败 → 抛最后一个异常。"""
    fb = FallbackChatModel(candidates=[(_BoomModel(), "deepseek", "deepseek-chat")])
    with pytest.raises(TimeoutError):
        fb.invoke("你好")


def test_get_llm_for_role_builds_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """有 DeepSeek 密钥时 ops_director 能构造出 FallbackChatModel，主候选为 deepseek-chat。"""
    monkeypatch.setattr(
        rc_mod, "get_settings",
        lambda: _fake_settings(deepseek_api_key="sk-test", dashscope_api_key="sk-test2"),
    )
    llm = get_llm_for_role("ops_director")
    assert isinstance(llm, FallbackChatModel)
    assert llm.candidates[0][1:] == ("deepseek", "deepseek-chat")
    # 降级链中已配密钥的 qwen 应在候选内，无密钥的 glm 被跳过
    providers = [c[1] for c in llm.candidates]
    assert providers == ["deepseek", "qwen"]


def test_get_llm_for_role_no_keys_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """整条链均无密钥 → 抛 NoAvailableProviderError（约定：抛明确异常而非返回空）。"""
    monkeypatch.setattr(rc_mod, "get_settings", lambda: _fake_settings())
    with pytest.raises(NoAvailableProviderError):
        get_llm_for_role("ops_director")


def test_unknown_role_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知 role_key 回退 default 角色。"""
    monkeypatch.setattr(
        rc_mod, "get_settings", lambda: _fake_settings(deepseek_api_key="sk-test")
    )
    llm = get_llm_for_role("no_such_role")
    assert llm.candidates[0][1:] == ("deepseek", "deepseek-chat")


def test_provider_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """没密钥不可用、有密钥可用；未知 provider 恒不可用。"""
    monkeypatch.setattr(
        rc_mod, "get_settings", lambda: _fake_settings(zhipu_api_key="sk-test")
    )
    assert provider_available("glm")
    assert not provider_available("deepseek")
    assert not provider_available("kimi")  # Settings 暂无密钥字段
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
