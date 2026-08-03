"""Validate and normalize read-only business-data SQL queries.

The policy rejects unparseable or multi-statement SQL, allows only SELECT, restricts
external tables to a caller-provided catalog, injects the ThinkingData partition floor,
and clamps the outer LIMIT. It has no database or network dependency.
"""

from __future__ import annotations

from typing import cast

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

_DIALECT = "presto"
_PARTITION_COL = "$part_date"
_PARTITION_FLOOR = "2020-01-01"


class SqlRejected(Exception):
    """Raised when a query violates the governed read-only policy."""


def _external_tables(node: exp.Expression) -> list[exp.Table]:
    """Return physical tables while excluding CTE aliases."""
    cte_names = {cte.alias.lower() for cte in node.find_all(exp.CTE) if cte.alias}
    return [
        table
        for table in node.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    ]


def _partition_floor(table: exp.Table) -> exp.GTE:
    """Build a qualified partition condition for an allowed table reference."""
    return exp.GTE(
        this=exp.Column(
            this=exp.Identifier(this=_PARTITION_COL, quoted=True),
            table=exp.Identifier(this=table.alias_or_name, quoted=True),
        ),
        expression=exp.Literal.string(_PARTITION_FLOOR),
    )


def _inject_partition(node: exp.Expression, tables: list[exp.Table]) -> None:
    """Require the partition floor for every governed table in its SELECT scope."""
    for table in tables:
        select_node = table.find_ancestor(exp.Select)
        if select_node is None:
            continue
        select_node.where(_partition_floor(table), append=True, copy=False)


def _parse_one(sql: str) -> exp.Expression:
    normalized = (sql or "").strip()
    if not normalized:
        raise SqlRejected("SQL 为空")
    try:
        statements = [statement for statement in parse(normalized, read=_DIALECT) if statement]
    except SqlglotError as exc:
        raise SqlRejected(f"SQL 无法解析:{str(exc)[:120]}") from exc
    if len(statements) != 1:
        raise SqlRejected("只允许单条语句(检测到多语句或分号注入)")
    return cast(exp.Expression, statements[0])


def _read_query(statement: exp.Expression) -> exp.Select | exp.Union:
    inner = statement.unnest() if isinstance(statement, exp.Subquery) else statement
    if not isinstance(inner, (exp.Select, exp.Union)):
        raise SqlRejected("只允许 SELECT 查询(禁止写入/建表/删除/调用等操作)")
    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
        exp.Merge,
    )
    if any(inner.find(node_type) for node_type in forbidden):
        raise SqlRejected("SQL 含被禁止的写/命令操作")
    return inner


def _allowed_tables(inner: exp.Expression, allowed_views: set[str]) -> list[exp.Table]:
    allowed = {view.lower() for view in allowed_views}
    tables = _external_tables(inner)
    if not tables:
        raise SqlRejected("SQL 未引用任何数据表")
    qualified = sorted(
        table.sql(dialect=_DIALECT) for table in tables if table.db or table.catalog
    )
    if qualified:
        raise SqlRejected(f"禁止使用带 schema/catalog 的限定表:{', '.join(qualified)}")
    used = [table.name.lower() for table in tables if table.name]
    illegal = sorted(set(used) - allowed)
    if illegal:
        raise SqlRejected(
            f"引用了未登记的表:{', '.join(illegal)}(仅允许:{', '.join(sorted(allowed))})"
        )
    return tables


def _bounded_select(inner: exp.Select | exp.Union, max_limit: int) -> exp.Select:
    if isinstance(inner, exp.Union):
        inner = exp.select("*").from_(inner.subquery("_u"))
    limit = inner.args.get("limit")
    if limit is None:
        inner = inner.limit(max_limit)
    else:
        try:
            if int(limit.expression.name) > max_limit:
                inner = inner.limit(max_limit)
        except (AttributeError, ValueError):
            inner = inner.limit(max_limit)
    return inner


def check_sql(sql: str, *, allowed_views: set[str], max_limit: int = 1000) -> str:
    """Validate a read-only query and return normalized, bounded SQL."""
    inner = _read_query(_parse_one(sql))
    tables = _allowed_tables(inner, allowed_views)
    _inject_partition(inner, tables)
    inner = _bounded_select(inner, max_limit)
    return inner.sql(dialect=_DIALECT)
