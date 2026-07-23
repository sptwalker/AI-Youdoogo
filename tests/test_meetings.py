"""会议会商全流程单测（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base
from app.agents.contracts import SkillResult
from app.contexts.business.meeting_management.domain.models import parse_vote_choice
from app.contexts.business.meeting_management.entrypoints import operations
from app.contexts.business.meeting_management.infrastructure import adapters as meeting_adapters
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.meeting import (
    CLOSED,
    IN_PROGRESS,
    MeetingDiscuss,
    MeetingInfo,
    MeetingResolution,
)
from app.models.system import SysUser


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content=self._text)

    async def astream(self, messages: list, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        # 逐字吐（验证 delta 逐段送达）
        for ch in self._text:
            yield AIMessageChunk(content=ch)


async def _ai_speak(session: AsyncSession, meeting_id: uuid.UUID, topic: str) -> dict:
    """drain ai_expert_speak_stream，返回 message_end 落库消息。"""
    events = [e async for e in operations.ai_expert_speak_stream(session, meeting_id, topic=topic)]
    names = [n for n, _ in events]
    assert names[0] == "message_start" and names[-1] == "message_end"
    assert names.count("delta") > 1  # 确实逐段流出
    return events[-1][1]


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="ceo", password_hash="x", real_name="老板", role_code="executive")
        expert = AgentRole(
            name=meeting_adapters.EXPERT_NAME,
            prompt_template="你是会商AI专家。",
            model_role="reasoning",
        )
        session.add_all([user, expert])
        await session.commit()
        yield session, user.id
    await engine.dispose()


async def _open_meeting(session: AsyncSession, uid: uuid.UUID):
    m = await operations.create_meeting(session, title="Q3 决策会", creator_id=uid)
    return await operations.set_status(session, m.id, IN_PROGRESS)


def _human_principal(user_id: uuid.UUID) -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        principal_id=user_id,
        role_code="executive",
        department_id=None,
    )


async def test_full_meeting_flow(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    session, uid = ctx
    monkeypatch.setattr(
        base, "get_llm_for_role", lambda *a, **k: _FakeLLM("approve\n方案可行，收益明确。")
    )
    m = await _open_meeting(session, uid)

    await operations.add_discussion(
        session, m.id, speaker_id=uid, speaker_name="老板", content="我倾向上线会员体系。"
    )
    ai_d = await _ai_speak(session, m.id, "是否上线会员体系")
    assert ai_d["speaker_type"] == "ai" and "可行" in ai_d["content"]

    await operations.cast_vote(
        session, m.id, subject="会员体系", voter_type="human", voter_id=uid, choice="approve"
    )
    ai_v = await operations.ai_expert_vote(session, m.id, subject="会员体系")
    assert ai_v.voter_type == "ai" and ai_v.choice == "approve"

    tally = await operations.tally_votes(session, m.id, "会员体系")
    assert tally["human"]["approve"] == 1 and tally["ai"]["approve"] == 1
    assert tally["human_passed"] is True

    m2 = await operations.generate_minutes(session, m.id)
    assert m2.summary and "可行" in m2.summary

    r = await operations.create_resolution(session, m.id, content="批准上线会员体系")
    assert r.is_confirmed is False


async def test_resolution_requires_human_confirm(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    """红线：未确认决议不能转任务卡；确认后可转。"""
    session, uid = ctx
    m = await _open_meeting(session, uid)
    r = await operations.create_resolution(session, m.id, content="决议X")

    with pytest.raises(ApplicationError, match="真人确认"):
        await operations.resolution_to_task(session, r.id, creator_id=uid)

    confirmed = await operations.confirm_resolution(
        session,
        r.id,
        principal=_human_principal(uid),
    )
    assert confirmed.is_confirmed is True and confirmed.confirmed_by == uid

    task = await operations.resolution_to_task(session, r.id, creator_id=uid)
    assert task.task_type == "resolution_execution"
    with pytest.raises(ApplicationError, match="已转过"):
        await operations.resolution_to_task(session, r.id, creator_id=uid)


async def test_discuss_requires_in_progress(ctx) -> None:
    session, uid = ctx
    m = await operations.create_meeting(session, title="M", creator_id=uid)  # scheduled
    with pytest.raises(ApplicationError, match="需先开始"):
        await operations.add_discussion(
            session, m.id, speaker_id=uid, speaker_name="x", content="hi"
        )


async def test_illegal_status_transition(ctx) -> None:
    session, uid = ctx
    m = await _open_meeting(session, uid)
    await operations.set_status(session, m.id, CLOSED)
    with pytest.raises(ApplicationError, match="非法会议状态流转"):
        await operations.set_status(session, m.id, IN_PROGRESS)


async def test_minutes_needs_discussion(ctx) -> None:
    session, uid = ctx
    m = await _open_meeting(session, uid)
    with pytest.raises(ApplicationError, match="无发言"):
        await operations.generate_minutes(session, m.id)


async def test_crud_list_order_soft_delete_and_participants_are_preserved(ctx) -> None:
    session, uid = ctx
    participants = [
        {
            "type": "human",
            "id": str(uid),
            "name": "老板",
            "metadata": {"observer": False, "tags": ["决策", {"level": 2}]},
        }
    ]
    older = await operations.create_meeting(
        session,
        title="旧会议",
        creator_id=uid,
        participants=participants,
    )
    newer = await operations.create_meeting(
        session,
        title="新会议",
        creator_id=uid,
    )
    older_row = await session.get(MeetingInfo, older.id)
    newer_row = await session.get(MeetingInfo, newer.id)
    assert older_row is not None and newer_row is not None
    older_row.create_time = datetime.now(UTC) - timedelta(days=1)
    newer_row.create_time = datetime.now(UTC)
    await session.commit()

    loaded = await operations.get_meeting(session, older.id)
    assert loaded.participants == participants
    assert [item.id for item in await operations.list_meetings(session)] == [
        newer.id,
        older.id,
    ]

    newer_row.is_delete = True
    await session.commit()
    assert [item.id for item in await operations.list_meetings(session)] == [older.id]
    with pytest.raises(ApplicationError, match="会议不存在"):
        await operations.get_meeting(session, newer.id)


async def test_discussions_and_resolutions_are_returned_oldest_first(ctx) -> None:
    session, uid = ctx
    meeting = await _open_meeting(session, uid)
    first = await operations.add_discussion(
        session,
        meeting.id,
        speaker_id=uid,
        speaker_name="甲",
        content="先发言",
    )
    second = await operations.add_discussion(
        session,
        meeting.id,
        speaker_id=uid,
        speaker_name="乙",
        content="后发言",
    )
    first_row = await session.get(MeetingDiscuss, first.id)
    second_row = await session.get(MeetingDiscuss, second.id)
    assert first_row is not None and second_row is not None
    first_row.create_time = datetime.now(UTC) - timedelta(minutes=2)
    second_row.create_time = datetime.now(UTC) - timedelta(minutes=1)
    resolution_first = await operations.create_resolution(session, meeting.id, content="先决议")
    resolution_second = await operations.create_resolution(session, meeting.id, content="后决议")
    resolution_first_row = await session.get(MeetingResolution, resolution_first.id)
    resolution_second_row = await session.get(MeetingResolution, resolution_second.id)
    assert resolution_first_row is not None and resolution_second_row is not None
    resolution_first_row.create_time = datetime.now(UTC) - timedelta(minutes=2)
    resolution_second_row.create_time = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()

    assert [item.id for item in await operations.list_discussions(session, meeting.id)] == [
        first.id,
        second.id,
    ]
    assert [item.id for item in await operations.list_resolutions(session, meeting.id)] == [
        resolution_first.id,
        resolution_second.id,
    ]


async def test_ai_consultant_reply_keeps_sse_shape_and_persists_each_message(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, uid = ctx
    meeting = await _open_meeting(session, uid)
    consultant = AgentRole(
        name="风险顾问",
        prompt_template="识别风险。",
        model_role="reasoning",
    )
    session.add(consultant)
    await session.commit()
    consult_record = AgentTaskRecord(
        agent_role_id=consultant.id,
        task_type="consult",
        input_summary="风险复核",
        output_content="顾问补充意见",
        status="success",
    )

    async def fake_execute_all(*args: object, **kwargs: object) -> SkillResult:
        return SkillResult(consult_replies=[(consultant, consult_record)])

    monkeypatch.setattr(
        base,
        "get_llm_for_role",
        lambda *a, **k: _FakeLLM("主专家意见"),
    )
    monkeypatch.setattr(meeting_adapters, "execute_all", fake_execute_all)

    events = [
        event
        async for event in operations.ai_expert_speak_stream(session, meeting.id, topic="是否推进")
    ]
    assert [name for name, _ in events].count("message_start") == 2
    assert [name for name, _ in events].count("message_end") == 2
    endings = [data for name, data in events if name == "message_end"]
    assert [item["speaker_name"] for item in endings] == [
        meeting_adapters.EXPERT_NAME,
        "风险顾问",
    ]
    expected_keys = {"id", "speaker_type", "speaker_name", "content", "create_time"}
    assert all(expected_keys <= item.keys() for item in endings)
    discussions = await operations.list_discussions(session, meeting.id)
    assert [item.content for item in discussions] == ["主专家意见", "顾问补充意见"]


async def test_task_conversion_failure_does_not_mark_resolution_converted(
    ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, uid = ctx
    meeting = await _open_meeting(session, uid)
    resolution = await operations.create_resolution(session, meeting.id, content="决议X")
    await operations.confirm_resolution(
        session,
        resolution.id,
        principal=_human_principal(uid),
    )
    resolution_id = resolution.id

    async def fail_create_task(*args: object, **kwargs: object) -> None:
        raise RuntimeError("task creation failed")

    monkeypatch.setattr(meeting_adapters.task_service, "create_task", fail_create_task)
    with pytest.raises(RuntimeError, match="task creation failed"):
        await operations.resolution_to_task(session, resolution.id, creator_id=uid)

    session.expire_all()
    stored = await session.scalar(
        select(MeetingResolution).where(MeetingResolution.id == resolution_id)
    )
    assert stored is not None and stored.converted_task_id is None


async def test_hidden_meeting_detail_uses_not_found_semantics(ctx) -> None:
    session, uid = ctx
    meeting = await operations.create_meeting(
        session,
        title="仅创建人可见",
        creator_id=uid,
    )
    outsider = Principal(
        principal_type=PrincipalType.USER,
        principal_id=uuid.uuid4(),
        role_code="member",
        department_id=uuid.uuid4(),
    )

    with pytest.raises(ApplicationError, match="资源不存在"):
        await operations.get_meeting_detail(
            session,
            meeting.id,
            principal=outsider,
        )


def test_parse_choice_rejects_negation() -> None:
    """AI 参考票解析：首行开头匹配，否定句不误判（红线：AI票仅参考也不能反向）。"""
    p = parse_vote_choice
    assert p("approve\n方案可行") == "approve"
    assert p("**reject** 风险高") == "reject"
    assert p("我不建议 approve，风险太大") == "abstain"  # 否定句不再误判为 approve
    assert p("") == "abstain"
