"""Work Desktop dashboard, inbox, and download policy."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.contexts.business.work_desktop.application.contracts import (
    DeliverableDownloadResult,
    DeliverableProjection,
    DesktopPrincipal,
    DesktopResult,
    InboxItemRef,
    MyTaskResult,
    PendingItemResult,
)
from app.contexts.business.work_desktop.application.ports import (
    ChannelCounterPort,
    CollaborationQueuePort,
    DeliverableInboxPort,
    IdentityDirectoryPort,
    InboxStatePort,
    KnowledgeCounterPort,
    ObjectStoragePort,
    ProposalQueuePort,
    ResolutionQueuePort,
    TaskDashboardPort,
)
from app.contexts.business.work_desktop.domain import inbox
from app.contexts.shared_kernel import PermissionDenied, ResourceNotFound, RuleViolation

_LIMIT = 50


def _aware(moment: datetime) -> datetime:
    """DB 侧 SQLite 落 naive 时间，PG 落 aware；统一按 UTC 归一以便做时效差值。"""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class WorkDesktopApplication:
    """Own the read-side desktop policy without owning source aggregates."""

    def __init__(
        self,
        *,
        tasks: TaskDashboardPort,
        proposals: ProposalQueuePort,
        resolutions: ResolutionQueuePort,
        collaborations: CollaborationQueuePort,
        channels: ChannelCounterPort,
        knowledge: KnowledgeCounterPort,
        identities: IdentityDirectoryPort,
        deliverables: DeliverableInboxPort,
        storage: ObjectStoragePort,
        inbox_state: InboxStatePort,
    ) -> None:
        self._tasks = tasks
        self._proposals = proposals
        self._resolutions = resolutions
        self._collaborations = collaborations
        self._channels = channels
        self._knowledge = knowledge
        self._identities = identities
        self._deliverables = deliverables
        self._storage = storage
        self._inbox_state = inbox_state

    async def desktop(
        self,
        principal: DesktopPrincipal,
        *,
        weights: inbox.InboxWeights = inbox.DEFAULT_WEIGHTS,
    ) -> DesktopResult:
        pending = [
            PendingItemResult(
                kind="task",
                id=task.id,
                title=task.title,
                meta=task.task_type,
                priority=task.priority,
                create_time=task.create_time,
            )
            for task in await self._tasks.reported_for(principal, limit=_LIMIT)
        ]

        if principal.is_manager:
            pending.extend(
                PendingItemResult(
                    kind="proposal",
                    id=proposal.id,
                    title=proposal.title,
                    meta=proposal.code,
                    priority=proposal.priority,
                    create_time=proposal.create_time,
                )
                for proposal in await self._proposals.reviewed(limit=_LIMIT)
            )
            pending.extend(
                PendingItemResult(
                    kind="resolution",
                    id=resolution.id,
                    title=resolution.content[:60],
                    meta=(resolution.due_date.isoformat() if resolution.due_date else None),
                    priority="normal",
                    create_time=resolution.create_time,
                )
                for resolution in await self._resolutions.unconfirmed(limit=_LIMIT)
            )

        pending.extend(
            PendingItemResult(
                kind="collab",
                id=collaboration.id,
                title=collaboration.title,
                meta=collaboration.risk_level,
                priority=("high" if collaboration.risk_level == "high" else "normal"),
                create_time=collaboration.create_time,
            )
            for collaboration in await self._collaborations.review_queue(principal)
        )
        pending = await self._rank_inbox(principal, pending, weights)

        my_tasks = tuple(
            MyTaskResult(
                id=task.id,
                title=task.title,
                task_type=task.task_type,
                status=task.status,
                priority=task.priority,
                create_time=task.create_time,
            )
            for task in await self._tasks.active_for(principal, limit=_LIMIT)
        )
        return DesktopResult(
            principal=principal,
            pending=tuple(pending),
            my_tasks=my_tasks,
            channel_count=await self._channels.count(),
            knowledge_count=await self._knowledge.count_for(principal),
        )

    async def supervised_desktop(
        self, operator: DesktopPrincipal, target_user_id: uuid.UUID
    ) -> DesktopResult:
        if not operator.is_admin:
            raise PermissionDenied("仅管理员可监督他人桌面")
        target = await self._identities.get(target_user_id)
        if target is None or target.is_deleted:
            raise ResourceNotFound("用户不存在")
        return await self.desktop(target)

    async def _rank_inbox(
        self,
        principal: DesktopPrincipal,
        items: list[PendingItemResult],
        weights: inbox.InboxWeights,
    ) -> list[PendingItemResult]:
        """去重 + 4 因子打分 + 叠加持久读态，按分数（再按时间）降序。"""
        states = await self._inbox_state.states_for(principal.id)
        now = datetime.now(UTC)
        seen: set[tuple[str, uuid.UUID]] = set()
        ranked: list[PendingItemResult] = []
        for item in items:
            key = (item.kind, item.id)
            if key in seen:  # 同一来源去重合并，保留首现
                continue
            seen.add(key)
            state = states.get(key)
            ranked.append(
                PendingItemResult(
                    kind=item.kind,
                    id=item.id,
                    title=item.title,
                    meta=item.meta,
                    priority=item.priority,
                    create_time=item.create_time,
                    score=inbox.priority_score(
                        item.kind, item.priority, _aware(item.create_time), now, weights
                    ),
                    is_read=state.is_read if state else False,
                    is_processed=state.is_processed if state else False,
                    ai_summary=state.ai_summary if state else None,
                )
            )
        ranked.sort(key=lambda i: (i.score, i.create_time), reverse=True)
        return ranked

    async def mark_inbox(
        self,
        principal: DesktopPrincipal,
        items: tuple[InboxItemRef, ...],
        *,
        is_read: bool | None = None,
        is_processed: bool | None = None,
    ) -> int:
        """批量置读/处理态（真人逐条/一次确认触发）。仅写本人读态，不触碰来源聚合、不外发。"""
        if is_read is None and is_processed is None:
            raise RuleViolation("批量处理需至少指定 is_read 或 is_processed 之一")
        if not items:
            return 0
        return await self._inbox_state.mark(
            principal.id, items, is_read=is_read, is_processed=is_processed
        )

    async def list_deliverables(
        self,
        principal: DesktopPrincipal,
        *,
        requested_owner_id: uuid.UUID | None = None,
    ) -> tuple[DeliverableProjection, ...]:
        owner_id = principal.id
        if requested_owner_id is not None and requested_owner_id != principal.id:
            if not principal.is_admin:
                raise PermissionDenied("仅管理员可查看他人交付区")
            owner_id = requested_owner_id
        return await self._deliverables.list_for(owner_id, limit=_LIMIT)

    async def download_deliverable(
        self, principal: DesktopPrincipal, deliverable_id: uuid.UUID
    ) -> DeliverableDownloadResult:
        deliverable = await self._deliverables.get(deliverable_id)
        if deliverable is None or deliverable.is_deleted:
            raise ResourceNotFound("交付物不存在")
        if deliverable.owner_user_id != principal.id and not principal.is_admin:
            raise PermissionDenied("无权下载该交付物")
        _, _, object_name = deliverable.storage_path.partition("/")
        content = await self._storage.get_object_bytes(object_name)
        return DeliverableDownloadResult(
            file_name=deliverable.file_name,
            content=content,
        )
