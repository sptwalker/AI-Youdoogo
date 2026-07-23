"""Collaboration Requests use cases and transaction ownership."""

from __future__ import annotations

from app.contexts.business.collaboration_requests.application.contracts import (
    AuthorizeCollaborationCommand,
    CollaborationAuthorizationResult,
    CollaborationRequestResult,
    CollaborationReviewPrincipal,
    CollaborationReviewQueueQuery,
    CreateCollaborationRequestCommand,
    HasCollaborationAuthorizationQuery,
    ListCollaborationAuthorizationsQuery,
    ReviewCollaborationRequestCommand,
    RevokeCollaborationAuthorizationCommand,
)
from app.contexts.business.collaboration_requests.application.errors import (
    CollaborationAuthorizationNotFound,
    CollaborationRequestNotFound,
    CollaborationReviewForbidden,
)
from app.contexts.business.collaboration_requests.application.ports import (
    AuditPort,
    AuditRequest,
    Clock,
    CollaborationUnitOfWorkFactory,
    IdentifierPort,
    ReviewScopePort,
)
from app.contexts.business.collaboration_requests.domain.models import (
    PENDING,
    CollaborationAuthorization,
    CollaborationRequest,
    classify_risk,
)


def _authorization_result(
    authorization: CollaborationAuthorization,
) -> CollaborationAuthorizationResult:
    return CollaborationAuthorizationResult(
        id=authorization.id,
        source_department_id=authorization.source_department_id,
        target_department_id=authorization.target_department_id,
        collab_type=authorization.collab_type,
        authorized_by=authorization.authorized_by,
        is_active=authorization.is_active,
        create_time=authorization.create_time,
    )


def _request_result(request: CollaborationRequest) -> CollaborationRequestResult:
    return CollaborationRequestResult(
        id=request.id,
        source_department_id=request.source_department_id,
        target_department_id=request.target_department_id,
        title=request.title,
        summary=request.summary,
        category=request.category,
        risk_level=request.risk_level,
        status=request.status,
        requested_by=request.requested_by,
        reviewed_by=request.reviewed_by,
        review_note=request.review_note,
        ref_type=request.ref_type,
        ref_id=request.ref_id,
        idempotency_key=request.idempotency_key,
        create_time=request.create_time,
    )


class CollaborationRequestsApplication:
    def __init__(
        self,
        *,
        uow_factory: CollaborationUnitOfWorkFactory,
        review_scope: ReviewScopePort,
        audit_port: AuditPort,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._review_scope = review_scope
        self._audit_port = audit_port
        self._clock = clock
        self._identifiers = identifiers

    async def authorize(
        self, command: AuthorizeCollaborationCommand
    ) -> CollaborationAuthorizationResult:
        authorization = CollaborationAuthorization(
            id=self._identifiers.new_id(),
            source_department_id=command.source_department_id,
            target_department_id=command.target_department_id,
            collab_type=command.collab_type,
            authorized_by=command.authorized_by,
            is_active=True,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.collaborations.add_authorization(authorization)
            await uow.commit()
        if command.actor_role is not None:
            await self._audit_port.record(
                AuditRequest(
                    actor_id=command.authorized_by,
                    actor_role=command.actor_role,
                    action="collab.authorize",
                    summary=f"授权跨部门协作 {command.collab_type}",
                    target_type="collab_authorization",
                    target_id=authorization.id,
                )
            )
        return _authorization_result(authorization)

    async def revoke(self, command: RevokeCollaborationAuthorizationCommand) -> None:
        async with self._uow_factory() as uow:
            authorization = await uow.collaborations.get_authorization(
                command.authorization_id
            )
            if authorization is None:
                raise CollaborationAuthorizationNotFound()
            authorization.revoke()
            await uow.collaborations.save_authorization(authorization)
            await uow.commit()
        if command.actor_role is not None:
            await self._audit_port.record(
                AuditRequest(
                    actor_id=command.actor_id,
                    actor_role=command.actor_role,
                    action="collab.revoke",
                    summary="撤销跨部门协作授权",
                    target_type="collab_authorization",
                    target_id=command.authorization_id,
                )
            )

    async def list_authorizations(
        self, query: ListCollaborationAuthorizationsQuery
    ) -> tuple[CollaborationAuthorizationResult, ...]:
        async with self._uow_factory() as uow:
            authorizations = await uow.collaborations.list_authorizations(
                target_department_id=query.target_department_id
            )
        return tuple(_authorization_result(item) for item in authorizations)

    async def has_authorization(
        self, query: HasCollaborationAuthorizationQuery
    ) -> bool:
        async with self._uow_factory() as uow:
            return await uow.collaborations.has_authorization(
                source_department_id=query.source_department_id,
                target_department_id=query.target_department_id,
                collab_type=query.collab_type,
            )

    async def create_request(
        self, command: CreateCollaborationRequestCommand
    ) -> CollaborationRequestResult:
        async with self._uow_factory() as uow:
            if command.idempotency_key:
                existing = await uow.collaborations.get_request_by_idempotency_key(
                    command.idempotency_key
                )
                if existing is not None:
                    return _request_result(existing)
            request = CollaborationRequest(
                id=self._identifiers.new_id(),
                source_department_id=command.source_department_id,
                target_department_id=command.target_department_id,
                title=command.title,
                summary=command.summary,
                category=command.category,
                risk_level=command.risk_level or classify_risk(command.category),
                status=PENDING,
                requested_by=command.requested_by,
                reviewed_by=None,
                review_note=None,
                ref_type=None,
                ref_id=None,
                idempotency_key=command.idempotency_key,
                create_time=self._clock.now(),
            )
            await uow.collaborations.add_request(request)
            await uow.commit()
        return _request_result(request)

    async def review_queue(
        self, query: CollaborationReviewQueueQuery
    ) -> tuple[CollaborationRequestResult, ...]:
        target_ids = await self._review_scope.reviewable_department_ids(
            supervisor_user_id=query.supervisor_user_id,
            is_admin=query.is_admin,
        )
        async with self._uow_factory() as uow:
            requests = await uow.collaborations.list_pending_requests(
                target_department_ids=target_ids
            )
        return tuple(_request_result(item) for item in requests)

    async def review_request(
        self, command: ReviewCollaborationRequestCommand
    ) -> CollaborationRequestResult:
        request = await self._review_request(command)
        await self._record_review_audit(command, request)
        return _request_result(request)

    async def review_request_authorized(
        self,
        command: ReviewCollaborationRequestCommand,
        principal: CollaborationReviewPrincipal,
    ) -> CollaborationRequestResult:
        if principal.id != command.reviewer_id:
            raise CollaborationReviewForbidden()
        async with self._uow_factory() as uow:
            request = await uow.collaborations.get_request(command.request_id)
            if request is None:
                raise CollaborationRequestNotFound()
            allowed = await self._review_scope.can_review(
                reviewer_id=principal.id,
                target_department_id=request.target_department_id,
                is_admin=principal.role_code == "admin",
            )
            if not allowed:
                raise CollaborationReviewForbidden()
            request.review(
                decision=command.decision,
                reviewer_id=command.reviewer_id,
                note=command.note,
            )
            await uow.collaborations.save_request(request)
            await uow.commit()
        await self._record_review_audit(command, request)
        return _request_result(request)

    async def _review_request(
        self, command: ReviewCollaborationRequestCommand
    ) -> CollaborationRequest:
        async with self._uow_factory() as uow:
            request = await uow.collaborations.get_request(command.request_id)
            if request is None:
                raise CollaborationRequestNotFound()
            request.review(
                decision=command.decision,
                reviewer_id=command.reviewer_id,
                note=command.note,
            )
            await uow.collaborations.save_request(request)
            await uow.commit()
        return request

    async def _record_review_audit(
        self,
        command: ReviewCollaborationRequestCommand,
        request: CollaborationRequest,
    ) -> None:
        if command.actor_role is None:
            return
        await self._audit_port.record(
            AuditRequest(
                actor_id=command.reviewer_id,
                actor_role=command.actor_role,
                action="collab.review",
                summary=f"复核跨部门协作 {request.title[:40]} → {request.status}",
                target_type="collab_request",
                target_id=request.id,
            )
        )
