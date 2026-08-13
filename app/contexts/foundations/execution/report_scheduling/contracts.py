"""report_scheduling 契约：调度记录的传输无关只读视图。

快照成不可变 dataclass，避免 scan_once 在 start() 内部 commit 后触发 ORM expire-on-commit 懒加载。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleView:
    """一条调度记录的只读快照（脱离 Session，读字段不再触库）。"""

    id: uuid.UUID
    name: str
    title: str
    request_text: str
    creator_id: uuid.UUID | None
    assignee_agent_id: uuid.UUID | None
    template_id: uuid.UUID | None
    day_of_month: int
    hour: int
    enabled: bool
    last_fired_period: str | None
