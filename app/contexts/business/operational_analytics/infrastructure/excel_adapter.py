"""Adapter for the existing versioned workbook parser."""

from app.contexts.business.operational_analytics.application.contracts import (
    ParsedMetricRow,
    ParsedWorkbook,
)
from app.contexts.business.operational_analytics.contracts import (
    IngestError,
    WorkbookParseFailure,
)
from app.services.excel_ingest import ExcelParseError, parse_workbook


class ExcelWorkbookParser:
    def parse(self, content: bytes) -> ParsedWorkbook:
        try:
            parsed = parse_workbook(content)
        except ExcelParseError as exc:
            raise WorkbookParseFailure(str(exc)) from exc
        return ParsedWorkbook(
            template=parsed.template,
            rows=tuple(
                ParsedMetricRow(
                    stat_date=row["stat_date"],
                    product=row["product"],
                    dau=row.get("dau"),
                    new_users=row.get("new_users"),
                    retention_d1=row.get("retention_d1"),
                )
                for row in parsed.rows
            ),
            errors=tuple(
                IngestError(
                    row_no=error.row_no,
                    field=error.field,
                    message=error.message,
                )
                for error in parsed.errors
            ),
            duplicate_count=parsed.duplicate_count,
        )
