"""Access Control decisions and grant use cases behind pure boundaries."""

from __future__ import annotations

import uuid

from app.contexts.foundations.access_control.application.contracts import (
    CreateGrantCommand,
    GrantResult,
    ListGrantsQuery,
)
from app.contexts.foundations.access_control.application.ports import (
    AccessControlUnitOfWorkFactory,
    Clock,
    DepartmentHierarchyPort,
    IdentifierPort,
    KnowledgeVisibilityPort,
)
from app.contexts.foundations.access_control.contracts import (
    PolicyDecision,
    ResourceReadPolicyRequest,
    RolePolicyRequest,
    RowPolicyRequest,
    RowVisibilityScope,
)
from app.contexts.foundations.access_control.domain.models import (
    GranteeType,
    GrantTarget,
    ResourceGrantRecord,
    validate_grantee_type,
    validate_permission,
    validate_resource_type,
)
from app.contexts.foundations.access_control.domain.policies import (
    decide_role,
    decide_row_visibility,
    row_visibility_scope,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.shared_kernel import ResourceNotFound


def _result(grant: ResourceGrantRecord) -> GrantResult:
    return GrantResult(
        id=grant.id,
        resource_type=grant.resource_type,
        resource_id=grant.resource_id,
        grantee_type=grant.grantee_type.value,
        grantee_id=grant.grantee_id,
        perm=grant.permission.value,
        granted_by=grant.granted_by,
        expires_at=grant.expires_at,
        create_time=grant.create_time,
    )


class AccessControlApplication:
    """Canonical policy and explicit-grant boundary."""

    def __init__(
        self,
        *,
        uow_factory: AccessControlUnitOfWorkFactory,
        departments: DepartmentHierarchyPort,
        knowledge_visibility: KnowledgeVisibilityPort,
        identifiers: IdentifierPort,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._departments = departments
        self._knowledge_visibility = knowledge_visibility
        self._identifiers = identifiers
        self._clock = clock

    def decide_role(self, request: RolePolicyRequest) -> PolicyDecision:
        return decide_role(request)

    def decide_row_visibility(self, request: RowPolicyRequest) -> PolicyDecision:
        return decide_row_visibility(request)

    def row_visibility_scope(self, principal: Principal) -> RowVisibilityScope:
        return row_visibility_scope(principal)

    async def get_grant(self, grant_id: uuid.UUID) -> GrantResult:
        async with self._uow_factory() as uow:
            grant = await uow.grants.get(grant_id)
        if grant is None or grant.is_deleted:
            raise ResourceNotFound("授权记录不存在")
        return _result(grant)

    async def create_grant(self, command: CreateGrantCommand) -> GrantResult:
        resource_type = validate_resource_type(command.resource_type)
        grantee_type = validate_grantee_type(command.grantee_type)
        permission = validate_permission(command.permission)
        grant = ResourceGrantRecord(
            id=self._identifiers.new_id(),
            resource_type=resource_type,
            resource_id=command.resource_id,
            grantee_type=grantee_type,
            grantee_id=command.grantee_id,
            permission=permission,
            granted_by=command.granted_by,
            expires_at=command.expires_at,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.grants.add(grant)
            await uow.commit()
        # The legacy service refreshed after commit; reload so database-side
        # datetime normalization/default behavior remains observable.
        async with self._uow_factory() as uow:
            persisted = await uow.grants.get(grant.id)
        return _result(persisted or grant)

    async def revoke_grant(self, grant_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            grant = await uow.grants.get(grant_id)
            if grant is None or grant.is_deleted:
                raise ResourceNotFound("授权记录不存在")
            grant.revoke()
            await uow.grants.save(grant)
            await uow.commit()

    async def list_grants(self, query: ListGrantsQuery) -> tuple[GrantResult, ...]:
        async with self._uow_factory() as uow:
            grants = await uow.grants.list_records(
                resource_type=query.resource_type,
                grantee_id=query.grantee_id,
            )
        return tuple(_result(grant) for grant in grants)

    async def granted_resource_ids(
        self,
        principal: Principal,
        resource_type: str,
    ) -> tuple[uuid.UUID, ...]:
        targets = [
            GrantTarget(
                grantee_type=(
                    GranteeType.AGENT
                    if principal.principal_type is PrincipalType.AGENT
                    else GranteeType.USER
                ),
                grantee_id=principal.principal_id,
            )
        ]
        ancestor_ids = await self._departments.ancestors_of(principal.department_id)
        targets.extend(
            GrantTarget(GranteeType.DEPARTMENT, department_id)
            for department_id in ancestor_ids
        )
        async with self._uow_factory() as uow:
            grants = await uow.grants.find_for_targets(
                resource_type=resource_type,
                targets=tuple(targets),
            )
        now = self._clock.now()
        return tuple(
            grant.resource_id for grant in grants if grant.is_effective_at(now)
        )

    async def visible_knowledge_ids(self, principal: Principal) -> tuple[uuid.UUID, ...]:
        extra_ids = await self.granted_resource_ids(principal, "knowledge_base")
        return await self._knowledge_visibility.visible_ids(
            department_id=principal.department_id,
            is_admin=principal.role_code == "admin",
            extra_knowledge_ids=extra_ids,
        )

    async def decide_resource_read(
        self,
        request: ResourceReadPolicyRequest,
    ) -> PolicyDecision:
        if request.principal.role_code == "admin":
            return PolicyDecision(allowed=True)
        if request.resource_type == "knowledge_base":
            allowed_ids = await self.visible_knowledge_ids(request.principal)
        else:
            allowed_ids = await self.granted_resource_ids(
                request.principal,
                request.resource_type,
            )
        if request.resource_id in allowed_ids:
            return PolicyDecision(allowed=True)
        return PolicyDecision(allowed=False, reason="无权访问资源")
