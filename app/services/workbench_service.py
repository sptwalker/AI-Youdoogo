"""真人工作台聚合（F3）：把三个红线确认闸门的「待我处理」汇总到一个只读视图。

零新表、零状态机改动——只聚合既有待办：
  待验收任务 task_card.status==reported / 待评审提案 proposal_card.status==reviewed /
  待确认决议 meeting_resolution.is_confirmed==false。
动作（验收/评审/确认）仍走各自既有端点。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import MeetingResolution
from app.models.proposal import REVIEWED, ProposalCard
from app.models.task import TaskCard
from app.services.task_flow import REPORTED

_LIMIT = 50  # 待办量小，够用；# ponytail: 数据量上来再分页


async def get_pending(db: AsyncSession) -> dict[str, Any]:
    """当前所有「待真人确认」的三队列 + 计数。

    scope（MVP）：不按部门过滤，返回全量待办——proposal/meeting 确认端点本就 gate 到
    admin/executive，且 task/meeting 尚无 department_id。
    # ponytail: meeting/task 加 department_id(F3'/F4) 后按 supervisor 部门子树过滤
    """
    task_stmt = (
        select(TaskCard)
        .where(TaskCard.status == REPORTED, TaskCard.is_delete.is_(False))
        .order_by(TaskCard.create_time.desc())
        .limit(_LIMIT)
    )
    proposal_stmt = (
        select(ProposalCard)
        .where(ProposalCard.status == REVIEWED, ProposalCard.is_delete.is_(False))
        .order_by(ProposalCard.create_time.desc())
        .limit(_LIMIT)
    )
    resolution_stmt = (
        select(MeetingResolution)
        .where(
            MeetingResolution.is_confirmed.is_(False), MeetingResolution.is_delete.is_(False)
        )
        .order_by(MeetingResolution.create_time.desc())
        .limit(_LIMIT)
    )

    tasks = list((await db.execute(task_stmt)).scalars())
    proposals = list((await db.execute(proposal_stmt)).scalars())
    resolutions = list((await db.execute(resolution_stmt)).scalars())

    return {
        "counts": {
            "tasks": len(tasks),
            "proposals": len(proposals),
            "resolutions": len(resolutions),
        },
        "tasks": [
            {
                "id": str(t.id), "title": t.title, "task_type": t.task_type,
                "priority": t.priority, "create_time": t.create_time.isoformat(),
            }
            for t in tasks
        ],
        "proposals": [
            {
                "id": str(p.id), "code": p.code, "title": p.title, "priority": p.priority,
                "department_id": str(p.department_id) if p.department_id else None,
                "create_time": p.create_time.isoformat(),
            }
            for p in proposals
        ],
        "resolutions": [
            {
                "id": str(r.id), "meeting_id": str(r.meeting_id), "content": r.content,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "create_time": r.create_time.isoformat(),
            }
            for r in resolutions
        ],
    }
