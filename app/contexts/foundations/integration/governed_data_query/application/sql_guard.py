"""Validate and normalize read-only business-data SQL queries.

The policy rejects unparseable or multi-statement SQL, allows only SELECT, restricts
external tables to a caller-provided catalog, injects the ThinkingData partition floor,
and clamps the outer LIMIT. It has no database or network dependency.
"""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

_DIALECT = "presto"
_PARTITION_COL = "$part_date"
_PARTITION_FLOOR = "2020-01-01"


class SqlRejected(Exception):
    """Raised when a query violates the governed read-only policy."""


def _tables(node: exp.Expression) -> list[str]:
    """Return external table names while excluding CTE aliases."""
    cte_names = {cte.alias.lower() for cte in node.find_all(exp.CTE) if cte.alias}
    return [
        table.name.lower()
        for table in node.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    ]


def _inject_partition(node: exp.Expression, allowed_views: set[str]) -> None:
    """Add a safe partition floor to each allowed event-table SELECT when absent."""
    seen: set[int] = set()
    for table in node.find_all(exp.Table):
        if not table.name or table.name.lower() not in allowed_views:
            continue
        select_node = table.find_ancestor(exp.Select)
        if select_node is None or id(select_node) in seen:
            continue
        seen.add(id(select_node))
        where = select_node.args.get("where")
        has_partition = where is not None and any(
            column.name == _PARTITION_COL for column in where.find_all(exp.Column)
        )
        if not has_partition:
            select_node.where(
                f"\"{_PARTITION_COL}\" >= '{_PARTITION_FLOOR}'",
                append=True,
                dialect=_DIALECT,
                copy=False,
            )


def check_sql(sql: str, *, allowed_views: set[str], max_limit: int = 1000) -> str:
    """Validate a read-only query and return normalized, bounded SQL."""
    sql = (sql or "").strip()
    if not sql:
        raise SqlRejected("SQL 为空")

    try:
        statements = [statement for statement in parse(sql, read=_DIALECT) if statement]
    except SqlglotError as exc:
        raise SqlRejected(f"SQL 无法解析:{str(exc)[:120]}") from exc
    if len(statements) != 1:
        raise SqlRejected("只允许单条语句(检测到多语句或分号注入)")
    statement = statements[0]

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

    allowed = {view.lower() for view in allowed_views}
    used = _tables(inner)
    if not used:
        raise SqlRejected("SQL 未引用任何数据表")
    illegal = sorted(set(used) - allowed)
    if illegal:
        raise SqlRejected(
            f"引用了未登记的表:{', '.join(illegal)}(仅允许:{', '.join(sorted(allowed))})"
        )

    _inject_partition(inner, allowed)

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
    return inner.sql(dialect=_DIALECT)
