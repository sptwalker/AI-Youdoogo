"""SQLAlchemy ownership for evaluation cases and feedback evidence."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.ai_quality.application.ports import (
    EvaluationCaseRepositoryPort,
    FeedbackRepositoryPort,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    CreateEvaluationCaseCommand,
    EvaluationCaseView,
    FeedbackResult,
    LowScoreSample,
    RecordFeedbackCommand,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)
from app.contexts.shared_kernel import ResourceNotFound
from app.models.agent import AgentTaskRecord
from app.models.eval_case import EvalCase
from app.models.feedback import AgentFeedback


def _case_view(case: EvalCase) -> EvaluationCaseView:
    return EvaluationCaseView(
        case_id=case.id,
        name=case.name,
        role_id=case.role_id,
        input_text=case.input_text,
        rubric=case.rubric,
        is_active=case.is_active,
    )


class SQLAlchemyEvaluationCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_applicable(
        self, role_id: uuid.UUID
    ) -> tuple[EvaluationCaseView, ...]:
        statement = select(EvalCase).where(
            EvalCase.is_active.is_(True),
            EvalCase.is_delete.is_(False),
            or_(EvalCase.role_id == role_id, EvalCase.role_id.is_(None)),
        )
        return tuple(_case_view(row) for row in (await self._session.execute(statement)).scalars())

    async def list(self, role_id: uuid.UUID | None) -> tuple[EvaluationCaseView, ...]:
        statement = select(EvalCase).where(EvalCase.is_delete.is_(False))
        if role_id is not None:
            statement = statement.where(
                or_(EvalCase.role_id == role_id, EvalCase.role_id.is_(None))
            )
        statement = statement.order_by(EvalCase.create_time.desc())
        return tuple(_case_view(row) for row in (await self._session.execute(statement)).scalars())

    async def create(self, command: CreateEvaluationCaseCommand) -> EvaluationCaseView:
        case = EvalCase(
            name=command.name,
            role_id=command.role_id,
            input_text=command.input_text,
            rubric=command.rubric or "产出是否准确、切题、可用。",
        )
        self._session.add(case)
        await self._session.flush()
        return _case_view(case)

    async def delete(self, case_id: uuid.UUID) -> None:
        case = await self._session.get(EvalCase, case_id)
        if case is None or case.is_delete:
            raise ResourceNotFound("用例不存在")
        case.is_delete = True


class SQLAlchemyFeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execution_exists(self, task_record_id: uuid.UUID) -> bool:
        record = await self._session.get(AgentTaskRecord, task_record_id)
        return record is not None and not record.is_delete

    async def add(self, command: RecordFeedbackCommand) -> FeedbackResult:
        feedback = AgentFeedback(
            task_record_id=command.task_record_id,
            rater_id=command.rater_id,
            score=command.score,
            comment=command.comment,
        )
        self._session.add(feedback)
        await self._session.flush()
        return FeedbackResult(
            feedback_id=feedback.id,
            task_record_id=feedback.task_record_id,
            rater_id=feedback.rater_id,
            score=feedback.score,
            comment=feedback.comment,
        )

    async def mine(
        self, rater_id: uuid.UUID, task_record_ids: tuple[uuid.UUID, ...]
    ) -> tuple[FeedbackResult, ...]:
        if not task_record_ids:
            return ()
        statement = select(AgentFeedback).where(
            AgentFeedback.rater_id == rater_id,
            AgentFeedback.task_record_id.in_(task_record_ids),
        )
        return tuple(
            FeedbackResult(
                feedback_id=row.id,
                task_record_id=row.task_record_id,
                rater_id=row.rater_id,
                score=row.score,
                comment=row.comment,
            )
            for row in (await self._session.execute(statement)).scalars()
        )

    async def low_scored(
        self, role_id: uuid.UUID, threshold: int, limit: int
    ) -> tuple[LowScoreSample, ...]:
        statement = (
            select(
                AgentTaskRecord.output_content,
                AgentFeedback.score,
                AgentFeedback.comment,
            )
            .join(AgentFeedback, AgentFeedback.task_record_id == AgentTaskRecord.id)
            .where(
                AgentTaskRecord.agent_role_id == role_id,
                AgentFeedback.score <= threshold,
            )
            .order_by(AgentFeedback.create_time.desc())
            .limit(limit)
        )
        return tuple(
            LowScoreSample(output or "", score, comment)
            for output, score, comment in (await self._session.execute(statement)).all()
        )


class SQLAlchemyEvaluationSubject:
    def __init__(self, session: AsyncSession) -> None:
        self._experts = build_local_expert_directory_port(session)

    async def get(self, role_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return await self._experts.get_execution(role_id)


class SQLAlchemyAIQualityUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.cases: EvaluationCaseRepositoryPort = SQLAlchemyEvaluationCaseRepository(session)
        self.feedback: FeedbackRepositoryPort = SQLAlchemyFeedbackRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


async def get_feedback_record(
    session: AsyncSession, feedback_id: uuid.UUID
) -> AgentFeedback:
    record = await session.get(AgentFeedback, feedback_id)
    if record is None:
        raise RuntimeError("feedback record is unavailable")
    return record
