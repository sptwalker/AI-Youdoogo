"""SQLAlchemy transaction boundary for Task Management."""

from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyTaskTransaction(SessionUnitOfWork):
    """Keep the legacy task transaction name over the shared session lifecycle."""
