"""反馈评分 + 提示词优化链单测（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.governance.ai_quality import public as ai_quality
from app.contexts.foundations.model_gateway import public as model_gateway
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord


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


async def test_public_feedback_operations(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID],
) -> None:
    session, role_id, record_id = ctx
    rater_id = uuid.uuid4()

    result = await ai_quality.record_feedback(
        session,
        ai_quality.RecordFeedbackCommand(
            task_record_id=record_id,
            rater_id=rater_id,
            score=2,
            comment="缺来源",
        ),
    )
    samples = await ai_quality.list_low_score_samples(session, role_id)

    assert result.task_record_id == record_id
    assert result.rater_id == rater_id
    assert result.score == 2
    assert samples == (ai_quality.LowScoreSample("日报正文……", 2, "缺来源"),)


async def test_public_prompt_improvement_operation(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, role_id, record_id = ctx
    monkeypatch.setattr(model_gateway, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    await ai_quality.record_feedback(
        session,
        ai_quality.RecordFeedbackCommand(
            task_record_id=record_id,
            rater_id=uuid.uuid4(),
            score=2,
            comment="缺来源标注",
        ),
    )

    suggestion = await ai_quality.suggest_prompt_improvement(session, role_id)

    assert suggestion.based_on_samples == 1
    assert suggestion.current_prompt == "你是运营AI总监。"
    assert "改进后的提示词" in suggestion.suggested_prompt
