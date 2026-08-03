"""Request-scoped composition for the Identity context."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.application.use_cases import IdentityApplication
from app.contexts.foundations.identity.infrastructure.adapters import (
    BcryptPasswordAdapter,
    FeishuOAuthAdapter,
)
from app.contexts.foundations.identity.infrastructure.sqlalchemy_uow import (
    SQLAlchemyIdentityUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_identity_application(session: AsyncSession) -> IdentityApplication:
    """Build an application boundary over the caller's existing session."""
    return IdentityApplication(
        uow_factory=lambda: SQLAlchemyIdentityUnitOfWork(session),
        passwords=BcryptPasswordAdapter(),
        feishu=FeishuOAuthAdapter(),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )
