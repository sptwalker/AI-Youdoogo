"""ADR 0005 自证：运行时事件产品字段 opaque 化后，两端仍无损。

一：生产者从 ORM 建 opaque payload → task_management ACL 解码回产品字段，值一致。
二：outbox ``to_payload → from_payload`` 往返保 ``payload``/``business_key``/通用字段不失真。
生产者与 ACL 均纯映射，用轻量假 ORM 对象即可，无需真实 DB。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.contexts.business.task_management.infrastructure.workflow_event_acl import (
    decode_workflow_progress,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    workflow_progress_from_payload,
    workflow_progress_to_payload,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.progress_events import (
    _step_progress_event,
)


def _fake_run(parent_task_id: uuid.UUID, creator_id: uuid.UUID, expert_id: uuid.UUID):
    return SimpleNamespace(
        id=uuid.uuid4(),
        version=2,
        parent_task_id=parent_task_id,
        creator_id=creator_id,
        title="日报流程",
        request_text="生成日报",
        status="running",
        assignee_agent_id=expert_id,
        error_msg=None,
    )


def _fake_step(task_card_id: uuid.UUID, expert_id: uuid.UUID):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="succeeded",
        task_card_id=task_card_id,
        version=3,
        step_no=1,
        title="查询",
        skill="data_query",
        instruction="查询昨日数据",
        red_line=True,
        assignee_agent_id=expert_id,
    )


def test_producer_payload_decodes_back_to_product_fields() -> None:
    parent_id, creator_id, expert_id, card_id = (uuid.uuid4() for _ in range(4))
    run = _fake_run(parent_id, creator_id, expert_id)
    step = _fake_step(card_id, expert_id)

    event = _step_progress_event(
        run, step, "step.completed", datetime.now(UTC), result_content="done"
    )

    assert event.business_key == str(card_id)
    data = decode_workflow_progress(event)
    assert data.parent_task_id == parent_id
    assert data.creator_id == creator_id
    assert data.task_card_id == card_id
    assert data.expert_id == expert_id
    assert data.capability_key == "data_query"
    assert data.instruction == "查询昨日数据"
    assert data.red_line is True
    assert data.result_content == "done"


def test_outbox_roundtrip_preserves_payload_and_business_key() -> None:
    parent_id, creator_id, expert_id, card_id = (uuid.uuid4() for _ in range(4))
    run = _fake_run(parent_id, creator_id, expert_id)
    step = _fake_step(card_id, expert_id)
    event = _step_progress_event(run, step, "step.completed", datetime.now(UTC))

    restored = workflow_progress_from_payload(workflow_progress_to_payload(event))

    assert restored.event_id == event.event_id
    assert restored.workflow_id == event.workflow_id
    assert restored.business_key == event.business_key
    assert restored.step_status == event.step_status
    assert restored.step_version == event.step_version
    # payload 逐键还原（生产者写入的产品字段全部保真）
    assert dict(restored.payload) == dict(event.payload)
    assert decode_workflow_progress(restored) == decode_workflow_progress(event)
