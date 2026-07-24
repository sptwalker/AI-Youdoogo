"""技能注册表单测（docs/13 §11，内存 SQLite，不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, skills
from app.contexts.business.collaboration_requests.entrypoints import (
    agent_capability as collaboration_capability,
)
from app.models import Base
from app.models.agent import AgentRole


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _role(tools: list[Any] | None = None) -> AgentRole:
    return AgentRole(name=f"AI-{uuid.uuid4().hex[:6]}", prompt_template="x", tools=tools or [])


# ── enabled_skills 语义 ─────────────────────────────────
def test_enabled_empty_means_default_all_on() -> None:
    keys = {s.key for s in skills.enabled_skills(_role([]))}
    assert keys == {s.key for s in skills.REGISTRY.values() if s.default_on}


def test_enabled_explicit_list() -> None:
    assert [s.key for s in skills.enabled_skills(_role(["collab"]))] == ["collab"]


def test_enabled_unknown_keys_ignored_and_all_off() -> None:
    assert [s.key for s in skills.enabled_skills(_role(["collab", "no_such"]))] == ["collab"]
    assert skills.enabled_skills(_role(["none"])) == []  # 全无效列表 = 全关
    assert skills.enabled_skills(_role([123, {"k": 1}])) == []  # 非 str 项忽略


# ── prompt_sections ────────────────────────────────────
async def test_prompt_sections_respects_tools(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tools=["collab"] → 只含协作段不含快照；空 → 两段都有。"""

    async def _fake_env(_db: AsyncSession) -> str:
        return "快照内容"

    monkeypatch.setattr(
        "app.contexts.foundations.environment_projection.public.get_env_context",
        _fake_env,
    )
    only_collab = await skills.prompt_sections(db, _role(["collab"]))
    assert "【协作能力】" in only_collab and "【系统环境快照】" not in only_collab
    both = await skills.prompt_sections(db, _role([]))
    assert "【协作能力】" in both and "【系统环境快照】" in both


async def test_prompt_sections_flag_off(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全局急停关 → 该技能段消失。"""

    async def _off(_db: AsyncSession, key: str, default: Any) -> Any:
        return False if key == "agent_collab_protocol" else default

    monkeypatch.setattr(skills.config_service, "resolve", _off)
    out = await skills.prompt_sections(db, _role(["collab"]))
    assert "【协作能力】" not in out


async def test_prompt_sections_single_skill_failure_isolated(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """单技能异常不阻断其余技能。"""

    async def _boom(_db: AsyncSession) -> str:
        raise RuntimeError("env down")

    monkeypatch.setattr(
        "app.contexts.foundations.environment_projection.public.get_env_context",
        _boom,
    )
    out = await skills.prompt_sections(db, _role([]))
    assert "【协作能力】" in out  # collab 不受 env 故障影响


# ── execute_all 门控 ────────────────────────────────────
async def test_execute_all_gated_by_tools(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未启用 collab 的 AI 输出指令也不执行；启用则透传 ProtocolResult。"""
    calls: list[str] = []

    async def _spy(
        _db: AsyncSession, initiator: AgentRole, output: str, *, user_id: Any = None
    ) -> collaboration_capability.ProtocolResult:
        calls.append(output)
        return collaboration_capability.ProtocolResult(notes=["done"])

    monkeypatch.setattr(collaboration_capability, "execute", _spy)
    text = "【咨询 @财务总监】预算？"

    r1 = await skills.execute_all(db, _role(["env_context"]), text)
    assert calls == [] and r1.notes == []

    r2 = await skills.execute_all(db, _role([]), text)  # 默认全开
    assert calls == [text] and r2.notes == ["done"]


async def test_prepare_uses_skills(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """base._prepare 经技能层拼提示词：tools 限定后无协作段。"""

    async def _fake_env(_db: AsyncSession) -> str:
        return "快照"

    monkeypatch.setattr(
        "app.contexts.foundations.environment_projection.public.get_env_context",
        _fake_env,
    )
    role = _role(["env_context"])
    _, system, _, _ = await base._prepare(db, role, "hi", use_knowledge=False)
    assert "【系统环境快照】" in system and "【协作能力】" not in system
