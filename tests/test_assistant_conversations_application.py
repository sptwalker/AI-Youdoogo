"""Database-free contracts for the Assistant Conversations application boundary."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionEvent,
    AgentExecutionRequest,
    ArchiveConversationRequest,
    ConsultedReply,
    OrchestrationResult,
    Principal,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.application.use_cases import (
    AssistantConversationsApplication,
)
from app.contexts.business.assistant_conversations.domain.models import (
    SPEAKER_USER,
    Assistant,
    ConversationMessage,
    Participant,
)
from app.contexts.shared_kernel import RuleViolation


class _Store:
    def __init__(self, messages: list[ConversationMessage] | None = None) -> None:
        self.messages = list(messages or [])
        self.commits = 0


class _Repository:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def list_recent(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> list[ConversationMessage]:
        rows = [row for row in self._store.messages if row.owner_user_id == owner_user_id]
        return rows[-limit:]

    async def list_since(
        self, owner_user_id: uuid.UUID, *, since: datetime
    ) -> list[ConversationMessage]:
        return [
            row
            for row in self._store.messages
            if row.owner_user_id == owner_user_id and row.create_time >= since
        ]

    async def list_before(
        self, owner_user_id: uuid.UUID, *, before: datetime
    ) -> list[ConversationMessage]:
        return [
            row
            for row in self._store.messages
            if row.owner_user_id == owner_user_id and row.create_time < before
        ]

    async def add(self, message: ConversationMessage) -> None:
        self._store.messages.append(message)

    async def delete(self, message_ids: tuple[uuid.UUID, ...]) -> None:
        ids = set(message_ids)
        self._store.messages = [row for row in self._store.messages if row.id not in ids]


class _UnitOfWork:
    def __init__(self, store: _Store) -> None:
        self._store = store
        self._messages = _Repository(store)

    @property
    def messages(self) -> _Repository:
        return self._messages

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._store.commits += 1

    async def rollback(self) -> None:
        return None


class _Assistants:
    def __init__(self, principal_id: uuid.UUID, added: tuple[Participant, ...] = ()) -> None:
        self.assistant = Assistant(
            id=uuid.UUID(int=10),
            owner_user_id=principal_id,
            name="爱丽丝的助理",
            personal_knowledge_base_id=uuid.UUID(int=11),
        )
        self.added = added
        self.get_calls = 0
        self.resolve_calls: list[tuple[uuid.UUID, ...]] = []

    async def get_or_create(self, principal: Principal) -> Assistant:
        self.get_calls += 1
        assert principal.id == self.assistant.owner_user_id
        return self.assistant

    async def list_addable(self) -> tuple[Participant, ...]:
        return self.added

    async def resolve_addable(self, agent_ids: tuple[uuid.UUID, ...]) -> tuple[Participant, ...]:
        self.resolve_calls.append(agent_ids)
        by_id = {agent.id: agent for agent in self.added}
        return tuple(by_id[agent_id] for agent_id in agent_ids)


class _Configuration:
    def __init__(self, *, rounds: int = 1, history_days: int = 10) -> None:
        self._values = {
            "desktop_roundtable_rounds": rounds,
            "desktop_history_days": history_days,
        }

    async def integer(self, key: str, default: int) -> int:
        return self._values.get(key, default)


class _Agents:
    def __init__(self, consultations: tuple[ConsultedReply, ...] = ()) -> None:
        self.requests: list[AgentExecutionRequest] = []
        self.consultations = consultations

    def stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        return self._stream(request)

    async def _stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        self.requests.append(request)
        reply = f"reply{len(self.requests)}"
        yield AgentExecutionEvent(name="delta", text=reply[:2])
        yield AgentExecutionEvent(
            name="complete",
            content=reply,
            consultations=self.consultations if len(self.requests) == 1 else (),
        )


class _Orchestration:
    def __init__(self, result: OrchestrationResult | None = None) -> None:
        self.result = result
        self.calls = 0

    async def try_start(self, **kwargs: object) -> OrchestrationResult | None:
        self.calls += 1
        return self.result


class _Archive:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.requests: list[ArchiveConversationRequest] = []

    async def archive(self, request: ArchiveConversationRequest) -> None:
        self.requests.append(request)
        if self.fails:
            raise RuntimeError("index unavailable")


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        value = self._now
        self._now += timedelta(microseconds=1)
        return value


class _Identifiers:
    def __init__(self) -> None:
        self._next = 100

    def new_id(self) -> uuid.UUID:
        self._next += 1
        return uuid.UUID(int=self._next)


def _application(
    *,
    store: _Store,
    assistants: _Assistants,
    agents: _Agents | None = None,
    orchestration: _Orchestration | None = None,
    archive: _Archive | None = None,
    now: datetime | None = None,
) -> AssistantConversationsApplication:
    return AssistantConversationsApplication(
        uow_factory=lambda: _UnitOfWork(store),
        assistants=assistants,
        configuration=_Configuration(),
        agents=agents or _Agents(),
        orchestration=orchestration or _Orchestration(),
        archive_port=archive or _Archive(),
        clock=_Clock(now or datetime(2026, 7, 23, tzinfo=UTC)),
        identifiers=_Identifiers(),
    )


async def test_roundtable_stream_owns_order_history_and_single_writes() -> None:
    principal = Principal(uuid.UUID(int=1), "爱丽丝")
    expert = Participant(uuid.UUID(int=12), "专家A")
    history = ConversationMessage(
        id=uuid.UUID(int=2),
        owner_user_id=principal.id,
        speaker_type=SPEAKER_USER,
        speaker_name=principal.display_name,
        content="之前的消息",
        create_time=datetime(2026, 7, 22, tzinfo=UTC),
    )
    store = _Store([history])
    assistants = _Assistants(principal.id, (expert,))
    agents = _Agents()
    application = _application(store=store, assistants=assistants, agents=agents)

    events = [
        event
        async for event in application.send_message_stream(
            SendMessageCommand(principal, "帮我分析", (expert.id,))
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
    assert events[0].data["speaker_type"] == "user"
    assert "之前的消息" in agents.requests[0].prompt
    assert "reply1" in agents.requests[1].prompt
    assert store.commits == 3
    assert [row.content for row in store.messages] == [
        "之前的消息",
        "帮我分析",
        "reply1",
        "reply2",
    ]


async def test_orchestration_preserves_payload_and_short_circuits_agent() -> None:
    principal = Principal(uuid.UUID(int=1), "爱丽丝")
    snapshot = {
        "total": 1,
        "accepted": 0,
        "steps": [
            {
                "step_no": 0,
                "title": "生成报告",
                "skill": "deliver",
                "status": "reported",
                "red_line": True,
            }
        ],
        "awaiting_human": True,
        "done": False,
    }
    store = _Store()
    assistants = _Assistants(principal.id)
    agents = _Agents()
    application = _application(
        store=store,
        assistants=assistants,
        agents=agents,
        orchestration=_Orchestration(OrchestrationResult(snapshot)),
    )

    events = [
        event
        async for event in application.send_message_stream(
            SendMessageCommand(principal, "请生成本周运营报告")
        )
    ]

    assert [event.name for event in events] == [
        "message_end",
        "orchestration",
        "message_end",
    ]
    assert events[1].data == snapshot
    assert "红线·待您验收" in events[2].data["content"]
    assert agents.requests == []
    assert store.commits == 2


async def test_consulted_reply_streams_and_persists_after_primary_reply() -> None:
    principal = Principal(uuid.UUID(int=1), "爱丽丝")
    expert = Participant(uuid.UUID(int=12), "专家A")
    consulted = ConsultedReply(uuid.UUID(int=13), "顾问B", "补充意见")
    store = _Store()
    agents = _Agents((consulted,))
    application = _application(
        store=store,
        assistants=_Assistants(principal.id, (expert,)),
        agents=agents,
    )

    events = [
        event
        async for event in application.send_message_stream(
            SendMessageCommand(principal, "帮我分析", (expert.id,))
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
        "message_start",
        "delta",
        "message_end",
    ]
    assert events[4].data == {
        "speaker_agent_id": str(consulted.participant_id),
        "speaker_name": consulted.participant_name,
    }
    assert events[5].data == {"text": consulted.content}
    assert [row.content for row in store.messages] == [
        "帮我分析",
        "reply1",
        consulted.content,
        "reply2",
    ]
    assert consulted.content in agents.requests[1].prompt
    assert store.commits == 4


@pytest.mark.parametrize("fails, expected_count", [(False, 0), (True, 1)])
async def test_archive_deletes_only_after_knowledge_success(
    fails: bool,
    expected_count: int,
) -> None:
    principal = Principal(uuid.UUID(int=1), "爱丽丝")
    old = ConversationMessage(
        id=uuid.UUID(int=3),
        owner_user_id=principal.id,
        speaker_type=SPEAKER_USER,
        speaker_name=principal.display_name,
        content="旧消息",
        create_time=datetime(2026, 7, 1, tzinfo=UTC),
    )
    store = _Store([old])
    archive = _Archive(fails=fails)
    application = _application(
        store=store,
        assistants=_Assistants(principal.id),
        archive=archive,
    )

    archived = await application.archive_old(principal, days=10)

    assert archived == (0 if fails else 1)
    assert len(store.messages) == expected_count
    assert store.commits == (0 if fails else 1)
    assert archive.requests[0].transcript == "爱丽丝：旧消息"


async def test_added_agent_limit_fails_before_persistence() -> None:
    principal = Principal(uuid.UUID(int=1), "爱丽丝")
    store = _Store()
    assistants = _Assistants(principal.id)
    application = _application(store=store, assistants=assistants)

    with pytest.raises(RuleViolation, match="最多再加入 2 个 AI"):
        async for _ in application.send_message_stream(
            SendMessageCommand(
                principal,
                "hi",
                (uuid.UUID(int=20), uuid.UUID(int=21), uuid.UUID(int=22)),
            )
        ):
            pass

    assert store.messages == []
    assert store.commits == 0
    assert assistants.get_calls == 0
