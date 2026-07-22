"""统一语义层服务（docs/15 §4.2）：术语字典 CRUD + 查询扩展 + 提示词注入。

三个能力:
- CRUD：admin 维护术语（规范名/别名/定义/类型/关联）。
- expand_query：把查询里命中的别名 → 规范名 + 同义词，扩展关键词臂输入（提精确召回）。
- term_prompt：把字典渲成【业务术语】段注入 agent，统一跨部门口径。
纯逻辑（_expand/_render）拆成可单测函数;DB 访问薄封装。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound, RuleViolation
from app.models.semantic_term import SemanticTerm

_MAX_PROMPT_TERMS = 60  # 注入提示词的术语上限（控 prompt 体积）
_MAX_EXPAND_TERMS = 8  # 单次查询最多注入的规范/同义词条数（防 query 膨胀）


async def _all_active(db: AsyncSession) -> list[SemanticTerm]:
    stmt = select(SemanticTerm).where(SemanticTerm.is_delete.is_(False)).order_by(
        SemanticTerm.term_type, SemanticTerm.canonical_name
    )
    return list((await db.execute(stmt)).scalars())


def _expand(query: str, terms: list[SemanticTerm]) -> list[str]:
    """纯函数:查询里出现某术语的规范名或任一别名 → 追加规范名+其余别名（去重、限量）。

    仅做子串命中（轻量，不分词）;命中即把该术语的规范名与别名并入扩展词，供关键词臂扩召回。
    返回追加词列表（不含原 query），保序去重，截到上限。
    """
    if not query.strip():
        return []
    extra: list[str] = []
    seen: set[str] = set()
    for t in terms:
        names = [t.canonical_name, *(t.aliases or [])]
        if not any(n and n in query for n in names):
            continue
        for n in names:
            if n and n not in query and n not in seen:
                seen.add(n)
                extra.append(n)
                if len(extra) >= _MAX_EXPAND_TERMS:
                    return extra
    return extra


async def expand_query(db: AsyncSession, query: str) -> str:
    """查询扩展:原 query 后拼上命中术语的规范名/同义词（空命中原样返回）。永不 raise。"""
    try:
        extra = _expand(query, await _all_active(db))
    except Exception:  # noqa: BLE001 - 语义扩展故障不连累检索
        return query
    return f"{query} {' '.join(extra)}" if extra else query


def _render(terms: list[SemanticTerm]) -> str:
    """纯函数:把术语列表渲成【业务术语】提示词段（空 → 空串）。"""
    if not terms:
        return ""
    lines = ["\n\n【业务术语】（公司统一口径，回答/取数时以此为准，别名视同规范名）:"]
    type_cn = {"metric": "指标", "dimension": "维度", "entity": "实体"}
    for t in terms[:_MAX_PROMPT_TERMS]:
        parts = [f"- {t.canonical_name}（{type_cn.get(t.term_type, t.term_type)}）"]
        if t.aliases:
            parts.append("别名:" + "、".join(t.aliases))
        if t.definition:
            parts.append(f"口径:{t.definition}")
        if t.linked_view:
            parts.append(f"数据源:{t.linked_view}")
        lines.append("；".join(parts))
    return "\n".join(lines)


async def term_prompt(db: AsyncSession) -> str:
    """渲染【业务术语】注入段。无术语返回空串。永不 raise（注入故障不阻断 AI）。"""
    try:
        return _render(await _all_active(db))
    except Exception:  # noqa: BLE001 - 提示词注入故障不阻断 AI
        return ""


# ── CRUD（admin 维护）───────────────────────────────────
async def list_terms(db: AsyncSession) -> list[dict[str, Any]]:
    return [t.as_dict() for t in await _all_active(db)]


async def _by_canonical(db: AsyncSession, name: str) -> SemanticTerm | None:
    stmt = select(SemanticTerm).where(
        SemanticTerm.canonical_name == name, SemanticTerm.is_delete.is_(False)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_term(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    """新建术语。规范名必填且唯一（重名 → 409）。"""
    name = (data.get("canonical_name") or "").strip()
    if not name:
        raise RuleViolation("规范名必填")
    if await _by_canonical(db, name) is not None:
        raise ConflictDetected("规范名已存在")
    term = SemanticTerm(
        canonical_name=name,
        aliases=[a.strip() for a in (data.get("aliases") or []) if a.strip()],
        term_type=data.get("term_type") or "metric",
        definition=data.get("definition") or None,
        linked_view=data.get("linked_view") or None,
        sql_template=data.get("sql_template") or None,
        kb_refs=[r.strip() for r in (data.get("kb_refs") or []) if r.strip()],
        department_id=data.get("department_id"),
    )
    db.add(term)
    await db.commit()
    await db.refresh(term)
    return term.as_dict()


async def update_term(db: AsyncSession, term_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    """改术语（仅传字段）。改规范名撞他人 → 409。"""
    term = await db.get(SemanticTerm, term_id)
    if term is None or term.is_delete:
        raise ResourceNotFound("术语不存在")
    if "canonical_name" in data:
        new_name = (data.get("canonical_name") or "").strip()
        if not new_name:
            raise RuleViolation("规范名不能为空")
        clash = await _by_canonical(db, new_name)
        if clash is not None and clash.id != term.id:
            raise ConflictDetected("规范名已存在")
        term.canonical_name = new_name
    if "aliases" in data:
        term.aliases = [a.strip() for a in (data.get("aliases") or []) if a.strip()]
    if "kb_refs" in data:
        term.kb_refs = [r.strip() for r in (data.get("kb_refs") or []) if r.strip()]
    for field in ("term_type", "definition", "linked_view", "sql_template", "department_id"):
        if field in data:
            setattr(term, field, data[field] or None)
    await db.commit()
    await db.refresh(term)
    return term.as_dict()


async def delete_term(db: AsyncSession, term_id: uuid.UUID) -> None:
    """软删术语。"""
    term = await db.get(SemanticTerm, term_id)
    if term is None or term.is_delete:
        raise ResourceNotFound("术语不存在")
    term.is_delete = True
    await db.commit()
