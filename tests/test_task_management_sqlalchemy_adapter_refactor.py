"""Compatibility checks for the split Task Management SQLAlchemy adapter."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.contracts.tasks import TaskDecisionRecordedV1
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskTransaction,
    task_decision_from_payload,
    task_decision_to_payload,
)
from app.contexts.business.task_management.infrastructure.task_decisions import (
    task_decision_from_payload as extracted_task_decision_from_payload,
)
from app.contexts.business.task_management.infrastructure.task_decisions import (
    task_decision_to_payload as extracted_task_decision_to_payload,
)
from app.contexts.business.task_management.infrastructure.transaction import (
    SQLAlchemyTaskTransaction as ExtractedSQLAlchemyTaskTransaction,
)


class RecordingSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_sqlalchemy_adapter_reexports_extracted_task_decision_codec() -> None:
    assert task_decision_to_payload is extracted_task_decision_to_payload
    assert task_decision_from_payload is extracted_task_decision_from_payload

    event = TaskDecisionRecordedV1(
        event_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        task_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        workflow_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        workflow_step_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        expected_step_version=7,
        decision="accepted",
        principal_id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        occurred_at=datetime(2026, 7, 24, 12, 30, tzinfo=UTC),
    )

    assert task_decision_from_payload(task_decision_to_payload(event)) == event


async def test_sqlalchemy_adapter_reexports_extracted_transaction() -> None:
    assert SQLAlchemyTaskTransaction is ExtractedSQLAlchemyTaskTransaction
    session = RecordingSession()
    transaction = SQLAlchemyTaskTransaction(cast(AsyncSession, session))

    await transaction.commit()
    await transaction.rollback()

    assert session.commits == 1
    assert session.rollbacks == 1
