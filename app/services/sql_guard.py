"""只读 SQL 护栏（数据取数安全命门）:AI/外部客户端写的 SQL 强校验后才放行。

护栏五条(任一不过即拒，绝不放行可疑 SQL):
1. 可解析(sqlglot, Presto 方言——TD 基于 Presto/Trino);
2. 单语句(挡分号注入 / 多语句);
3. 仅 SELECT(挡 insert/update/delete/drop/create/call 等一切写与命令);
4. 只引用白名单视图(表名须在 allowed_views 内);
5. 强制 LIMIT(无则补、超上限则夹紧)。
校验通过返回规范化后的 SQL 字符串;不过抛 SqlRejected(带原因，供上层转结构化拒绝)。
用 sqlglot AST 判定而非正则:正则易被注释/大小写/嵌套绕过。
"""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

_DIALECT = "presto"  # TD 查询引擎基于 Presto/Trino
# TD 事件表强制 WHERE 带日期分区 "$part_date"，否则拒查（防全表扫描）。AI 常忘写，
# 尤其"累计/全量"统计——护栏自动补一个足够宽的下界兜底，覆盖全量又满足分区要求。
_PARTITION_COL = "$part_date"
_PARTITION_FLOOR = "2020-01-01"


class SqlRejected(Exception):
    """SQL 未通过护栏。reason 面向调用方(可回给 AI/客户端)。"""


def _tables(node: exp.Expression) -> list[str]:
    """AST 中引用的**外部**表名(小写)。排除 CTE 别名——那是查询内部引用，非外部表。"""
    cte_names = {c.alias.lower() for c in node.find_all(exp.CTE) if c.alias}
    return [
        t.name.lower()
        for t in node.find_all(exp.Table)
        if t.name and t.name.lower() not in cte_names
    ]


def _inject_partition(node: exp.Expression, allow: set[str]) -> None:
    """给引用了白名单事件视图但 WHERE 缺 "$part_date" 的 SELECT 就地补日期分区下界。

    分区是逐表扫描的要求，故按「表所属的 SELECT」注入:每个 FROM 命中事件视图、且自身
    WHERE 未含 "$part_date" 的 SELECT 各补一次。已带分区(单日/区间/下界)的原样不动。
    """
    seen: set[int] = set()
    for tbl in node.find_all(exp.Table):
        if not tbl.name or tbl.name.lower() not in allow:
            continue
        sel = tbl.find_ancestor(exp.Select)
        if sel is None or id(sel) in seen:
            continue
        seen.add(id(sel))
        where = sel.args.get("where")
        has_part = where is not None and any(
            c.name == _PARTITION_COL for c in where.find_all(exp.Column)
        )
        if not has_part:
            sel.where(
                f'"{_PARTITION_COL}" >= \'{_PARTITION_FLOOR}\'',
                append=True, dialect=_DIALECT, copy=False,
            )


def check_sql(sql: str, *, allowed_views: set[str], max_limit: int = 1000) -> str:
    """校验并规范化只读 SQL。allowed_views 传入时统一小写比较。

    Returns:
        规范化后的 SQL(必要时补/夹 LIMIT)。
    Raises:
        SqlRejected: 任一护栏不过。
    """
    sql = (sql or "").strip()
    if not sql:
        raise SqlRejected("SQL 为空")

    # 1+2. 解析 + 单语句
    try:
        statements = [s for s in parse(sql, read=_DIALECT) if s is not None]
    except SqlglotError as exc:
        raise SqlRejected(f"SQL 无法解析:{str(exc)[:120]}") from exc
    if len(statements) != 1:
        raise SqlRejected("只允许单条语句(检测到多语句或分号注入)")
    stmt = statements[0]

    # 3. 仅 SELECT:顶层必须是 Select(或包一层括号的 Select)。任何 DDL/DML/Command 一律拒。
    inner = stmt.unnest() if isinstance(stmt, exp.Subquery) else stmt
    if not isinstance(inner, (exp.Select, exp.Union)):
        raise SqlRejected("只允许 SELECT 查询(禁止写入/建表/删除/调用等操作)")
    # 纵深:AST 里出现任何写/命令节点直接拒(如 CTE 里藏 insert、或 Command 兜底)
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
                 exp.Alter, exp.Command, exp.Merge)
    if any(inner.find(f) for f in forbidden):
        raise SqlRejected("SQL 含被禁止的写/命令操作")

    # 4. 视图白名单
    allow = {v.lower() for v in allowed_views}
    used = _tables(inner)
    if not used:
        raise SqlRejected("SQL 未引用任何数据表")
    illegal = sorted(set(used) - allow)
    if illegal:
        raise SqlRejected(
            f"引用了未登记的表:{', '.join(illegal)}"
            f"(仅允许:{', '.join(sorted(allow))})"
        )

    # 4.5 自动补日期分区:事件表 WHERE 缺 "$part_date" 会被 TD 拒，护栏就地补全量下界兜底
    _inject_partition(inner, allow)

    # 5. 强制 LIMIT(仅对最外层 Select;Union 直接包一层再限)
    if isinstance(inner, exp.Union):
        inner = exp.select("*").from_(inner.subquery("_u"))
    limit = inner.args.get("limit")
    if limit is None:
        inner = inner.limit(max_limit)
    else:
        try:
            n = int(limit.expression.name)
            if n > max_limit:
                inner = inner.limit(max_limit)
        except (AttributeError, ValueError):
            inner = inner.limit(max_limit)  # LIMIT 值非常量(如 LIMIT ?)—夹到上限
    return inner.sql(dialect=_DIALECT)


def demo() -> None:
    """自检:放行 SELECT+补LIMIT;拒 DML/DDL/多语句/越权表。"""
    views = {"v_event_4", "v_event_5"}

    out = check_sql('select "$part_event" from v_event_4', allowed_views=views)
    assert "LIMIT 1000" in out.upper(), out

    out2 = check_sql("SELECT 1 AS n FROM v_event_4 LIMIT 999999", allowed_views=views)
    assert "LIMIT 1000" in out2.upper() and "999999" not in out2, out2

    # 自动补分区:缺 "$part_date" → 补下界；已带的不重复补
    inj = check_sql('select count(*) c from v_event_4', allowed_views=views)
    assert '"$part_date" >= \'2020-01-01\'' in inj, inj
    kept = check_sql(
        'select count(*) c from v_event_4 where "$part_date"=\'2026-07-16\'',
        allowed_views=views,
    )
    assert kept.count("$part_date") == 1, kept  # 已有分区不再叠加

    for bad, why in [
        ("DROP TABLE v_event_4", "drop"),
        ("INSERT INTO v_event_4 VALUES (1)", "insert"),
        ("UPDATE v_event_4 SET x=1", "update"),
        ("DELETE FROM v_event_4", "delete"),
        ("SELECT 1 FROM v_event_4; DROP TABLE v_event_4", "多语句"),
        ("SELECT * FROM secret_table", "越权表"),
        ("CALL some_proc()", "call"),
    ]:
        try:
            check_sql(bad, allowed_views=views)
            raise AssertionError(f"应拒未拒:{why} -> {bad}")
        except SqlRejected:
            pass
    print("sql_guard demo ok")


if __name__ == "__main__":
    demo()
