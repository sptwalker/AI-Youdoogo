"""只读 SQL 护栏单测(纯函数，sqlglot 真解析，无需 DB)。"""

import pytest

from app.services.sql_guard import SqlRejected, check_sql

_VIEWS = {"v_event_4", "v_event_5"}


def _ok(sql: str) -> str:
    return check_sql(sql, allowed_views=_VIEWS, max_limit=1000)


def _rejected(sql: str) -> str:
    with pytest.raises(SqlRejected) as ei:
        check_sql(sql, allowed_views=_VIEWS, max_limit=1000)
    return str(ei.value)


# ── 放行 + LIMIT 规范化 ─────────────────────────────────
def test_select_passes_and_injects_limit() -> None:
    out = _ok('select "$part_event" from v_event_4')
    assert "LIMIT 1000" in out.upper()


def test_limit_clamped_when_too_large() -> None:
    out = _ok("SELECT 1 AS n FROM v_event_4 LIMIT 999999")
    assert "LIMIT 1000" in out.upper() and "999999" not in out


def test_small_limit_kept() -> None:
    out = _ok("SELECT 1 FROM v_event_4 LIMIT 10")
    assert "LIMIT 10" in out.upper() and "1000" not in out


def test_real_td_metric_query_passes() -> None:
    sql = ('select "$part_event" ev, count(distinct "#user_id") dau '
           "from v_event_4 where \"$part_date\"='2026-07-15' group by 1")
    out = _ok(sql)
    assert "v_event_4" in out and "LIMIT" in out.upper()


def test_cte_passes() -> None:
    out = _ok("with a as (select 1 n from v_event_4) select * from a")
    assert "LIMIT 1000" in out.upper()


# ── 自动补日期分区（TD 事件表强制 $part_date）─────────────
def test_partition_injected_when_missing() -> None:
    out = _ok('select count(distinct "#user_id") t from v_event_4')
    assert "\"$part_date\" >= '2020-01-01'" in out


def test_partition_not_duplicated_when_present() -> None:
    out = _ok("select count(*) c from v_event_4 where \"$part_date\"='2026-07-16'")
    assert out.count("$part_date") == 1  # 已带分区不叠加


def test_partition_kept_for_range_filter() -> None:
    out = _ok(
        "select count(*) c from v_event_4 "
        "where \"$part_date\" between '2026-07-01' and '2026-07-16'"
    )
    assert out.count("$part_date") == 1 and "2020-01-01" not in out


def test_partition_injected_with_existing_event_filter() -> None:
    """AI 那条累计设备数:只有 $part_event、缺 $part_date → 补下界，两个条件并存。"""
    out = _ok(
        'select count(distinct "#user_id") total_devices from v_event_4 '
        "where \"$part_event\"='new_device'"
    )
    assert "\"$part_event\" = 'new_device'" in out
    assert "\"$part_date\" >= '2020-01-01'" in out


# ── 拒绝:写/命令 ────────────────────────────────────────
@pytest.mark.parametrize("sql", [
    "DROP TABLE v_event_4",
    "INSERT INTO v_event_4 VALUES (1)",
    "UPDATE v_event_4 SET x=1",
    "DELETE FROM v_event_4",
    "CREATE TABLE t (a int)",
    "ALTER TABLE v_event_4 ADD COLUMN c int",
    "CALL some_proc()",
])
def test_non_select_rejected(sql: str) -> None:
    assert _rejected(sql)


# ── 拒绝:注入 / 越权 / 空 ───────────────────────────────
def test_multi_statement_rejected() -> None:
    assert "多语句" in _rejected("SELECT 1 FROM v_event_4; DROP TABLE v_event_4") or \
        _rejected("SELECT 1 FROM v_event_4; DROP TABLE v_event_4")


def test_unlisted_table_rejected() -> None:
    r = _rejected("SELECT * FROM secret_table")
    assert "未登记" in r or "secret_table" in r


def test_union_to_unlisted_rejected() -> None:
    assert _rejected("select 1 from v_event_4 union select 1 from evil")


def test_subquery_to_unlisted_rejected() -> None:
    assert _rejected("select 1 from v_event_4 where x in (select y from evil)")


def test_cte_body_unlisted_rejected() -> None:
    assert _rejected("with a as (select 1 from evil) select * from a")


def test_empty_rejected() -> None:
    assert _rejected("   ")


def test_no_table_rejected() -> None:
    assert _rejected("SELECT 1")
