"""Entrypoint 网关：拉起紧急会商——建会 + 解析品牌/销售/产品/法务负责人 + 定向飞书通知。

编排三个既有 Context（跨 Context 只走各自 entrypoints/public 门面，零直连 ORM/repository）：
  - organization_structure：`get_snapshot()` 按部门 code 匹配四部门 → `supervisor_user_id`
  - identity：`get_user_by_id()` 拿 `feishu_open_id` / `email`
  - meeting_management：`create_meeting`/`add_discussion` 建会 + 记录议题
  - feishu_notify_person：`send_to_recipient` 定向通知（复用 P0-1，零新增飞书 client 代码）

数据前置缺失（部门未配置/无负责人/负责人无飞书）→ 如实声明并安全跳过该收件人，不臆造、不静默失败。
定位到的负责人 user_id + email 一并回吐（供机械会商步装配 meeting 数据集，喂下游纪要/邮件步）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management import public as meetings
from app.contexts.foundations.identity import public as identity
from app.contexts.foundations.integration.feishu_notify_person import (
    public as feishu_notify_person,
)
from app.contexts.foundations.organization_structure import public as organization
from app.contexts.foundations.organization_structure.public import (
    DepartmentSnapshot,
    OrganizationTreeNodeSnapshot,
)

# 四部门目标名单——按组织骨架真实种子部门 code 匹配（见 organization_structure 的 _DEPARTMENTS）：
# 品牌宣传部/营销销售部/基础产品部/法务部；法务部（dept_legal）于 047 迁移随本能力补齐。
# code 稳定、与部门显示名解耦，比按名匹配更可靠（docs/26 §5）。
TARGET_DEPARTMENT_CODES = ("dept_brand", "dept_marketing", "dept_product_base", "dept_legal")


@dataclass(frozen=True, slots=True)
class ConsultationResult:
    """会商拉起结果：建会结果 + 每个目标部门的通知结论 + 定位到的与会负责人
    （供机械步装配数据集）。"""

    meeting_id: uuid.UUID
    notified: tuple[str, ...]  # 已成功定向通知的部门 code
    skipped: tuple[str, ...]  # 未能通知的部门 code + 原因说明
    participant_user_ids: tuple[uuid.UUID, ...]  # 定位到的部门负责人 user_id
    participant_emails: tuple[str, ...]  # 定位到的部门负责人工作邮箱（供下游邮件步）


def _find_department(
    snapshot_roots: tuple[OrganizationTreeNodeSnapshot, ...], code: str
) -> DepartmentSnapshot | None:
    """在组织树中按部门 code 深度优先查找部门快照。"""
    stack = list(snapshot_roots)
    while stack:
        node = stack.pop()
        if node.department.code == code:
            return node.department
        stack.extend(node.children)
    return None


async def convene(
    session: AsyncSession,
    *,
    topic: str,
    creator_id: uuid.UUID,
) -> ConsultationResult:
    """建紧急会商会议 + 记录议题 + 定向通知四部门负责人（缺失安全跳过）。"""
    meeting = await meetings.create_meeting(
        session,
        title=f"紧急会商：{topic}",
        creator_id=creator_id,
        meeting_type="consultation",
        initial_status="in_progress",
    )
    await meetings.add_discussion(
        session,
        meeting.id,
        speaker_id=creator_id,
        speaker_name="系统",
        content=f"紧急会商议题：{topic}",
    )

    snapshot = await organization.get_snapshot(session)
    notified: list[str] = []
    skipped: list[str] = []
    participant_user_ids: list[uuid.UUID] = []
    participant_emails: list[str] = []
    for code in TARGET_DEPARTMENT_CODES:
        department = _find_department(snapshot.roots, code)
        if department is None:
            skipped.append(f"{code}部门未配置")
            continue
        if department.supervisor_user_id is None:
            skipped.append(f"{code}部门负责人未配置")
            continue
        user = await identity.get_user_by_id(session, user_id=department.supervisor_user_id)
        if user is None:
            skipped.append(f"{code}部门负责人未配置")
            continue
        # 定位到负责人即计入与会人（供下游纪要/邮件步）；邮箱缺失只是不发邮件，不影响入会。
        participant_user_ids.append(user.id)
        if user.email:
            participant_emails.append(user.email)
        if not user.feishu_open_id:
            skipped.append(f"{code}部门负责人无飞书")
            continue
        sent = await feishu_notify_person.send_to_recipient(
            user.feishu_open_id, False, f"【紧急会商】{topic}，请及时关注会议 {meeting.id}"
        )
        (notified if sent else skipped).append(code if sent else f"{code}部门通知未生效")

    return ConsultationResult(
        meeting_id=meeting.id,
        notified=tuple(notified),
        skipped=tuple(skipped),
        participant_user_ids=tuple(participant_user_ids),
        participant_emails=tuple(participant_emails),
    )
