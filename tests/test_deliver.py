"""文件交付技能单测（docs/13 §11，内存 SQLite + 打桩 MinIO，不发真实请求）。"""

import io
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.execution.deliverable_management.application import (
    formatting,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints import (
    agent_capability,
)
from app.models import Base
from app.models.agent import AgentRole
from app.models.deliverable import Deliverable
from app.platform.object_storage import gateway as object_storage
from app.services import deliver_service


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
    return AgentRole(id=uuid.uuid4(), name="销售助理", prompt_template="x", tools=[])


_TABLE = "【交付】名称：销售周报；格式：xlsx\n```\n| 日期 | 产品 | 销量 |\n| --- | --- | --- |\n| 2026-07-14 | A | 120 |\n```"  # noqa: E501


# ── parse 纯函数 ────────────────────────────────────────
def test_parse_extracts_name_fmt_body() -> None:
    items = deliver_service.parse(f"好的，这是报表：\n{_TABLE}")
    assert len(items) == 1
    name, fmt, body = items[0]
    assert name == "销售周报" and fmt == "xlsx" and "120" in body


def test_legacy_facade_exports_canonical_delivery_components() -> None:
    assert deliver_service.parse is agent_capability.parse
    assert deliver_service.DeliverySkillExecutor is agent_capability.DeliverySkillExecutor
    assert deliver_service._build_bytes is formatting.build_bytes
    assert deliver_service._markdown_table_to_rows is formatting.markdown_table_to_rows
    assert deliver_service._safe_name is formatting.safe_file_name
    assert deliver_service.storage is object_storage


def test_parse_truncates_to_two() -> None:
    one = "【交付】名称：N；格式：txt\n```\n正文\n```"
    assert len(deliver_service.parse("\n".join([one] * 5))) == 2


def test_parse_ignores_invalid_format() -> None:
    bad = "【交付】名称：X；格式：pdf\n```\n内容\n```"
    assert deliver_service.parse(bad) == []


# ── markdown 表 → 行 ────────────────────────────────────
def test_markdown_table_drops_separator_row() -> None:
    rows = deliver_service._markdown_table_to_rows(
        "| 日期 | 销量 |\n| --- | ---: |\n| 7-14 | 120 |"
    )
    assert rows == [["日期", "销量"], ["7-14", "120"]]


# ── 字节生成 ────────────────────────────────────────────
def test_build_csv_readable() -> None:
    data = deliver_service._build_bytes("csv", "| A | B |\n| - | - |\n| 1 | 2 |")
    text = data.decode("utf-8-sig")
    assert "A,B" in text and "1,2" in text


def test_build_xlsx_reloadable() -> None:
    data = deliver_service._build_bytes("xlsx", "| A | B |\n| - | - |\n| 1 | 2 |")
    wb = load_workbook(io.BytesIO(data))
    assert [c.value for c in wb.active[1]] == ["A", "B"]


def test_build_doc_raw() -> None:
    assert deliver_service._build_bytes("md", "# 标题\n正文") == "# 标题\n正文".encode()


def test_build_table_empty_raises() -> None:
    with pytest.raises(ValueError, match="表格"):
        deliver_service._build_bytes("csv", "没有表格只有文字")


# ── execute 编排 ────────────────────────────────────────
async def test_execute_no_directive_fast_path(db: AsyncSession) -> None:
    r = await deliver_service.execute(db, _role(), "普通回复无交付", user_id=uuid.uuid4())
    assert r.notes == []


async def test_execute_requires_recipient(db: AsyncSession) -> None:
    """user_id 为空（自动任务）→ 跳过并出 note，不落库。"""
    r = await deliver_service.execute(db, _role(), _TABLE, user_id=None)
    assert any("接收人" in n for n in r.notes)
    assert (await db.execute(select(Deliverable))).first() is None


async def test_execute_happy_path(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """交付成功：存储被调用、落一行 Deliverable、出「已交付」note。"""
    saved: dict[str, Any] = {}

    async def _fake_put(object_name: str, data: bytes, content_type: str) -> str:
        saved["name"] = object_name
        saved["size"] = len(data)
        return f"bucket/{object_name}"

    monkeypatch.setattr(deliver_service.storage, "put_object", _fake_put)
    uid = uuid.uuid4()
    r = await deliver_service.execute(db, _role(), _TABLE, user_id=uid)

    assert any("已交付" in n for n in r.notes)
    assert saved["size"] > 0
    row = (await db.execute(select(Deliverable))).scalar_one()
    assert row.owner_user_id == uid and row.file_name == "销售周报.xlsx"
    assert row.file_format == "xlsx" and row.storage_path.startswith("bucket/")
    # 结构化载荷:交付引用进 artifacts（阶段A 产出管道）
    assert len(r.artifacts) == 1
    assert r.artifacts[0]["file_name"] == "销售周报.xlsx"
    assert r.artifacts[0]["deliverable_id"] == str(row.id)


async def test_storage_failure_does_not_publish_visible_deliverable(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_put(_object_name: str, _data: bytes, _content_type: str) -> str:
        raise RuntimeError("object storage unavailable")

    monkeypatch.setattr(deliver_service.storage, "put_object", _fail_put)
    result = await deliver_service.execute(db, _role(), _TABLE, user_id=uuid.uuid4())

    assert any("交付「销售周报」失败" in note for note in result.notes)
    assert (await db.execute(select(Deliverable))).first() is None


async def test_list_deliverables_scoped_and_ordered(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list 仅返回该 owner 的、倒序。"""

    async def _put(object_name: str, data: bytes, content_type: str) -> str:
        return f"bucket/{object_name}"

    monkeypatch.setattr(deliver_service.storage, "put_object", _put)
    mine, other = uuid.uuid4(), uuid.uuid4()
    await deliver_service.execute(db, _role(), _TABLE, user_id=mine)
    await deliver_service.execute(db, _role(), _TABLE, user_id=other)
    rows = await deliver_service.list_deliverables(db, mine)
    assert len(rows) == 1 and rows[0]["file_name"] == "销售周报.xlsx"
