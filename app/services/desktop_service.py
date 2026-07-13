"""真人工作桌面聚合（F5a）：真人员工的统一工作枢纽（取代 workbench_service）。

按**目标真人用户身份**作用域（每人只见自己的待办，admin 全见=监督）：
  待我处理统一队列（验收/评审/确认/复核，同性质合并）+ 我的任务 + 对话/资料角标。
动作（验收/评审/确认/复核）仍走各自既有真人端点，本服务只聚合只读。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import MeetingResolution
from app.models.proposal import REVIEWED, ProposalCard
from app.models.system import SysUser
from app.models.task import TaskCard
from app.services import collab_service, discussion_service, permission_service
from app.services.task_flow import ACCEPTED, CANCELLED, REPORTED

_LIMIT = 50  # 各队列量小够用；# ponytail: 数据量上来再分页
_MANAGER_ROLES = ("admin", "executive")


async def get_desktop(db: AsyncSession, target: SysUser) -> dict[str, Any]:
    """目标真人用户的桌面聚合。作用域由 target 身份决定（admin 全见）。"""
    is_admin = target.role_code == "admin"
    is_manager = target.role_code in _MANAGER_ROLES

    pending: list[dict[str, Any]] = []

    # 待验收任务：reported 且（admin 全见 / 我创建或受理）
    task_where = [TaskCard.status == REPORTED, TaskCard.is_delete.is_(False)]
    if not is_admin:
        task_where.append(
            or_(TaskCard.creator_id == target.id, TaskCard.assignee_user_id == target.id)
        )
    task_stmt = select(TaskCard).where(*task_where).order_by(
        TaskCard.create_time.desc()
    ).limit(_LIMIT)
    for t in (await db.execute(task_stmt)).scalars():
        pending.append({
            "kind": "task", "id": str(t.id), "title": t.title,
            "meta": t.task_type, "priority": t.priority,
            "create_time": t.create_time.isoformat(),
        })

    # 待评审提案 / 待确认决议：管理动作，仅 admin/executive 纳入
    if is_manager:
        prop_stmt = select(ProposalCard).where(
            ProposalCard.status == REVIEWED, ProposalCard.is_delete.is_(False)
        ).order_by(ProposalCard.create_time.desc()).limit(_LIMIT)
        for p in (await db.execute(prop_stmt)).scalars():
            pending.append({
                "kind": "proposal", "id": str(p.id), "title": p.title,
                "meta": p.code, "priority": p.priority,
                "create_time": p.create_time.isoformat(),
            })
        res_stmt = select(MeetingResolution).where(
            MeetingResolution.is_confirmed.is_(False), MeetingResolution.is_delete.is_(False)
        ).order_by(MeetingResolution.create_time.desc()).limit(_LIMIT)
        for r in (await db.execute(res_stmt)).scalars():
            pending.append({
                "kind": "resolution", "id": str(r.id), "title": r.content[:60],
                "meta": r.due_date.isoformat() if r.due_date else None, "priority": "normal",
                "create_time": r.create_time.isoformat(),
            })

    # 待复核协作请求：目标部门主管=本人（admin 全见），复用 collab review_queue
    for c in await collab_service.review_queue(
        db, supervisor_user_id=target.id, is_admin=is_admin
    ):
        pending.append({
            "kind": "collab", "id": c["id"], "title": c["title"],
            "meta": c["risk_level"], "priority": "high" if c["risk_level"] == "high" else "normal",
            "create_time": c["create_time"],
        })

    pending.sort(key=lambda x: x["create_time"], reverse=True)

    # 我的任务（我创建或受理，非终态）
    my_stmt = select(TaskCard).where(
        or_(TaskCard.creator_id == target.id, TaskCard.assignee_user_id == target.id),
        TaskCard.status.not_in((ACCEPTED, CANCELLED)),
        TaskCard.is_delete.is_(False),
    ).order_by(TaskCard.create_time.desc()).limit(_LIMIT)
    my_tasks = [
        {
            "id": str(t.id), "title": t.title, "task_type": t.task_type,
            "status": t.status, "priority": t.priority,
            "create_time": t.create_time.isoformat(),
        }
        for t in (await db.execute(my_stmt)).scalars()
    ]

    # 对话/资料入口角标
    channels = await discussion_service.list_channels(db)
    kb_ids = await permission_service.visible_kb_ids(db, target)

    return {
        "user": {
            "id": str(target.id), "name": target.real_name or target.username,
            "role_code": target.role_code,
        },
        "pending": pending,
        "pending_count": len(pending),
        "my_tasks": my_tasks,
        "counts": {"channels": len(channels), "kbs": len(kb_ids)},
    }
