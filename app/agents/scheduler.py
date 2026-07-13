"""调度中枢（自研，替代 LangGraph）：驱动分配给智能体的任务卡自动执行。

run_task 把任务卡沿状态机推进 created→dispatched→executing→reported：
执行体调用其 assignee_agent 的 run_agent，产出写回任务卡 result_content。
验收（reported→accepted/rejected）仍由真人操作（docs/04 红线）。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.core.exceptions import AppError
from app.models.agent import AgentRole
from app.models.task import TaskCard
from app.services import task_flow, task_service


def _build_message(task: TaskCard) -> str:
    """把任务卡渲染成给智能体的输入消息。"""
    parts = [f"任务标题：{task.title}", f"任务类型：{task.task_type}"]
    if task.payload:
        parts.append("任务输入：\n" + json.dumps(task.payload, ensure_ascii=False, indent=2))
    parts.append("请完成该任务并给出结构化结果。")
    return "\n".join(parts)


async def run_task(
    db: AsyncSession, task_id: uuid.UUID, *, operator_id: uuid.UUID | None = None
) -> TaskCard:
    """驱动一个已分配智能体的任务卡执行到「已汇报」。

    Raises:
        AppError: 任务未分配智能体 / 智能体角色不存在 / 当前状态不可执行。
    """
    task = await task_service.get_task(db, task_id)
    if task.assignee_type == "user":
        # 派给真人的任务不进自动执行链，交由真人在工作台受理（docs/13 §7）
        raise AppError("该任务派给真人受理，不由调度中枢自动执行")
    if task.assignee_agent_id is None:
        raise AppError("任务未分配智能体，无法自动执行")
    role = await db.get(AgentRole, task.assignee_agent_id)
    if role is None or not role.is_active:
        raise AppError("指派的智能体角色不存在或已停用")

    # created → dispatched（若尚未分发）
    if task.status == task_flow.CREATED:
        task = await task_service.transition(
            db, task_id, task_flow.DISPATCHED, operator_id=operator_id, note="调度中枢分发"
        )
    if task.status != task_flow.DISPATCHED:
        raise AppError(f"任务当前状态 {task.status} 不可执行（需为 created/dispatched）")

    # dispatched → executing
    await task_service.transition(
        db, task_id, task_flow.EXECUTING, operator_id=operator_id, note="调度中枢开始执行"
    )
    record = await run_agent(
        db, role,
        task_type=task.task_type,
        input_summary=f"任务卡执行：{task.title[:40]}",
        user_message=_build_message(task),
        user_id=operator_id,
    )

    # executing → reported，产出写回
    result = record.output_content or record.error_msg or "（无产出）"
    return await task_service.transition(
        db, task_id, task_flow.REPORTED,
        operator_id=role.id,  # 执行者为智能体
        note=f"智能体执行 status={record.status}",
        result_content=result,
    )
