"""智能体核心 + 运营日报单测（假模型 + 内存 SQLite，不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, ops
from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord

_ROWS = [
    {
        "stat_date": "2026-07-11", "product": "产品A",
        "dau": 1234, "new_users": 56, "retention_d1": 42.5,
    },
    {"stat_date": "2026-07-11", "product": "产品B", "dau": 2000},
]


class _FakeLLM:
    """假模型：可返回固定文本或抛异常，覆盖成功/失败留痕两条路径。"""

    def __init__(self, text: str = "", metadata: dict | None = None, exc: Exception | None = None):
        self._text = text
        self._metadata = metadata or {}
        self._exc = exc

    async def ainvoke(self, messages: list, **kwargs: Any) -> AIMessage:
        if self._exc is not None:
            raise self._exc
        return AIMessage(content=self._text, response_metadata=self._metadata)


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """内存库 + 预置运营AI总监角色。"""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            AgentRole(
                name="平台运营部总监助理",
                code=ops.OPS_DIRECTOR_CODE,
                prompt_template="你是平台运营部总监助理。",
                model_role="daily",
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


def test_format_metrics_renders_rows() -> None:
    text = ops.format_metrics(_ROWS)
    assert "日活" in text and "1234" in text
    assert "-" in text.splitlines()[-1]  # 产品B 缺 new_users/retention 以 - 占位


async def test_generate_daily_report_success(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        base, "get_llm_for_role",
        lambda *a, **k: _FakeLLM(
            text="【核心指标概览】...", metadata={"model_name": "deepseek-chat"}
        ),
    )
    operator = uuid.uuid4()
    record = await ops.generate_daily_report(
        db, stat_date="2026-07-11", rows=_ROWS, operator_id=operator
    )
    assert record.status == "success"
    assert record.output_content is not None and "核心指标" in record.output_content
    assert record.model_used == "deepseek-chat"
    assert record.task_type == "daily_report"
    assert record.duration_ms is not None
    # 留痕已入库
    assert await db.get(AgentTaskRecord, record.id) is not None
    # 用量入库并关联触发用户与任务（docs/09 user_id/task_id 关联）
    from app.models.llm_log import LlmCallLog

    log = (await db.execute(select(LlmCallLog))).scalar_one()
    assert log.user_id == operator and log.task_id == record.id


async def test_run_agent_failure_is_recorded(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 抛异常 → 转 status=failed 留痕，不向上抛。"""
    monkeypatch.setattr(
        base, "get_llm_for_role", lambda *a, **k: _FakeLLM(exc=TimeoutError("boom"))
    )
    record = await ops.generate_daily_report(db, stat_date="2026-07-11", rows=_ROWS)
    assert record.status == "failed"
    assert record.output_content is None
    assert record.error_msg and "boom" in record.error_msg


async def test_empty_rows_rejected(db: AsyncSession) -> None:
    with pytest.raises(AppError, match="为空"):
        await ops.generate_daily_report(db, stat_date="2026-07-11", rows=[])


async def test_missing_role_rejected(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "OPS_DIRECTOR_CODE", "no_such_code")
    with pytest.raises(AppError, match="未配置"):
        await ops.generate_daily_report(db, stat_date="2026-07-11", rows=_ROWS)


async def test_generate_proposal(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        base, "get_llm_for_role",
        lambda *a, **k: _FakeLLM(text="【背景与问题】...【优先级建议】..."),
    )
    record = await ops.generate_proposal(db, topic="提升产品B次留", context="次留仅38%")
    assert record.status == "success" and record.task_type == "proposal"
    assert record.output_content and "背景" in record.output_content
