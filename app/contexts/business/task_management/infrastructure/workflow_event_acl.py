"""ACL: 把运行时不透明事件 payload 解码回 Task Management 的产品字段。

运行时契约 ``WorkflowProgressedV1`` 只携通用字段 + ``business_key`` + 不透明 ``payload``
（见 [[ADR 0005]]）。产品字段名的唯一归属地在本 Context——本模块把 payload 解回
``WorkflowProjectionData``，投影 ``SQLAlchemyWorkflowTaskProjection`` 只读解码结果。
缺省宽容：payload 缺键回 None / 空 tuple / red_line=False，与旧事件默认值一致。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
)


@dataclass(frozen=True, slots=True)
class WorkflowProjectionData:
    """从运行时事件 payload 解码出的 Task Management 产品字段。"""

    parent_task_id: uuid.UUID
    creator_id: uuid.UUID
    title: str
    request_text: str
    task_card_id: uuid.UUID | None
    step_title: str | None
    capability_key: str | None
    instruction: str | None
    red_line: bool
    expert_id: uuid.UUID | None
    depends_on_task_ids: tuple[uuid.UUID, ...]
    result_content: str | None


def _opt_uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value is not None else None


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _uuid_tuple(value: object) -> tuple[uuid.UUID, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(uuid.UUID(str(item)) for item in value)


def decode_workflow_progress(event: WorkflowProgressedV1) -> WorkflowProjectionData:
    payload = event.payload
    return WorkflowProjectionData(
        parent_task_id=uuid.UUID(str(payload["parent_task_id"])),
        creator_id=uuid.UUID(str(payload["creator_id"])),
        title=str(payload["title"]),
        request_text=str(payload["request_text"]),
        task_card_id=_opt_uuid(payload.get("task_card_id")),
        step_title=_opt_str(payload.get("step_title")),
        capability_key=_opt_str(payload.get("capability_key")),
        instruction=_opt_str(payload.get("instruction")),
        red_line=bool(payload.get("red_line", False)),
        expert_id=_opt_uuid(payload.get("expert_id")),
        depends_on_task_ids=_uuid_tuple(payload.get("depends_on_task_ids")),
        result_content=_opt_str(payload.get("result_content")),
    )
