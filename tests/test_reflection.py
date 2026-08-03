"""反思/critic 回路单测（H4.3，docs/16）:critic 解析纯函数 + reflect 三路径（打桩 LLM）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.governance.ai_quality import public as ai_quality
from app.contexts.foundations.governance.ai_quality.infrastructure import (
    output_review as reflection_service,
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


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="专家", prompt_template="x", model_role="reasoning")


# ── parse_critic 纯函数 ─────────────────────────────────
def test_parse_critic_score_and_issues() -> None:
    score, issues = reflection_service.parse_critic("2\n- 遗漏了风险分析\n- 数据无来源")
    assert score == 2 and "遗漏了风险" in issues and "数据无来源" in issues


def test_parse_critic_no_issues() -> None:
    score, issues = reflection_service.parse_critic("5\n无")
    assert score == 5 and issues == "无"


def test_parse_critic_only_score() -> None:
    score, issues = reflection_service.parse_critic("4")
    assert score == 4 and issues == "无"


# ── reflect 三路径 ──────────────────────────────────────
async def test_reflect_high_score_no_rewrite(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """critic 高分 → 不重写，原样返回。"""
    async def _critique(*a: Any, **k: Any) -> tuple[int, str]:
        return 5, "无"

    monkeypatch.setattr(reflection_service.LangChainOutputCritic, "critique", _critique)
    role = _role()
    res = await ai_quality.review_output(
        db,
        ai_quality.OutputReviewRequest(
            expert_id=role.id,
            output="很好的产出",
            task_context="任务",
            rubric="r",
        ),
    )
    assert res.revised is False and res.final_output == "很好的产出"
    assert res.critic_score == 5


async def test_reflect_low_score_rewrites(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """critic 低分 + 有问题 → 带问题重写，取重写版。"""
    async def _critique(*a: Any, **k: Any) -> tuple[int, str]:
        return 2, "- 遗漏风险分析"

    async def _revise(*a: Any, **k: Any) -> str:
        return "补充了风险分析的修订版产出"

    monkeypatch.setattr(reflection_service.LangChainOutputCritic, "critique", _critique)
    monkeypatch.setattr(reflection_service.AgentOutputRevision, "revise", _revise)
    role = _role()
    res = await ai_quality.review_output(
        db,
        ai_quality.OutputReviewRequest(
            expert_id=role.id,
            output="初稿",
            task_context="任务",
            rubric="r",
        ),
    )
    assert res.revised is True
    assert res.final_output == "补充了风险分析的修订版产出"
    assert res.original_output == "初稿" and res.critic_score == 2


async def test_reflect_empty_output(db: AsyncSession) -> None:
    """空产出 → 直接返回，不触发 critic。"""
    role = _role()
    res = await ai_quality.review_output(
        db,
        ai_quality.OutputReviewRequest(
            expert_id=role.id,
            output="   ",
            task_context="t",
            rubric="r",
        ),
    )
    assert res.revised is False and res.critic_score == 0


async def test_reflect_degrades_on_error(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """critic 抛错 → 退回初稿，不抛。"""
    async def _boom(*a: Any, **k: Any) -> tuple[int, str]:
        raise RuntimeError("critic 模型不可用")

    monkeypatch.setattr(reflection_service.LangChainOutputCritic, "critique", _boom)
    role = _role()
    res = await ai_quality.review_output(
        db,
        ai_quality.OutputReviewRequest(
            expert_id=role.id,
            output="初稿",
            task_context="t",
            rubric="r",
        ),
    )
    assert res.revised is False and res.final_output == "初稿"


async def test_reflect_rewrite_empty_falls_back(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重写返回空 → 保留初稿（不因重写失败丢产出）。"""
    async def _critique(*a: Any, **k: Any) -> tuple[int, str]:
        return 2, "- 有问题"

    async def _revise(*a: Any, **k: Any) -> str:
        return ""

    monkeypatch.setattr(reflection_service.LangChainOutputCritic, "critique", _critique)
    monkeypatch.setattr(reflection_service.AgentOutputRevision, "revise", _revise)
    role = _role()
    res = await ai_quality.review_output(
        db,
        ai_quality.OutputReviewRequest(
            expert_id=role.id,
            output="初稿",
            task_context="t",
            rubric="r",
        ),
    )
    assert res.revised is False and res.final_output == "初稿"


def test_metadata_excludes_body() -> None:
    """as_metadata 只含分数/问题/重写标记，不含正文。"""
    r = ai_quality.OutputReviewResult(
        final_output="正文", critic_score=3, issues="x", revised=True,
    )
    meta = r.as_metadata()
    assert meta == {"critic_score": 3, "issues": "x", "revised": True}
    assert "正文" not in str(meta)
