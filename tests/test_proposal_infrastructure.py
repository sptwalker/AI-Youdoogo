"""Proposal SQLAlchemy mapper/repository compatibility with existing tables."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.proposal_management.application.contracts import ProposalViewer
from app.contexts.business.proposal_management.infrastructure.adapters import (
    CurrentProposalVisibilityPolicy,
)
from app.contexts.business.proposal_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyProposalRepository,
)
from app.contexts.business.proposal_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyProposalUnitOfWork,
)
from app.models import Base
from app.models.proposal import ProposalCard, ProposalReview


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def test_existing_rows_round_trip_without_schema_migration(session: AsyncSession) -> None:
    proposal_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    session.add_all(
        [
            ProposalCard(
                id=proposal_id,
                code="PROP-LEGACY01",
                title="历史提案",
                background="历史背景",
                plan="历史方案",
                creator_id=creator_id,
                status="reviewed",
            ),
            ProposalReview(
                proposal_id=proposal_id,
                review_type="ai_research",
                conclusion="历史预研",
            ),
        ]
    )
    await session.commit()

    repository = SQLAlchemyProposalRepository(session)
    proposal = await repository.get(proposal_id)
    reviews = await repository.list_reviews(proposal_id)

    assert proposal is not None
    assert proposal.code == "PROP-LEGACY01"
    assert proposal.status.value == "reviewed"
    assert reviews[0].conclusion == "历史预研"

    async with SQLAlchemyProposalUnitOfWork(session) as uow:
        current = await uow.proposals.get(proposal_id)
        assert current is not None
        human_review = current.record_human_review(
            review_id=uuid.uuid4(),
            reviewer_id=reviewer_id,
            conclusion="同意",
            decision="approve",
            occurred_at=datetime.now(UTC),
        )
        await uow.proposals.add_review(human_review)
        await uow.proposals.save(current)
        await uow.commit()

    persisted = await session.get(ProposalCard, proposal_id)
    assert persisted is not None
    await session.refresh(persisted)
    assert persisted.status == "approved"


async def test_repository_uses_plain_visibility_scope(session: AsyncSession) -> None:
    department_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    session.add_all(
        [
            ProposalCard(
                code="PROP-OWN",
                title="本人",
                background="b",
                plan="p",
                creator_id=viewer_id,
            ),
            ProposalCard(
                code="PROP-DEPT",
                title="同部门",
                background="b",
                plan="p",
                creator_id=uuid.uuid4(),
                department_id=department_id,
            ),
            ProposalCard(
                code="PROP-OTHER",
                title="不可见",
                background="b",
                plan="p",
                creator_id=uuid.uuid4(),
                department_id=uuid.uuid4(),
            ),
        ]
    )
    await session.commit()
    policy = CurrentProposalVisibilityPolicy()
    visibility = policy.visibility_for(
        ProposalViewer(id=viewer_id, role_code="member", department_id=department_id)
    )

    proposals = await SQLAlchemyProposalRepository(session).list_proposals(
        status=None,
        limit=100,
        visibility=visibility,
    )

    assert {proposal.code for proposal in proposals} == {"PROP-OWN", "PROP-DEPT"}
