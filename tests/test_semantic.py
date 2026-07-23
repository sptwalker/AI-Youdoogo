"""统一语义层单测（docs/15 §4.2）:查询扩展/提示词渲染纯函数 + CRUD（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.semantic_catalog import public as semantic_catalog
from app.contexts.foundations.knowledge.semantic_catalog.domain.models import (
    MAX_EXPAND_TERMS,
    expand_terms,
    render_term_prompt,
)
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.semantic_term import SemanticTerm


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _term(name: str, aliases: list[str], **kw: Any) -> SemanticTerm:
    return SemanticTerm(id=uuid.uuid4(), canonical_name=name, aliases=aliases, **kw)


# ── _expand 纯函数 ──────────────────────────────────────
def test_expand_hits_alias_adds_canonical() -> None:
    """查询含别名 → 追加规范名 + 其余别名。"""
    terms = [_term("累计激活设备数", ["新增设备", "激活量"])]
    extra = expand_terms("查一下激活量", terms)
    assert "累计激活设备数" in extra and "新增设备" in extra
    assert "激活量" not in extra  # 已在 query 里，不重复追加


def test_expand_no_hit_empty() -> None:
    terms = [_term("累计激活设备数", ["激活量"])]
    assert expand_terms("今天天气如何", terms) == ()


def test_expand_empty_query() -> None:
    assert expand_terms("  ", [_term("x", ["y"])]) == ()


def test_expand_dedups_and_caps() -> None:
    """多术语命中同词只追加一次，且不超过上限。"""
    terms = [_term(f"指标{i}", ["公共词"]) for i in range(20)]
    extra = expand_terms("包含公共词", terms)
    assert len(extra) <= MAX_EXPAND_TERMS
    assert len(extra) == len(set(extra))  # 去重


# ── _render 纯函数 ──────────────────────────────────────
def test_render_includes_fields() -> None:
    terms = [
        _term(
            "累计激活设备数",
            ["激活量"],
            term_type="metric",
            definition="new_device 去重",
            linked_view="v_event_4",
        )
    ]
    out = render_term_prompt(terms)
    assert "累计激活设备数" in out and "指标" in out
    assert "激活量" in out and "new_device 去重" in out and "v_event_4" in out


def test_render_empty() -> None:
    assert render_term_prompt([]) == ""


# ── expand_query / term_prompt（DB）─────────────────────
async def test_expand_query_appends(db: AsyncSession) -> None:
    db.add(_term("累计激活设备数", ["激活量"]))
    await db.commit()
    out = await semantic_catalog.expand_query(db, "看下激活量趋势")
    assert out.startswith("看下激活量趋势 ") and "累计激活设备数" in out


async def test_expand_query_no_hit_unchanged(db: AsyncSession) -> None:
    db.add(_term("累计激活设备数", ["激活量"]))
    await db.commit()
    assert await semantic_catalog.expand_query(db, "无关查询") == "无关查询"


async def test_term_prompt_renders(db: AsyncSession) -> None:
    db.add(_term("累计激活设备数", ["激活量"], definition="去重设备"))
    await db.commit()
    out = await semantic_catalog.term_prompt(db)
    assert "业务术语" in out and "累计激活设备数" in out


async def test_term_prompt_empty(db: AsyncSession) -> None:
    assert await semantic_catalog.term_prompt(db) == ""


# ── CRUD ────────────────────────────────────────────────
async def test_create_and_list(db: AsyncSession) -> None:
    snapshot = await semantic_catalog.create_term(
        db, {"canonical_name": "日活", "aliases": ["DAU", " "], "term_type": "metric"}
    )
    r = snapshot.to_dict()
    assert r["canonical_name"] == "日活" and r["aliases"] == ["DAU"]  # 空别名被过滤
    rows = [term.to_dict() for term in await semantic_catalog.list_terms(db)]
    assert len(rows) == 1


async def test_create_duplicate_rejected(db: AsyncSession) -> None:
    await semantic_catalog.create_term(db, {"canonical_name": "日活"})
    with pytest.raises(ApplicationError, match="已存在"):
        await semantic_catalog.create_term(db, {"canonical_name": "日活"})


async def test_create_requires_name(db: AsyncSession) -> None:
    with pytest.raises(ApplicationError, match="必填"):
        await semantic_catalog.create_term(db, {"canonical_name": "  "})


async def test_update_term(db: AsyncSession) -> None:
    created = await semantic_catalog.create_term(
        db,
        {"canonical_name": "日活", "aliases": ["DAU"]},
    )
    updated = await semantic_catalog.update_term(
        db,
        created.id,
        {"aliases": ["DAU", "活跃用户"], "definition": "当日去重用户"},
    )
    upd = updated.to_dict()
    assert set(upd["aliases"]) == {"DAU", "活跃用户"} and upd["definition"] == "当日去重用户"


async def test_update_name_clash_rejected(db: AsyncSession) -> None:
    await semantic_catalog.create_term(db, {"canonical_name": "日活"})
    second = await semantic_catalog.create_term(db, {"canonical_name": "月活"})
    with pytest.raises(ApplicationError, match="已存在"):
        await semantic_catalog.update_term(db, second.id, {"canonical_name": "日活"})


async def test_delete_term(db: AsyncSession) -> None:
    created = await semantic_catalog.create_term(db, {"canonical_name": "日活"})
    await semantic_catalog.delete_term(db, created.id)
    assert [term.to_dict() for term in await semantic_catalog.list_terms(db)] == []
    with pytest.raises(ApplicationError, match="不存在"):
        await semantic_catalog.delete_term(db, created.id)
