"""Request-scoped composition for the local Knowledge Retrieval adapter."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.application.use_cases import (
    KnowledgeRetrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_gateway,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.local_adapter import (
    LocalKnowledgeRetrievalAdapter,
)


def build_local_knowledge_retrieval(
    session: AsyncSession,
) -> LocalKnowledgeRetrievalAdapter:
    """Bind the stable retrieval interface to the current SQLAlchemy implementation."""
    return LocalKnowledgeRetrievalAdapter(
        KnowledgeRetrieval(sqlalchemy_gateway.SqlAlchemyKnowledgeRetrievalGateway(session))
    )
