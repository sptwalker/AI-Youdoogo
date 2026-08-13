"""Meeting Management 跨 Context 只读/写门面：其它 Context 只经此调建会/记议题。

# ponytail: 只暴露 convene_consultation 编排真正需要的 create_meeting/add_discussion 两个入口，
#   薄转发 entrypoints.operations（不复制逻辑）。需要更多再按需加，不预建整套 CRUD facade。
"""

from __future__ import annotations

from app.contexts.business.meeting_management.entrypoints.operations import (
    add_discussion,
    create_meeting,
)

__all__ = ["add_discussion", "create_meeting"]
