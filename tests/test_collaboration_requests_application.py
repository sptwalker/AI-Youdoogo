"""Fast domain/application tests for the Collaboration Requests slice."""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

import pytest

from app.contexts.business.collaboration_requests.application.contracts import (
    CollaborationReviewPrincipal,
    CollaborationReviewQueueQuery,
    CreateCollaborationRequestCommand,
    ReviewCollaborationRequestCommand,
)
from app.contexts.business.collaboration_requests.application.use_cases import (
    CollaborationRequestsApplication,
)
from app.contexts.business.collaboration_requests.domain.errors import (
    CollaborationReviewNotAllowed,
    InvalidReviewDecision,
)
from app.contexts.business.collaboration_requests.domain.models import (
    PENDING,
    CollaborationAuthorization,
    CollaborationRequest,
    classify_risk,
)


class FakeRepository:
    def __init__(self) -> None:
        self.authorizations: dict[uuid.UUID, CollaborationAuthorization] = {}
        self.requests: dict[uuid.UUID, CollaborationRequest] = {}

    async def add_authorization(self, item: CollaborationAuthorization) -> None:
        self.authorizations[item.id] = copy.deepcopy(item)

    async def get_authorization(
        self, item_id: uuid.UUID
    ) -> CollaborationAuthorization | None:
        item = self.authorizations.get(item_id)
        return copy.deepcopy(item) if item and not item.is_deleted else None

    async def save_authorization(self, item: CollaborationAuthorization) -> None:
        self.authorizations[item.id] = copy.deepcopy(item)

    async def list_authorizations(
        self, *, target_department_id: uuid.UUID | None
    ) -> list[CollaborationAuthorization]:
        return [
            copy.deepcopy(item)
            for item in self.authorizations.values()
            if not item.is_deleted
            and (
                target_department_id is None
                or item.target_department_id == target_department_id
            )
        ]

    async def has_authorization(
        self,
        *,
        source_department_id: uuid.UUID,
        target_department_id: uuid.UUID,
        collab_type: str,
    ) -> bool:
        return any(
            item.source_department_id == source_department_id
            and item.target_department_id == target_department_id
            and item.collab_type == collab_type
            and item.is_active
            and not item.is_deleted
            for item in self.authorizations.values()
        )

    async def add_request(self, item: CollaborationRequest) -> None:
        self.requests[item.id] = copy.deepcopy(item)

    async def get_request(self, item_id: uuid.UUID) -> CollaborationRequest | None:
        item = self.requests.get(item_id)
        return copy.deepcopy(item) if item else None

    async def get_request_by_idempotency_key(
        self, key: str
    ) -> CollaborationRequest | None:
        return next(
            (
                copy.deepcopy(item)
                for item in self.requests.values()
                if item.idempotency_key == key
            ),
            None,
        )

    async def save_request(self, item: CollaborationRequest) -> None:
        self.requests[item.id] = copy.deepcopy(item)

    async def list_pending_requests(
        self, *, target_department_ids: tuple[uuid.UUID, ...] | None
    ) -> list[CollaborationRequest]:
        return [
            copy.deepcopy(item)
            for item in self.requests.values()
            if item.status == PENDING
            and (
                target_department_ids is None
                or item.target_department_id in target_department_ids
            )
        ]


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.collaborations = repository
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class StaticScope:
    def __init__(self, target_ids: tuple[uuid.UUID, ...] | None = None) -> None:
        self.target_ids = target_ids

    async def reviewable_department_ids(
        self, *, supervisor_user_id: uuid.UUID, is_admin: bool
    ) -> tuple[uuid.UUID, ...] | None:
        return None if is_admin else self.target_ids

    async def can_review(
        self,
        *,
        reviewer_id: uuid.UUID,
        target_department_id: uuid.UUID,
        is_admin: bool,
    ) -> bool:
        return is_admin or self.target_ids is None or target_department_id in self.target_ids


class AuditSpy:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def record(self, request: object) -> None:
        self.requests.append(request)


class StaticClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class SequenceIdentifiers:
    def __init__(self) -> None:
        self.values = iter(uuid.UUID(int=value) for value in range(1, 20))

    def new_id(self) -> uuid.UUID:
        return next(self.values)


def _application(
    *, target_ids: tuple[uuid.UUID, ...] | None = None
) -> tuple[CollaborationRequestsApplication, FakeRepository, list[FakeUnitOfWork]]:
    repository = FakeRepository()
    units: list[FakeUnitOfWork] = []

    def factory() -> FakeUnitOfWork:
        unit = FakeUnitOfWork(repository)
        units.append(unit)
        return unit

    return (
        CollaborationRequestsApplication(
            uow_factory=factory,
            review_scope=StaticScope(target_ids),
            audit_port=AuditSpy(),
            clock=StaticClock(),
            identifiers=SequenceIdentifiers(),
        ),
        repository,
        units,
    )


def test_domain_owns_risk_and_review_rules() -> None:
    assert classify_risk("finance") == "high"
    assert classify_risk("analysis") == "low"
    request = CollaborationRequest(
        id=uuid.uuid4(),
        source_department_id=None,
        target_department_id=uuid.uuid4(),
        title="request",
        summary=None,
        category=None,
        risk_level="low",
        status=PENDING,
        requested_by=None,
        reviewed_by=None,
        review_note=None,
        ref_type=None,
        ref_id=None,
        idempotency_key=None,
        create_time=datetime.now(UTC),
    )
    with pytest.raises(InvalidReviewDecision):
        request.review(decision="maybe", reviewer_id=uuid.uuid4(), note=None)
    request.review(decision="approve", reviewer_id=uuid.uuid4(), note="ok")
    with pytest.raises(CollaborationReviewNotAllowed):
        request.review(decision="reject", reviewer_id=uuid.uuid4(), note=None)


async def test_create_is_idempotent_and_commits_only_the_new_request() -> None:
    application, repository, units = _application()
    target = uuid.uuid4()
    command = CreateCollaborationRequestCommand(
        target_department_id=target,
        title="预算协作",
        category="budget",
        idempotency_key="workflow:request:1",
    )

    first = await application.create_request(command)
    replay = await application.create_request(command)

    assert first == replay
    assert first.risk_level == "high"
    assert len(repository.requests) == 1
    assert [unit.commits for unit in units] == [1, 0]


async def test_review_queue_scope_and_transition_are_application_owned() -> None:
    target = uuid.uuid4()
    other = uuid.uuid4()
    application, _repository, units = _application(target_ids=(target,))
    visible = await application.create_request(
        CreateCollaborationRequestCommand(target_department_id=target, title="visible")
    )
    await application.create_request(
        CreateCollaborationRequestCommand(target_department_id=other, title="hidden")
    )

    queue = await application.review_queue(
        CollaborationReviewQueueQuery(supervisor_user_id=uuid.uuid4())
    )
    reviewed = await application.review_request(
        ReviewCollaborationRequestCommand(
            request_id=visible.id,
            decision="approve",
            reviewer_id=uuid.uuid4(),
            note="ok",
        )
    )

    assert [item.title for item in queue] == ["visible"]
    assert reviewed.status == "approved"
    assert units[-1].commits == 1


async def test_authorized_review_uses_pure_principal_and_scope_port() -> None:
    target = uuid.uuid4()
    application, _repository, _units = _application(target_ids=(target,))
    request = await application.create_request(
        CreateCollaborationRequestCommand(target_department_id=target, title="review")
    )
    reviewer = uuid.uuid4()

    result = await application.review_request_authorized(
        ReviewCollaborationRequestCommand(
            request_id=request.id,
            decision="reject",
            reviewer_id=reviewer,
        ),
        CollaborationReviewPrincipal(id=reviewer, role_code="member"),
    )

    assert result.status == "rejected"
