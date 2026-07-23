"""Release read transactions before invoking an external model."""

from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyExternalExecutionBoundary:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def release_before_external_call(self) -> None:
        if self._session.in_transaction():
            await self._session.rollback()
