"""反馈评分 + 提示词优化链单测（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.services import feedback_service


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="改进后的提示词：更强调数据来源与结论优先级。")


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        role = AgentRole(name="运营AI总监", prompt_template="你是运营AI总监。", model_role="daily")
        session.add(role)
        await session.flush()
        record = AgentTaskRecord(
            agent_role_id=role.id, task_type="daily_report",
            output_content="日报正文……", status="success",
        )
        session.add(record)
        await session.commit()
        yield session, role.id, record.id
    await engine.dispose()


async def test_add_feedback(ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID]) -> None:
    session, _, record_id = ctx
    fb = await feedback_service.add_feedback(
        session, task_record_id=record_id, rater_id=uuid.uuid4(), score=2, comment="缺来源"
    )
    assert fb.score == 2


async def test_add_feedback_score_range(ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID]) -> None:
    session, _, record_id = ctx
    with pytest.raises(AppError, match="1~5"):
        await feedback_service.add_feedback(
            session, task_record_id=record_id, rater_id=uuid.uuid4(), score=9
        )


async def test_add_feedback_missing_record(ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID]) -> None:
    session, _, _ = ctx
    with pytest.raises(AppError, match="不存在"):
        await feedback_service.add_feedback(
            session, task_record_id=uuid.uuid4(), rater_id=uuid.uuid4(), score=3
        )


async def test_optimize_prompt_from_low_scores(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    session, role_id, record_id = ctx
    monkeypatch.setattr(feedback_service, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    await feedback_service.add_feedback(
        session, task_record_id=record_id, rater_id=uuid.uuid4(), score=2, comment="缺来源标注"
    )
    result = await feedback_service.optimize_prompt(session, role_id)
    assert result["based_on_samples"] == 1
    assert "改进后的提示词" in str(result["suggested_prompt"])
    assert result["current_prompt"] == "你是运营AI总监。"


async def test_optimize_prompt_no_low_scores(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID],
) -> None:
    session, role_id, record_id = ctx
    await feedback_service.add_feedback(
        session, task_record_id=record_id, rater_id=uuid.uuid4(), score=5
    )  # 高分不入优化样本
    with pytest.raises(AppError, match="无需优化"):
        await feedback_service.optimize_prompt(session, role_id)
