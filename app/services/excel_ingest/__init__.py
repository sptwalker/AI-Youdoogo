"""Excel 数据接入管道（模板识别/校验/标准化/去重）。"""

from app.services.excel_ingest.parser import (
    ExcelParseError,
    ParseResult,
    RowError,
    parse_workbook,
)
from app.services.excel_ingest.spec import ColumnSpec, TemplateSpec, registry

__all__ = [
    "ColumnSpec",
    "ExcelParseError",
    "ParseResult",
    "RowError",
    "TemplateSpec",
    "parse_workbook",
    "registry",
]
