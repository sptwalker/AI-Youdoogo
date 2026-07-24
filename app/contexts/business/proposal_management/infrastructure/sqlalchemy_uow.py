"""Proposal Unit of Work backed by a caller-owned AsyncSession."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyProposalRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyProposalUnitOfWork(SessionUnitOfWork):
    """Keep transaction decisions in Application while preserving request session lifetime."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._proposals = SQLAlchemyProposalRepository(session)

    @property
    def proposals(self) -> SQLAlchemyProposalRepository:
        return self._proposals

    def _prepare_for_use(self) -> None:
        self._proposals = SQLAlchemyProposalRepository(self._session)
