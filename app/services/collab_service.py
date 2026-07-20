"""跨部门协作治理业务逻辑（docs/13 §2.2 · F4c，只做结构）。

风险分级 + 既定工作流授权 + 主管复核队列。红线：复核=分发闸门；生效永远真人验收。
自动编排链（AI产出请求→匹配授权/风险→自动分发→回流→事后复核）留未来业务工作流阶段。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.collab import (
    REQ_APPROVED,
    REQ_PENDING,
    REQ_REJECTED,
    RISK_HIGH,
    RISK_LOW,
    CollabAuthorization,
    CollabRequest,
)
from app.models.system import SysDepartment

# 红线类别恒高风险（资金/预算、人事、项目立项-调整、重大业务调整）
_HIGH_RISK_CATEGORIES = frozenset(
    {"finance", "budget", "hr", "project", "major_change"}
)


def classify_risk(category: str | None) -> str:
    """风险默认分类：红线类别恒高；分析/草拟/取数/报告/预研等只产草稿的默认低。"""
    return RISK_HIGH if category in _HIGH_RISK_CATEGORIES else RISK_LOW


# ---- 既定工作流授权 ----

async def authorize(
    db: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
    authorized_by: uuid.UUID | None,
) -> CollabAuthorization:
    """目标部门预授权源部门某类协作通道。"""
    a = CollabAuthorization(
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        collab_type=collab_type, authorized_by=authorized_by,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def revoke_authorization(db: AsyncSession, auth_id: uuid.UUID) -> None:
    a = await db.get(CollabAuthorization, auth_id)
    if a is None or a.is_delete:
        raise AppError("授权不存在", code=404, status_code=404)
    a.is_delete = True
    await db.commit()


async def list_authorizations(
    db: AsyncSession, *, target_department_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    stmt = select(CollabAuthorization).where(CollabAuthorization.is_delete.is_(False))
    if target_department_id is not None:
        stmt = stmt.where(CollabAuthorization.target_department_id == target_department_id)
    stmt = stmt.order_by(CollabAuthorization.create_time.desc())
    return [
        {
            "id": str(a.id), "source_department_id": str(a.source_department_id),
            "target_department_id": str(a.target_department_id),
            "collab_type": a.collab_type, "is_active": a.is_active,
        }
        for a in (await db.execute(stmt)).scalars()
    ]


async def has_authorization(
    db: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
) -> bool:
    """是否存在既定工作流授权（结构判定；自动分发链留未来）。"""
    stmt = select(CollabAuthorization.id).where(
        CollabAuthorization.source_department_id == source_department_id,
        CollabAuthorization.target_department_id == target_department_id,
        CollabAuthorization.collab_type == collab_type,
        CollabAuthorization.is_active.is_(True),
        CollabAuthorization.is_delete.is_(False),
    )
    return (await db.execute(stmt)).first() is not None


# ---- 主管复核队列 ----

def _req_dict(r: CollabRequest) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "source_department_id": str(r.source_department_id) if r.source_department_id else None,
        "target_department_id": str(r.target_department_id),
        "title": r.title, "summary": r.summary, "category": r.category,
        "risk_level": r.risk_level, "status": r.status,
        "requested_by": str(r.requested_by) if r.requested_by else None,
        "reviewed_by": str(r.reviewed_by) if r.reviewed_by else None,
        "review_note": r.review_note, "create_time": r.create_time.isoformat(),
    }


async def create_request(
    db: AsyncSession,
    *,
    target_department_id: uuid.UUID,
    title: str,
    source_department_id: uuid.UUID | None = None,
    summary: str | None = None,
    category: str | None = None,
    risk_level: str | None = None,
    requested_by: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> CollabRequest:
    """发起跨部门协作请求入复核队列（risk_level 省略时按 category 自动分级）。"""
    if idempotency_key:
        existing = (
            await db.execute(
                select(CollabRequest).where(
                    CollabRequest.idempotency_key == idempotency_key,
                    CollabRequest.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    r = CollabRequest(
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        title=title, summary=summary, category=category,
        risk_level=risk_level or classify_risk(category),
        requested_by=requested_by,
        idempotency_key=idempotency_key,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


async def review_queue(
    db: AsyncSession, *, supervisor_user_id: uuid.UUID, is_admin: bool = False
) -> list[dict[str, Any]]:
    """某真人主管的待复核队列：目标部门主管=本人的 pending 请求；admin 见全部 pending。"""
    stmt = select(CollabRequest).where(CollabRequest.status == REQ_PENDING)
    if not is_admin:
        stmt = stmt.join(
            SysDepartment, SysDepartment.id == CollabRequest.target_department_id
        ).where(SysDepartment.supervisor_user_id == supervisor_user_id)
    stmt = stmt.order_by(CollabRequest.create_time)
    return [_req_dict(r) for r in (await db.execute(stmt)).scalars()]


async def review_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    decision: str,
    reviewer_id: uuid.UUID,
    note: str | None = None,
) -> CollabRequest:
    """主管复核：approve/reject（红线：只是分发闸门，产出生效仍走真人验收）。"""
    if decision not in ("approve", "reject"):
        raise AppError("decision 仅支持 approve/reject")
    r = await db.get(CollabRequest, request_id)
    if r is None or r.is_delete:
        raise AppError("协作请求不存在", code=404, status_code=404)
    if r.status != REQ_PENDING:
        raise AppError(f"请求当前状态 {r.status}，不可复核")
    r.status = REQ_APPROVED if decision == "approve" else REQ_REJECTED
    r.reviewed_by = reviewer_id
    r.review_note = note
    await db.commit()
    await db.refresh(r)
    return r
