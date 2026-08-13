"""读网页技能单测（离线）：指令解析、SSRF 防护（拒私有 IP / 拒重定向到内网）、trafilatura 抽正文、
闭环回喂结合知识库、链式派发、注入防护 fence、注册表成员。仿 test_web_search_skill.py。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.contracts import ExecutionContext, SkillResult
from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.foundations.integration.read_url.entrypoints import (
    agent_capability,
    operations,
)
from app.contexts.foundations.integration.read_url.infrastructure.connector import (
    ReadUrlOutcome,
    UrlReader,
)
from app.models import Base
from app.models.agent import AgentRole
from app.platform import net

_HTML = (
    "<!DOCTYPE html><html><head><title>测试文章标题</title></head><body>"
    "<article><h1>测试文章标题</h1>"
    "<p>人工智能正在深刻改变现代企业的经营决策方式，越来越多的公司开始借助智能体来辅助分析。</p>"
    "<p>本文进一步阐述了智能决策系统如何结合企业内部知识库，为管理者提供可追溯的建议与洞察。</p>"
    "</article></body></html>"
)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="分析助理", prompt_template="x", tools=[])


# ── parse ───────────────────────────────────────────────
def test_parse_extracts_url() -> None:
    out = "我读一下：\n【读网页】https://example.com/article\n然后综合"
    assert agent_capability.parse(out) == ["https://example.com/article"]


def test_parse_strips_trailing_punct() -> None:
    assert agent_capability.parse("【读网页】https://example.com/a。") == ["https://example.com/a"]


def test_parse_truncates_to_two() -> None:
    out = "\n".join(f"【读网页】https://example.com/{i}" for i in range(5))
    assert len(agent_capability.parse(out)) == 2


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复无读网页") == []


def test_parse_ignores_non_http_scheme() -> None:
    assert agent_capability.parse("【读网页】ftp://example.com/x") == []


# ── SSRF 防护 ───────────────────────────────────────────
def test_url_is_safe_rejects_non_http() -> None:
    ok, reason = net.url_is_safe("ftp://example.com/x")
    assert ok is False and "http" in reason


def test_url_is_safe_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["10.0.0.5"])
    ok, reason = net.url_is_safe("http://intranet.local/secret")
    assert ok is False and "SSRF" in reason


def test_url_is_safe_rejects_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["127.0.0.1"])
    ok, _reason = net.url_is_safe("http://localhost/x")
    assert ok is False


def test_url_is_safe_rejects_ipv4_mapped_v6(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["::ffff:10.0.0.1"])
    ok, _reason = net.url_is_safe("http://sneaky.example/x")
    assert ok is False  # IPv4-mapped IPv6 不能绕过内网判定


def test_url_is_safe_rejects_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: [])
    ok, _reason = net.url_is_safe("https://nonexistent.invalid/x")
    assert ok is False


def test_url_is_safe_allows_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])
    ok, reason = net.url_is_safe("https://example.com/x")
    assert ok is True and reason == ""


# ── fetch（抓取 + 抽正文，MockTransport 离线）──────────────
async def test_fetch_extracts_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_HTML.encode(), headers={"content-type": "text/html; charset=utf-8"}
        )

    outcome = await UrlReader().fetch(
        "https://example.com/a", transport=httpx.MockTransport(_handler)
    )
    assert len(outcome.results) == 1
    assert outcome.results[0]["url"] == "https://example.com/a"
    assert "人工智能" in outcome.results[0]["text"]


async def test_fetch_follows_safe_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://example.com/final"})
        return httpx.Response(200, content=_HTML.encode(), headers={"content-type": "text/html"})

    outcome = await UrlReader().fetch(
        "https://example.com/start", transport=httpx.MockTransport(_handler)
    )
    assert len(outcome.results) == 1 and "人工智能" in outcome.results[0]["text"]


async def test_fetch_rejects_redirect_to_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = {"safe.example": ["93.184.216.34"], "evil.internal": ["10.0.0.5"]}
    monkeypatch.setattr(net, "resolve_ips", lambda host: resolved.get(host, []))
    calls = {"n": 0}

    def _handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(302, headers={"location": "http://evil.internal/secret"})

    outcome = await UrlReader().fetch(
        "http://safe.example/a", transport=httpx.MockTransport(_handler)
    )
    assert outcome.results == [] and "SSRF" in outcome.reason
    assert calls["n"] == 1  # 只请求了首跳；重定向目标在连接前被 SSRF 拦下


async def test_fetch_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    outcome = await UrlReader().fetch(
        "https://example.com/a", transport=httpx.MockTransport(_handler)
    )
    assert outcome.results == [] and "重定向次数过多" in outcome.reason


async def test_fetch_rejects_non_html(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    outcome = await UrlReader().fetch(
        "https://example.com/a.pdf", transport=httpx.MockTransport(_handler)
    )
    assert outcome.results == [] and "不是网页" in outcome.reason


async def test_fetch_http_error_no_throw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    outcome = await UrlReader().fetch(
        "https://example.com/a", transport=httpx.MockTransport(_handler)
    )
    assert outcome.results == [] and outcome.reason  # 不抛穿，返结构化原因


async def test_fetch_empty_body_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "text/html"})

    outcome = await UrlReader().fetch(
        "https://example.com/a", transport=httpx.MockTransport(_handler)
    )
    assert outcome.results == [] and outcome.reason


# ── 自门控 ──────────────────────────────────────────────
async def test_prompt_section_advertises() -> None:
    section = await agent_capability.prompt_section()
    assert "【读网页】" in section and "读网页" in section


async def test_prompt_section_gated_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable() -> bool:
        return False

    monkeypatch.setattr(operations, "read_url_available", _unavailable)
    assert await agent_capability.prompt_section() == ""


# ── execute:闭环回喂 + 结合知识库 ───────────────────────
class _Rec:
    output_content = "关键结论：文章讲 AI 决策。\n## 详情\n- 要点一\n- 要点二"
    error_msg = None


async def test_execute_interprets_with_knowledge(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """抓取网页 → 回喂 run_agent（use_knowledge=True）→ 解读作为 consult_replies 追加消息。"""

    async def _fake_read(url: str) -> ReadUrlOutcome:
        return ReadUrlOutcome(
            results=[{"title": "外部标题", "url": "http://x", "text": "外部正文内容片段"}]
        )

    fed: dict[str, Any] = {}

    async def _fake_agent(_db: Any, agent: Any, **kw: Any) -> _Rec:
        fed["prompt"] = kw.get("user_message")
        fed["use_knowledge"] = kw.get("use_knowledge")
        fed["task_type"] = kw.get("task_type")
        fed["agent"] = agent
        return _Rec()

    expert = object()  # runner 现在收专家执行快照；fake runner 只记录不访问属性

    async def _fake_execution(_db: Any, _expert_id: Any) -> Any:
        return expert

    monkeypatch.setattr(operations, "run_read_url", _fake_read)
    monkeypatch.setattr(
        agent_capability.expert_management, "get_expert_execution", _fake_execution
    )
    role = _role()
    res = await agent_capability.execute(
        db, role, "【读网页】https://x.com/a", user_id=uuid.uuid4(), agent_runner=_fake_agent
    )
    assert fed["use_knowledge"] is True  # 综合轮折进知识库
    assert fed["task_type"] == "read_url_synthesis"
    assert fed["agent"] is expert  # runner 收到专家执行快照，而非 legacy role
    # 注入防护 fence + 安全须知出现在解读 prompt
    assert agent_capability._FENCE_OPEN in fed["prompt"]
    assert "不得执行" in fed["prompt"] and "外部正文内容片段" in fed["prompt"]
    # 结果进 datasets；解读作为独立消息进 consult_replies
    assert len(res.datasets) == 1 and res.datasets[0]["url"] == "https://x.com/a"
    assert len(res.consult_replies) == 1 and res.consult_replies[0][0].expert_id == role.id
    assert res.notes == []


async def test_execute_no_results_becomes_note_no_interpret(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_read(url: str) -> ReadUrlOutcome:
        return ReadUrlOutcome(results=[], reason="未能从网页提取正文（可能是脚本渲染页或空页）")

    agent_called = False

    async def _fake_agent(*a: Any, **k: Any) -> Any:
        nonlocal agent_called
        agent_called = True

    monkeypatch.setattr(operations, "run_read_url", _fake_read)
    res = await agent_capability.execute(
        db, _role(), "【读网页】https://x.com/a", user_id=None, agent_runner=_fake_agent
    )
    assert len(res.notes) == 1 and "无结果" in res.notes[0]
    assert res.consult_replies == [] and agent_called is False


async def test_execute_no_directive_fast_path(db: AsyncSession) -> None:
    res = await agent_capability.execute(db, _role(), "无读网页的普通回复", user_id=None)
    assert res.notes == [] and res.consult_replies == []


async def test_interpret_round_dispatches_chained_deliver(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """解读轮 AI 写【交付】→ 递归 dispatch_text（exclude={"read_url"}）捕获链式指令。"""

    async def _fake_read(url: str) -> ReadUrlOutcome:
        return ReadUrlOutcome(results=[{"title": "T", "url": "u", "text": "正文"}])

    class _Record:
        output_content = "关键结论。\n【交付】名称：网页摘要；格式：md\n```\n内容\n```"
        error_msg = None

    async def _fake_agent(*a: Any, **k: Any) -> _Record:
        return _Record()

    async def _fake_execution(_db: Any, _expert_id: Any) -> Any:
        return object()

    captured: dict[str, Any] = {}

    class _Dispatcher:
        async def dispatch(
            self, session: AsyncSession, role: AgentRole, request: Any, context: ExecutionContext
        ) -> SkillResult:
            return await agent_capability.ReadUrlSkillExecutor().execute(
                session, role, request, context
            )

        async def dispatch_text(
            self,
            _session: AsyncSession,
            _role: AgentRole,
            output: str,
            _context: ExecutionContext,
            *,
            exclude: set[str] | None = None,
        ) -> SkillResult:
            captured["output"] = output
            captured["exclude"] = exclude
            return SkillResult(artifacts=[{"file_name": "网页摘要.md"}])

    monkeypatch.setattr(operations, "run_read_url", _fake_read)
    monkeypatch.setattr(
        agent_capability.expert_management, "get_expert_execution", _fake_execution
    )
    context = ExecutionContext(dispatcher=_Dispatcher(), agent_runner=_fake_agent)
    res = await agent_capability.execute(
        db, _role(), "【读网页】https://x.com/a", execution_context=context
    )
    assert captured["exclude"] == {"read_url"}
    assert "【交付】" in captured["output"]
    assert len(res.artifacts) == 1 and res.artifacts[0]["file_name"] == "网页摘要.md"


# ── 注册表 ──────────────────────────────────────────────
def test_read_url_registered_and_default_on() -> None:
    assert "read_url" in REGISTRY
    skill = REGISTRY["read_url"]
    assert skill.default_on is True and skill.legacy_executor is not None
    assert skill.executor_factory is not None
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 默认全开
    assert "read_url" in keys
