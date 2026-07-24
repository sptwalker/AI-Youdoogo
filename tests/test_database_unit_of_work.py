"""Shared SQLAlchemy Unit of Work transaction behavior."""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.application.errors import IdentityWriteConflict
from app.contexts.foundations.identity.infrastructure.sqlalchemy_uow import (
    SQLAlchemyIdentityUnitOfWork,
)
from app.contexts.foundations.organization_structure.application.errors import (
    OrganizationWriteConflict,
)
from app.contexts.foundations.organization_structure.infrastructure.sqlalchemy_uow import (
    SQLAlchemyOrganizationUnitOfWork,
)
from app.contexts.foundations.workforce.expert_management.application.errors import (
    ExpertWriteConflict,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyExpertUnitOfWork,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class _HealthySessionSpy:
    def __init__(self) -> None:
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        self.flushes += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionSpy:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def commit(self) -> None:
        raise IntegrityError("commit", {}, RuntimeError("duplicate"))

    async def flush(self) -> None:
        raise IntegrityError("flush", {}, RuntimeError("duplicate"))

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_session_unit_of_work_owns_only_transaction_lifecycle() -> None:
    session = _HealthySessionSpy()
    uow = SessionUnitOfWork(cast(AsyncSession, session))

    async with uow as entered:
        assert entered is uow
        await entered.flush()
        await entered.commit()

    assert session.flushes == 1
    assert session.commits == 1
    assert session.rollbacks == 0

    with pytest.raises(RuntimeError, match="application failure"):
        async with uow:
            raise RuntimeError("application failure")

    assert session.rollbacks == 1


@pytest.mark.parametrize("operation", ["commit", "flush"])
@pytest.mark.parametrize(
    ("uow_type", "error_type"),
    [
        (SQLAlchemyIdentityUnitOfWork, IdentityWriteConflict),
        (SQLAlchemyOrganizationUnitOfWork, OrganizationWriteConflict),
        (SQLAlchemyExpertUnitOfWork, ExpertWriteConflict),
    ],
)
async def test_integrity_failures_rollback_and_keep_context_error(
    operation: str,
    uow_type: type[Any],
    error_type: type[Exception],
) -> None:
    session = _SessionSpy()
    uow = uow_type(cast(AsyncSession, session))

    with pytest.raises(error_type) as captured:
        await getattr(uow, operation)()

    assert isinstance(captured.value.__cause__, IntegrityError)
    assert session.rollbacks == 1


async def test_exceptional_context_exit_rolls_back() -> None:
    session = _SessionSpy()
    uow = SQLAlchemyIdentityUnitOfWork(cast(AsyncSession, session))

    with pytest.raises(RuntimeError, match="application failure"):
        async with uow:
            raise RuntimeError("application failure")

    assert session.rollbacks == 1
