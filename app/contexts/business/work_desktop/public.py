"""Published Work Desktop operations for delivery adapters."""

from app.contexts.business.work_desktop.application.contracts import (
    DeliverableDownloadResult,
    DesktopPrincipal,
)
from app.contexts.business.work_desktop.entrypoints.operations import (
    download_deliverable,
    get_desktop,
    get_supervised_desktop,
    list_deliverables,
)

__all__ = [
    "DeliverableDownloadResult",
    "DesktopPrincipal",
    "download_deliverable",
    "get_desktop",
    "get_supervised_desktop",
    "list_deliverables",
]
