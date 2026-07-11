"""Excel 解析管道测试：内存构造 xlsx，覆盖模板匹配/校验/标准化/去重。"""

from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.services.excel_ingest import (
    ColumnSpec,
    ExcelParseError,
    TemplateSpec,
    parse_workbook,
    registry,
)

HEADERS = ["日期", "产品", "日活", "新增", "次留"]


def _xlsx(rows: list[list], headers: list[str] = HEADERS) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_happy_path_types_normalized() -> None:
    content = _xlsx(
        [
            ["2026-07-10", "  产品A ", "1234", "56", "42.5"],
            ["2026/07/11", "产品Ｂ", 2000, None, None],  # 全角Ｂ、可选列为空
        ]
    )
    result = parse_workbook(content)
    assert result.template == "ops_daily/v1"
    assert result.ok_count == 2 and result.error_count == 0
    row0, row1 = result.rows
    assert row0 == {
        "stat_date": date(2026, 7, 10),
        "product": "产品A",
        "dau": 1234,
        "new_users": 56,
        "retention_d1": 42.5,
    }
    assert row1["product"] == "产品B"  # NFKC 全角→半角
    assert row1["stat_date"] == date(2026, 7, 11)
    assert row1["new_users"] is None


def test_row_errors_reported_with_row_no() -> None:
    content = _xlsx(
        [
            ["2026-07-10", "产品A", 100, None, None],  # 第2行 OK
            ["不是日期", "产品A", "abc", None, None],  # 第3行 两个错误
            [None, "产品C", 50, None, None],  # 第4行 必填日期为空
        ]
    )
    result = parse_workbook(content)
    assert result.ok_count == 1
    messages = [(e.row_no, e.field) for e in result.errors]
    assert (3, "stat_date") in messages and (3, "dau") in messages
    assert (4, "stat_date") in messages


def test_duplicate_rows_dropped_by_unique_key() -> None:
    content = _xlsx(
        [
            ["2026-07-10", "产品A", 100, None, None],
            ["2026-07-10", "产品A", 999, None, None],  # 同 (日期,产品) 重复
            ["2026-07-10", "产品B", 100, None, None],
        ]
    )
    result = parse_workbook(content)
    assert result.ok_count == 2
    assert result.duplicate_count == 1
    assert result.rows[0]["dau"] == 100  # 保留首条


def test_blank_rows_skipped() -> None:
    content = _xlsx(
        [
            ["2026-07-10", "产品A", 100, None, None],
            [None, None, None, None, None],
            ["", "", "", "", ""],
        ]
    )
    result = parse_workbook(content)
    assert result.ok_count == 1 and result.error_count == 0


def test_unknown_headers_rejected() -> None:
    content = _xlsx([["x"]], headers=["随便", "什么", "表头"])
    with pytest.raises(ExcelParseError, match="模板"):
        parse_workbook(content)


def test_corrupt_file_rejected() -> None:
    with pytest.raises(ExcelParseError, match="无法读取"):
        parse_workbook(b"this is not xlsx")


def test_explicit_template_missing_required_column() -> None:
    tpl = TemplateSpec(
        name="t",
        version="v1",
        columns=(ColumnSpec("金额", "amount", "float"),),
    )
    content = _xlsx([[1]], headers=["别的列"])
    with pytest.raises(ExcelParseError, match="金额"):
        parse_workbook(content, template=tpl)


def test_registry_match_prefers_more_specific() -> None:
    """文件表头是超集时匹配列数最多的模板。"""
    assert registry.match(HEADERS + ["额外备注列"]) is not None
    assert registry.match(["日期"]) is None  # 缺列不匹配
