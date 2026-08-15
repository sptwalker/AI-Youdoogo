"""SQLAlchemy 仓储：日程 / 专注 / 时间记录三 ORM ↔ 领域对象。三表唯一持久化 writer。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.time_management.domain.models import (
    FOCUS_ACTIVE,
    FocusSession,
    Schedule,
    TimeLog,
)
from app.models.time_management import FocusSession as FocusRow
from app.models.time_management import Schedule as ScheduleRow
from app.models.time_management import TimeLog as TimeLogRow


def _schedule_from_row(row: ScheduleRow) -> Schedule:
    return Schedule(
        id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        start_at=row.start_at,
        end_at=row.end_at,
        source=row.source,
        status=row.status,
        linked_task_id=row.linked_task_id,
        create_time=row.create_time,
    )


class SQLAlchemyScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, schedule: Schedule) -> None:
        self._session.add(
            ScheduleRow(
                id=schedule.id,
                owner_id=schedule.owner_id,
                title=schedule.title,
                start_at=schedule.start_at,
                end_at=schedule.end_at,
                source=schedule.source,
                status=schedule.status,
                linked_task_id=schedule.linked_task_id,
                create_time=schedule.create_time,
            )
        )
        await self._session.flush()

    async def get(self, schedule_id: uuid.UUID) -> Schedule | None:
        row = await self._session.get(ScheduleRow, schedule_id)
        if row is None or row.is_delete:
            return None
        return _schedule_from_row(row)

    async def save(self, schedule: Schedule) -> None:
        row = await self._session.get(ScheduleRow, schedule.id)
        if row is None or row.is_delete:
            return
        row.title = schedule.title
        row.start_at = schedule.start_at
        row.end_at = schedule.end_at
        row.status = schedule.status
        row.linked_task_id = schedule.linked_task_id
        await self._session.flush()

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Schedule, ...]:
        statement = select(ScheduleRow).where(
            ScheduleRow.is_delete.is_(False), ScheduleRow.owner_id == owner_id
        )
        if status:
            statement = statement.where(ScheduleRow.status == status)
        rows = (
            await self._session.execute(
                statement.order_by(ScheduleRow.start_at.asc()).limit(limit)
            )
        ).scalars()
        return tuple(_schedule_from_row(row) for row in rows)


def _focus_from_row(row: FocusRow) -> FocusSession:
    return FocusSession(
        id=row.id,
        owner_id=row.owner_id,
        start_at=row.start_at,
        planned_minutes=row.planned_minutes,
        status=row.status,
        intercept_notifications=row.intercept_notifications,
        ended_at=row.ended_at,
        create_time=row.create_time,
    )


class SQLAlchemyFocusSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, focus: FocusSession) -> None:
        self._session.add(
            FocusRow(
                id=focus.id,
                owner_id=focus.owner_id,
                start_at=focus.start_at,
                planned_minutes=focus.planned_minutes,
                status=focus.status,
                intercept_notifications=focus.intercept_notifications,
                ended_at=focus.ended_at,
                create_time=focus.create_time,
            )
        )
        await self._session.flush()

    async def get(self, focus_id: uuid.UUID) -> FocusSession | None:
        row = await self._session.get(FocusRow, focus_id)
        if row is None or row.is_delete:
            return None
        return _focus_from_row(row)

    async def save(self, focus: FocusSession) -> None:
        row = await self._session.get(FocusRow, focus.id)
        if row is None or row.is_delete:
            return
        row.status = focus.status
        row.ended_at = focus.ended_at
        await self._session.flush()

    async def active_for_owner(self, owner_id: uuid.UUID) -> FocusSession | None:
        statement = (
            select(FocusRow)
            .where(
                FocusRow.is_delete.is_(False),
                FocusRow.owner_id == owner_id,
                FocusRow.status == FOCUS_ACTIVE,
            )
            .order_by(FocusRow.start_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _focus_from_row(row) if row is not None else None


def _log_from_row(row: TimeLogRow) -> TimeLog:
    return TimeLog(
        id=row.id,
        owner_id=row.owner_id,
        category=row.category,
        minutes=row.minutes,
        logged_date=row.logged_date,
        ref_task_id=row.ref_task_id,
        create_time=row.create_time,
    )


class SQLAlchemyTimeLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: TimeLog) -> None:
        self._session.add(
            TimeLogRow(
                id=log.id,
                owner_id=log.owner_id,
                category=log.category,
                minutes=log.minutes,
                logged_date=log.logged_date,
                ref_task_id=log.ref_task_id,
                create_time=log.create_time,
            )
        )
        await self._session.flush()

    async def list_for_owner_between(
        self, *, owner_id: uuid.UUID, start: date, end: date
    ) -> tuple[TimeLog, ...]:
        statement = select(TimeLogRow).where(
            TimeLogRow.is_delete.is_(False),
            TimeLogRow.owner_id == owner_id,
            TimeLogRow.logged_date >= start,
            TimeLogRow.logged_date <= end,
        )
        rows = (await self._session.execute(statement)).scalars()
        return tuple(_log_from_row(row) for row in rows)
