"""LLM 用量入库 + 日预算告警单测（内存 SQLite）。"""

import logging
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.llm.usage import extract_usage, record_usage
from app.models import Base
from app.models.llm_log import LlmCallLog


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_extract_usage_from_metadata() -> None:
    msg = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )
    assert extract_usage(msg) == (12, 8, 20)


def test_extract_usage_absent_returns_zero() -> None:
    assert extract_usage(AIMessage(content="x")) == (0, 0, 0)


def test_extract_usage_total_falls_back_to_sum() -> None:
    """total_tokens 为 0 时回退为 prompt+completion（防个别端点不回总数）。"""
    reply = SimpleNamespace(
        usage_metadata={"input_tokens": 3, "output_tokens": 4, "total_tokens": 0}
    )
    assert extract_usage(reply) == (3, 4, 7)


async def test_record_usage_inserts_row(db: AsyncSession) -> None:
    await record_usage(db, role="default", model="deepseek-chat", total_tokens=50)
    total = (await db.execute(select(func.count()).select_from(LlmCallLog))).scalar_one()
    assert total == 1


async def test_daily_budget_alert(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "llm_daily_token_budget", 10)
    with caplog.at_level(logging.WARNING):
        await record_usage(db, role="default", model="m", total_tokens=100)
    assert any("日用量告警" in r.message for r in caplog.records)


async def test_no_budget_no_alert(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "llm_daily_token_budget", 0)  # 不启用
    with caplog.at_level(logging.WARNING):
        await record_usage(db, role="default", model="m", total_tokens=10_000)
    assert not any("日用量告警" in r.message for r in caplog.records)
