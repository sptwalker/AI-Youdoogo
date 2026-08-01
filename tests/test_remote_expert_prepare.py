"""RemoteAgentExecutionApplication 编排缝测试（Module 2 / docs/23 §6.2）——纯 stub，离线。

不导入远端 ``expert`` 包（youdoo venv 无此包）、不碰 youdoo 库、不用真密钥：本地 DB 读函数
（resolve_configuration/term_prompt/agent_visible_knowledge_base_ids）与 mint 均 monkeypatch。
覆盖：本地读随体传远端 + 转发令牌（scope/actor）、sources 回流、record 记账、首 delta 前回退本地。
真·跨仓 parity（远端组装与本地逐字一致）走 Todo 5 双服务真 HTTP 验收。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutionStreamEvent,
    ExecutionTrace,
    LlmStreamChunk,
    SourceReference,
    TokenUsage,
)
from app.contexts.foundations.execution.agent_execution.infrastructure import (
    remote_application as ra,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_application import (
    RemoteAgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_execution_adapter import (  # noqa: E501
    ExpertPlatformError,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

EXPERT = ExpertExecutionSnapshot(
    expert_id=uuid.UUID(int=1),
    version="v1",
    name="财务",
    title="CFO",
    department_id=None,
    prompt_template="模板",
    model_role="daily",
)
USER_ID = uuid.UUID(int=42)


def _request(
    *, use_knowledge: bool = False, user_id: uuid.UUID | None = None
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        expert=EXPERT,
        task_type="t",
        input_summary="s",
        user_message="利润多少",
        user_id=user_id,
        use_knowledge=use_knowledge,
        trace=ExecutionTrace(),
    )


@pytest.fixture(autouse=True)
def _patch_local_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(session: object, key: str, default: object = None) -> object:
        return "全局提示"

    async def fake_term(session: object) -> str:
        return "术语"

    async def fake_kb(
        session: object, *, department_id: object, owner_agent_id: object = None
    ) -> list[uuid.UUID]:
        return [uuid.UUID(int=7)]

    monkeypatch.setattr(ra, "resolve_configuration", fake_resolve)
    monkeypatch.setattr(ra, "term_prompt", fake_term)
    monkeypatch.setattr(ra, "agent_visible_knowledge_base_ids", fake_kb)


def _chunk(delta: str, acc: str, *, model: str | None = None) -> LlmStreamChunk:
    return LlmStreamChunk(delta=delta, accumulated_content=acc, model=model, usage=TokenUsage())


class StubPrepare:
    def __init__(
        self,
        *,
        chunks: list[LlmStreamChunk],
        sources: tuple[SourceReference, ...] = (),
        fail: bool = False,
    ) -> None:
        self.chunks = chunks
        self.sources = sources
        self.fail = fail
        self.create_kwargs: dict[str, object] = {}

    async def create(
        self,
        expert_id: str,
        *,
        model_role: str,
        user_message: str,
        use_knowledge: bool,
        knowledge_base_ids: list[str] | None,
        knowledge_token: str | None,
        global_prompt: str,
        term_prompt: str,
        temperature: float = 0.3,
        gateway_token: str | None = None,
    ) -> tuple[str, tuple[SourceReference, ...]]:
        self.create_kwargs = {
            "expert_id": expert_id,
            "model_role": model_role,
            "use_knowledge": use_knowledge,
            "knowledge_base_ids": knowledge_base_ids,
            "knowledge_token": knowledge_token,
            "gateway_token": gateway_token,
            "global_prompt": global_prompt,
            "term_prompt": term_prompt,
        }
        if self.fail:
            raise ExpertPlatformError("远端不可达")
        return "exec-1", self.sources

    def stream(self, execution_id: str) -> AsyncIterator[LlmStreamChunk]:
        async def _it() -> AsyncIterator[LlmStreamChunk]:
            for c in self.chunks:
                yield c

        return _it()


class AllowAuth:
    def authorize(self, request: AgentExecutionRequest) -> None:
        return None


class StubRecorder:
    def __init__(self) -> None:
        self.recorded: list[AgentExecutionResult] = []

    async def record(
        self, request: AgentExecutionRequest, result: AgentExecutionResult
    ) -> AgentExecutionResult:
        self.recorded.append(result)
        return result


class StubClock:
    def monotonic_ms(self) -> int:
        return 0


class StubFallback:
    def __init__(self) -> None:
        self.execute_called = False
        self.stream_called = False

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.execute_called = True
        return AgentExecutionResult(
            status=AgentExecutionStatus.SUCCEEDED, trace=request.trace, content="本地兜底"
        )

    async def stream(
        self, request: AgentExecutionRequest
    ) -> AsyncIterator[AgentExecutionStreamEvent]:
        self.stream_called = True
        yield AgentExecutionStreamEvent(delta="本地")
        yield AgentExecutionStreamEvent(
            result=AgentExecutionResult(
                status=AgentExecutionStatus.SUCCEEDED, trace=request.trace, content="本地兜底"
            )
        )


def _app(
    prepare: StubPrepare, fallback: StubFallback, *, forward_gateway_token: bool = False
) -> tuple[RemoteAgentExecutionApplication, StubRecorder]:
    recorder = StubRecorder()
    app = RemoteAgentExecutionApplication(
        session=object(),  # type: ignore[arg-type]  # 未用：boundary=None 且 DB 读已 monkeypatch
        prepare=prepare,  # type: ignore[arg-type]
        usage_authorization=AllowAuth(),
        recorder=recorder,
        clock=StubClock(),
        fallback=fallback,  # type: ignore[arg-type]
        forward_gateway_token=forward_gateway_token,
    )
    return app, recorder


async def test_execute_passes_local_reads_and_records() -> None:
    """无知识：本地读 global/term 随体传远端，model_role 经映射，sources 空，record 记一次。"""
    prepare = StubPrepare(chunks=[_chunk("利润多少", "利润多少", model="echo-default")])
    app, recorder = _app(prepare, StubFallback())

    result = await app.execute(_request())

    assert result.status is AgentExecutionStatus.SUCCEEDED
    assert result.content == "利润多少"
    assert result.model == "echo-default"
    assert result.sources == ()
    assert recorder.recorded == [result]
    # 本地留读、远端做算：daily→default 映射 + 全局/术语随体，无知识时 ids/token 为 None。
    assert prepare.create_kwargs["model_role"] == "default"
    assert prepare.create_kwargs["global_prompt"] == "全局提示"
    assert prepare.create_kwargs["term_prompt"] == "术语"
    assert prepare.create_kwargs["knowledge_base_ids"] is None
    assert prepare.create_kwargs["knowledge_token"] is None


async def test_execute_with_knowledge_relays_token_and_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有知识：解析可见库 id 随体 + mint 转发令牌（aud=知识服务, scope=knowledge:search）。"""
    captured: dict[str, object] = {}

    def fake_mint(
        *, service_id: str, audience: str, scope: tuple[str, ...] = (), actor_id: str | None = None
    ) -> str:
        captured.update(audience=audience, scope=scope, actor_id=actor_id)
        return "relay-tok"

    monkeypatch.setattr(ra, "mint_internal_token", fake_mint)
    src = (SourceReference(file_id="doc-9", file_name="财报", chunk_index=2),)
    prepare = StubPrepare(chunks=[_chunk("x", "x", model="echo-default")], sources=src)
    app, _ = _app(prepare, StubFallback())

    result = await app.execute(_request(use_knowledge=True, user_id=USER_ID))

    assert result.sources == src
    assert prepare.create_kwargs["use_knowledge"] is True
    assert prepare.create_kwargs["knowledge_base_ids"] == [str(uuid.UUID(int=7))]
    assert prepare.create_kwargs["knowledge_token"] == "relay-tok"
    assert captured["audience"] == "ai-knowledge-service"
    assert captured["scope"] == ("knowledge:search",)
    assert captured["actor_id"] == str(USER_ID)


async def test_execute_falls_back_before_first_chunk() -> None:
    """首 delta 前远端失败 → 委托本地兜底应用；远端 recorder 不记（本地自行记账）。"""
    prepare = StubPrepare(chunks=[], fail=True)
    fallback = StubFallback()
    app, recorder = _app(prepare, fallback)

    result = await app.execute(_request())

    assert fallback.execute_called
    assert result.content == "本地兜底"
    assert recorder.recorded == []


async def test_stream_yields_deltas_then_result() -> None:
    """流式：先逐 delta，末尾一枚带 result 的终帧（content 为末块累积）。"""
    prepare = StubPrepare(
        chunks=[_chunk("利润", "利润", model="echo-default"), _chunk("多少", "利润多少")]
    )
    app, recorder = _app(prepare, StubFallback())

    events = [e async for e in app.stream(_request())]

    assert [e.delta for e in events if e.delta] == ["利润", "多少"]
    final = events[-1].result
    assert final is not None
    assert final.content == "利润多少"
    assert recorder.recorded == [final]


async def test_stream_falls_back_before_first_chunk() -> None:
    prepare = StubPrepare(chunks=[], fail=True)
    fallback = StubFallback()
    app, _ = _app(prepare, fallback)

    events = [e async for e in app.stream(_request())]

    assert fallback.stream_called
    assert events[-1].result is not None
    assert events[-1].result.content == "本地兜底"


# --- 真·网关执行器转发（docs/23 §6.4）：门控 expert_forward_gateway_token ---


@pytest.fixture
def _gateway_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """给 settings 单例注入一对真 EC 密钥（真 mint→真 verify，非 monkeypatch mint）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.core.config import get_settings

    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = get_settings()
    monkeypatch.setattr(settings, "internal_jwt_private_key", priv)
    monkeypatch.setattr(settings, "internal_jwt_public_key", "")  # 派生自私钥
    monkeypatch.setattr(settings, "internal_jwt_issuer", "youdoogo-platform")


async def test_forward_on_mints_valid_gateway_token(_gateway_keys: None) -> None:
    """flag=on：gateway_token 是真 JWT，verify(aud=网关) 通过含 llm:complete，错 aud 被拒。"""
    from app.contexts.shared_kernel import AuthenticationFailed
    from app.core.internal_token import verify_internal_token

    prepare = StubPrepare(chunks=[_chunk("x", "x", model="ds")])
    app, _ = _app(prepare, StubFallback(), forward_gateway_token=True)

    await app.execute(_request(user_id=USER_ID))

    token = prepare.create_kwargs["gateway_token"]
    assert isinstance(token, str) and token
    claims = verify_internal_token(token, audience="ai-model-gateway")
    assert "llm:complete" in claims.scope
    assert claims.actor_id == str(USER_ID)
    with pytest.raises(AuthenticationFailed):
        verify_internal_token(token, audience="ai-knowledge-service")  # 错 aud → 拒


async def test_forward_off_sends_no_gateway_token() -> None:
    """flag=off（默认）：不 mint，body gateway_token 为 None → 远端回落 echo。"""
    prepare = StubPrepare(chunks=[_chunk("x", "x", model="echo-default")])
    app, _ = _app(prepare, StubFallback())  # forward_gateway_token 默认 False

    await app.execute(_request(user_id=USER_ID))

    assert prepare.create_kwargs["gateway_token"] is None
