"""Published Work Desktop operations for delivery adapters."""

from app.contexts.business.work_desktop.application.contracts import (
    DeliverableDownloadResult,
    DesktopPrincipal,
    InboxItemRef,
)
from app.contexts.business.work_desktop.entrypoints.operations import (
    download_deliverable,
    get_desktop,
    get_supervised_desktop,
    list_deliverables,
    mark_inbox,
)

__all__ = [
    "DeliverableDownloadResult",
    "DesktopPrincipal",
    "InboxItemRef",
    "download_deliverable",
    "get_desktop",
    "get_supervised_desktop",
    "list_deliverables",
    "mark_inbox",
]
