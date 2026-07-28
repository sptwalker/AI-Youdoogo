"""Fast Group Messaging application tests with no ORM, Redis, Agent, or storage."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.contexts.business.group_messaging.application.contracts import (
    AgentReplyRequest,
    AgentReplyStreamEvent,
    ArchiveRequest,
    CreateChannelCommand,
    MemberInput,
    MessageStreamEvent,
    PostMessageCommand,
    PromotionRequest,
    UploadAttachmentCommand,
)
from app.contexts.business.group_messaging.application.use_cases import (
    GroupMessagingApplication,
)
from app.contexts.business.group_messaging.domain.models import (
    MEMBER_HUMAN,
    Channel,
    MemberDraft,
    Message,
)
from app.contexts.business.group_messaging.infrastructure.adapters import (
    PublishedPromotionAdapter,
)
from app.contexts.business.proposal_management import public as proposal_management
from app.contexts.shared_kernel import InvalidInput, PermissionDenied, RuleViolation


class FakeRepository:
    def __init__(self) -> None:
        self.channels: dict[uuid.UUID, Channel] = {}
        self.members: dict[tuple[uuid.UUID, str, uuid.UUID], MemberDraft] = {}
        self.messages: dict[uuid.UUID, Message] = {}
        self.attachment_visible = False

    async def add_channel(self, channel: Channel) -> None:
        self.channels[channel.id] = channel

    async def get_channel(
        self, channel_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Channel | None:
        channel = self.channels.get(channel_id)
        if channel is None or (channel.is_deleted and not include_deleted):
            return None
        return channel

    async def save_channel(self, channel: Channel) -> None:
        self.channels[channel.id] = channel

    async def list_channels(self, *, department_id: uuid.UUID | None = None) -> list[Channel]:
        return [
            channel
            for channel in self.channels.values()
            if not channel.is_deleted
            and (department_id is None or channel.department_id == department_id)
        ]

    async def all_channel_ids(self) -> list[uuid.UUID]:
        return [channel.id for channel in await self.list_channels()]

    async def add_members(self, channel_id: uuid.UUID, members: tuple[MemberDraft, ...]) -> int:
        added = 0
        for member in members:
            key = (channel_id, member.member_type, member.member_id)
            if key not in self.members:
                self.members[key] = member
                added += 1
        return added

    async def remove_member(
        self, channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID
    ) -> None:
        self.members.pop((channel_id, member_type, member_id), None)

    async def deactivate_members(self, channel_id: uuid.UUID) -> None:
        self.members = {key: member for key, member in self.members.items() if key[0] != channel_id}

    async def list_members(self, channel_id: uuid.UUID) -> list[MemberDraft]:
        return [member for key, member in self.members.items() if key[0] == channel_id]

    async def channel_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        return [
            channel_id
            for channel_id, member_type, member_id in self.members
            if member_type == MEMBER_HUMAN and member_id == user_id
        ]

    async def is_member(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return (channel_id, MEMBER_HUMAN, user_id) in self.members

    async def mark_read(self, channel_id: uuid.UUID, user_id: uuid.UUID, read_at: datetime) -> None:
        return None

    async def channels_with_unread(self, user_id: uuid.UUID) -> list[tuple[Channel, int]]:
        return [(self.channels[value], 0) for value in await self.channel_ids_for_user(user_id)]

    async def add_message(self, message: Message) -> None:
        self.messages[message.id] = message

    async def get_message(self, message_id: uuid.UUID) -> Message | None:
        return self.messages.get(message_id)

    async def save_message(self, message: Message) -> None:
        self.messages[message.id] = message

    async def list_messages(self, channel_id: uuid.UUID, *, limit: int) -> list[Message]:
        rows = [message for message in self.messages.values() if message.channel_id == channel_id]
        return rows[-limit:]

    async def attachment_visible_to_user(self, *, storage_path: str, user_id: uuid.UUID) -> bool:
        return self.attachment_visible


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository, transactions: dict[str, int]) -> None:
        self.messages = repository
        self._transactions = transactions

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self._transactions["commits"] += 1

    async def rollback(self) -> None:
        self._transactions["rollbacks"] += 1


class FakeRealtime:
    def __init__(self) -> None:
        self.published: list[tuple[uuid.UUID, str, dict[str, object]]] = []

    async def publish(
        self, channel_id: uuid.UUID, event_name: str, data: dict[str, object]
    ) -> None:
        self.published.append((channel_id, event_name, data))


class FakeSubscription:
    async def _empty(self) -> AsyncIterator[MessageStreamEvent]:
        if False:
            yield MessageStreamEvent("never", {})

    def subscribe_user(
        self, *, user_id: uuid.UUID, channel_ids: tuple[uuid.UUID, ...]
    ) -> AsyncIterator[MessageStreamEvent]:
        return self._empty()


class FakeAgentReplies:
    def stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]:
        return self._stream(request)

    async def _stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]:
        yield AgentReplyStreamEvent(
            "start",
            speaker_agent_id=request.agent_id,
            speaker_name="顾问",
        )
        yield AgentReplyStreamEvent("delta", text="第一段")
        yield AgentReplyStreamEvent("delta", text="第二段")
        yield AgentReplyStreamEvent(
            "complete",
            speaker_agent_id=request.agent_id,
            speaker_name="顾问",
            content="第一段第二段",
            source_record_id=uuid.UUID(int=99),
        )


class FakeConsultedReplies(FakeAgentReplies):
    async def _stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]:
        yield AgentReplyStreamEvent(
            "start",
            speaker_agent_id=request.agent_id,
            speaker_name="主顾问",
        )
        yield AgentReplyStreamEvent("delta", text="主回复")
        yield AgentReplyStreamEvent(
            "complete",
            speaker_agent_id=request.agent_id,
            speaker_name="主顾问",
            content="主回复",
            source_record_id=uuid.UUID(int=99),
        )
        yield AgentReplyStreamEvent(
            "start",
            speaker_agent_id=uuid.UUID(int=77),
            speaker_name="被咨询顾问",
        )
        yield AgentReplyStreamEvent("delta", text="补充意见")
        yield AgentReplyStreamEvent(
            "complete",
            speaker_agent_id=uuid.UUID(int=77),
            speaker_name="被咨询顾问",
            content="补充意见",
            source_record_id=uuid.UUID(int=100),
            publish_realtime=False,
        )


class FakeStorage:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def put(self, *, object_name: str, content: bytes, content_type: str) -> str:
        self.values[object_name] = content
        return f"youdoo/{object_name}"

    async def get(self, *, object_name: str) -> bytes:
        return self.values[object_name]


class FakeArchive:
    async def archive(self, request: ArchiveRequest) -> None:
        return None


class FakePromotion:
    def __init__(self) -> None:
        self.proposals: dict[uuid.UUID, uuid.UUID] = {}
        self.calls = 0

    async def promote(self, request: PromotionRequest) -> uuid.UUID:
        self.calls += 1
        if request.target == "proposal":
            return self.proposals.setdefault(request.source_message_id, uuid.uuid4())
        return uuid.UUID(int=88)


class CommitAwareMessageRepository(FakeRepository):
    """Keep a message update invisible until its Unit of Work commits."""

    def __init__(self) -> None:
        super().__init__()
        self._pending_message: Message | None = None

    async def get_message(self, message_id: uuid.UUID) -> Message | None:
        message = self.messages.get(message_id)
        return deepcopy(message) if message is not None else None

    async def save_message(self, message: Message) -> None:
        self._pending_message = deepcopy(message)

    def commit_pending_message(self) -> None:
        if self._pending_message is not None:
            self.messages[self._pending_message.id] = self._pending_message
        self._pending_message = None

    def discard_pending_message(self) -> None:
        self._pending_message = None


class FailFirstMessagePromotionUnitOfWork:
    def __init__(
        self,
        repository: CommitAwareMessageRepository,
        transactions: dict[str, int | bool],
    ) -> None:
        self.messages = repository
        self._transactions = transactions

    async def __aenter__(self) -> FailFirstMessagePromotionUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self._transactions["commits"] = int(self._transactions["commits"]) + 1
        if self._transactions["fail_next_commit"]:
            self._transactions["fail_next_commit"] = False
            raise RuntimeError("message commit failed")
        self.messages.commit_pending_message()

    async def rollback(self) -> None:
        self.messages.discard_pending_message()
        self._transactions["rollbacks"] = int(self._transactions["rollbacks"]) + 1


class FakeOutbox:
    def __init__(self) -> None:
        self.channel_ids: list[uuid.UUID] = []

    async def enqueue_disband_archive(self, channel_id: uuid.UUID) -> None:
        self.channel_ids.append(channel_id)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 23, tzinfo=UTC)


class SequenceIdentifiers:
    def __init__(self, values: list[uuid.UUID]) -> None:
        self._values = iter(values)

    def new_id(self) -> uuid.UUID:
        return next(self._values)

    def new_object_token(self) -> str:
        return "fixed-object"


def _application(
    repository: FakeRepository,
    identifiers: SequenceIdentifiers,
    *,
    agent_replies: FakeAgentReplies | None = None,
) -> tuple[GroupMessagingApplication, FakeRealtime, dict[str, int]]:
    realtime = FakeRealtime()
    transactions = {"commits": 0, "rollbacks": 0}
    application = GroupMessagingApplication(
        uow_factory=lambda: FakeUnitOfWork(repository, transactions),
        realtime_delivery=realtime,
        realtime_subscription=FakeSubscription(),
        agent_replies=agent_replies or FakeAgentReplies(),
        attachment_storage=FakeStorage(),
        archive_port=FakeArchive(),
        promotion_port=FakePromotion(),
        outbox_port=FakeOutbox(),
        clock=FixedClock(),
        identifiers=identifiers,
    )
    return application, realtime, transactions


async def test_membership_and_owner_protection_are_application_rules() -> None:
    channel_id = uuid.UUID(int=1)
    owner_id = uuid.UUID(int=2)
    member_id = uuid.UUID(int=3)
    repository = FakeRepository()
    application, _, transactions = _application(repository, SequenceIdentifiers([channel_id]))

    await application.create_channel(
        CreateChannelCommand(
            name="项目群",
            creator_id=owner_id,
            members=(MemberInput(MEMBER_HUMAN, member_id, "成员"),),
        )
    )
    with pytest.raises(PermissionDenied, match="仅群主"):
        await application.add_members(
            channel_id,
            (MemberInput(MEMBER_HUMAN, uuid.UUID(int=4)),),
            owner_id=member_id,
        )
    with pytest.raises(InvalidInput, match="不能踢出群主"):
        await application.remove_member(
            channel_id,
            MEMBER_HUMAN,
            owner_id,
            owner_id=owner_id,
        )

    assert await repository.is_member(channel_id, owner_id)
    assert transactions == {"commits": 1, "rollbacks": 2}


async def test_message_stream_keeps_start_delta_end_order_and_delivery() -> None:
    channel_id = uuid.UUID(int=10)
    human_message_id = uuid.UUID(int=11)
    ai_message_id = uuid.UUID(int=12)
    user_id = uuid.UUID(int=13)
    agent_id = uuid.UUID(int=14)
    repository = FakeRepository()
    repository.channels[channel_id] = Channel(
        id=channel_id,
        name="项目群",
        creator_id=user_id,
        create_time=FixedClock().now(),
    )
    repository.members[(channel_id, MEMBER_HUMAN, user_id)] = MemberDraft(
        MEMBER_HUMAN, user_id, "发言人"
    )
    application, realtime, transactions = _application(
        repository,
        SequenceIdentifiers([human_message_id, ai_message_id]),
    )

    events = [
        event
        async for event in application.post_message_stream(
            PostMessageCommand(
                channel_id=channel_id,
                speaker_id=user_id,
                speaker_name="发言人",
                content="请给建议",
                mentioned_agent_ids=(agent_id, agent_id),
                require_member_id=user_id,
            )
        )
    ]

    assert [event.name for event in events] == [
        "message_end",
        "message_start",
        "delta",
        "delta",
        "message_end",
    ]
    assert [event.data.get("text") for event in events[2:4]] == ["第一段", "第二段"]
    assert len(repository.messages) == 2
    assert [item[1] for item in realtime.published] == ["message", "message"]
    assert transactions["commits"] == 2


async def test_consulted_reply_persists_without_realtime_publish() -> None:
    channel_id = uuid.UUID(int=20)
    user_id = uuid.UUID(int=21)
    agent_id = uuid.UUID(int=22)
    repository = FakeRepository()
    repository.channels[channel_id] = Channel(
        id=channel_id,
        name="项目群",
        creator_id=user_id,
        create_time=FixedClock().now(),
    )
    repository.members[(channel_id, MEMBER_HUMAN, user_id)] = MemberDraft(
        MEMBER_HUMAN, user_id, "发言人"
    )
    application, realtime, transactions = _application(
        repository,
        SequenceIdentifiers([uuid.UUID(int=23), uuid.UUID(int=24), uuid.UUID(int=25)]),
        agent_replies=FakeConsultedReplies(),
    )

    events = [
        event
        async for event in application.post_message_stream(
            PostMessageCommand(
                channel_id=channel_id,
                speaker_id=user_id,
                speaker_name="发言人",
                content="请给建议",
                mentioned_agent_ids=(agent_id,),
                require_member_id=user_id,
            )
        )
    ]

    assert [event.name for event in events] == [
        "message_end",
        "message_start",
        "delta",
        "message_end",
        "message_start",
        "delta",
        "message_end",
    ]
    assert events[4].data == {
        "speaker_agent_id": str(uuid.UUID(int=77)),
        "speaker_name": "被咨询顾问",
    }
    assert events[5].data == {"text": "补充意见"}
    assert [item[2]["content"] for item in realtime.published] == ["请给建议", "主回复"]
    assert len(repository.messages) == 3
    assert transactions["commits"] == 3


async def test_attachment_limit_and_path_rules_are_owned_by_application() -> None:
    repository = FakeRepository()
    application, _, _ = _application(repository, SequenceIdentifiers([]))

    with pytest.raises(RuleViolation, match="文件过大"):
        await application.upload_attachment(
            UploadAttachmentCommand(
                name="large.bin",
                content=b"x" * (20 * 1024 * 1024 + 1),
                content_type="application/octet-stream",
            )
        )
    with pytest.raises(InvalidInput, match="非法附件路径"):
        await application.download_attachment(
            storage_path="youdoo/secret/value",
            name="value",
            user_id=uuid.UUID(int=22),
        )


async def test_promotion_retry_after_message_commit_failure_reuses_proposal() -> None:
    message_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    repository = CommitAwareMessageRepository()
    repository.messages[message_id] = Message(
        id=message_id,
        channel_id=uuid.uuid4(),
        speaker_type="human",
        speaker_id=creator_id,
        speaker_name="发言人",
        content="建议启动会员体系",
        create_time=FixedClock().now(),
    )
    transactions: dict[str, int | bool] = {
        "commits": 0,
        "rollbacks": 0,
        "fail_next_commit": True,
    }
    promotion = FakePromotion()
    application = GroupMessagingApplication(
        uow_factory=lambda: FailFirstMessagePromotionUnitOfWork(repository, transactions),
        realtime_delivery=FakeRealtime(),
        realtime_subscription=FakeSubscription(),
        agent_replies=FakeAgentReplies(),
        attachment_storage=FakeStorage(),
        archive_port=FakeArchive(),
        promotion_port=promotion,
        outbox_port=FakeOutbox(),
        clock=FixedClock(),
        identifiers=SequenceIdentifiers([]),
    )

    with pytest.raises(RuntimeError, match="message commit failed"):
        await application.promote_message(message_id, target="proposal", creator_id=creator_id)

    result = await application.promote_message(
        message_id,
        target="proposal",
        creator_id=creator_id,
    )

    assert promotion.calls == 2
    assert len(promotion.proposals) == 1
    assert repository.messages[message_id].ref_id == uuid.UUID(result["ref_id"])


async def test_proposal_promotion_forwards_source_message_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_message_id = uuid.uuid4()
    expected_proposal_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async def create_proposal(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(id=expected_proposal_id)

    monkeypatch.setattr(proposal_management, "create_proposal", create_proposal)
    adapter = PublishedPromotionAdapter(object())

    proposal_id = await adapter.promote(
        PromotionRequest(
            target="proposal",
            title="讨论结论",
            content="讨论内容",
            creator_id=uuid.uuid4(),
            source_message_id=source_message_id,
        )
    )

    assert proposal_id == expected_proposal_id
    assert captured["source_message_id"] == source_message_id
