"""取数技能单测:指令解析、结果渲染、护栏拒绝转 note、门控（假取数服务，本地）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.contracts import ExecutionContext, SkillResult
from app.contexts.foundations.integration.governed_data_query.entrypoints import (
    agent_capability,
)
from app.models import Base
from app.models.agent import AgentRole
from app.models.deliverable import Deliverable
from app.services import config_service, data_query_service, deliver_service, query_skill


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="分析助理", prompt_template="x", tools=[])


# ── parse ───────────────────────────────────────────────
def test_parse_extracts_sql() -> None:
    out = "我来查一下：\n【取数】select ev from v_event_4\n然后分析"
    assert query_skill.parse(out) == ["select ev from v_event_4"]


def test_parse_truncates_to_two() -> None:
    out = "\n".join(f"【取数】select {i}" for i in range(5))
    assert len(query_skill.parse(out)) == 2


def test_parse_empty() -> None:
    assert query_skill.parse("普通回复无取数") == []


# ── render 表格（回喂 AI 的数据块）─────────────────────
def test_table_renders_rows() -> None:
    res = {"status": "ok", "columns": ["ev", "c"],
           "rows": [{"ev": "a", "c": 1}, {"ev": "b", "c": 2}],
           "row_count": 2, "truncated": False}
    md = query_skill._table(res)
    assert "| ev | c |" in md and "| a | 1 |" in md and "共 2 行" in md


def test_legacy_facade_exports_canonical_parser_and_bindings() -> None:
    assert query_skill.parse is agent_capability.parse
    assert query_skill._table is agent_capability.render_table
    assert query_skill.data_query_service is data_query_service
    assert query_skill.config_service is config_service
    assert issubclass(
        query_skill.DataQuerySkillExecutor,
        agent_capability.DataQuerySkillExecutor,
    )


# ── execute:闭环回喂 ────────────────────────────────────
async def test_execute_runs_and_interprets(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """执行取数 → 数据回喂 run_agent → 解读作为 consult_replies 追加消息。"""
    captured: dict[str, Any] = {}

    async def _fake_run(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        captured["sql"] = sql
        captured["source"] = kw.get("source")
        return {"status": "ok", "columns": ["c"], "rows": [{"c": 42}],
                "row_count": 1, "truncated": False}

    class _Rec:
        output_content = "整体活跃 42。\n| 指标 | 值 |\n| --- | --- |\n| DAU | 42 |"
        error_msg = None

    fed: dict[str, Any] = {}

    async def _fake_agent(_db: Any, agent: Any, **kw: Any) -> Any:
        fed["agent"] = agent
        fed["prompt"] = kw.get("user_message")
        fed["task_type"] = kw.get("task_type")
        return _Rec()

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _fake_run)
    monkeypatch.setattr(query_skill, "run_agent", _fake_agent)
    role = _role()
    res = await query_skill.execute(
        db, role, "【取数】select count(*) c from v_event_4", user_id=uuid.uuid4()
    )
    assert captured["sql"] == "select count(*) c from v_event_4"
    assert captured["source"] == "agent:分析助理"  # 审计来源带 AI 名
    assert "42" in fed["prompt"] and fed["task_type"] == "data_interpret"  # 数据回喂
    assert fed["agent"] is role  # 查询结果回喂同一 Agent
    assert res.notes == []  # 成功不再折原始表进 note
    assert len(res.consult_replies) == 1 and res.consult_replies[0][0] is role
    # 结构化载荷:取数产出进 datasets（阶段A 产出管道）
    assert len(res.datasets) == 1
    assert res.datasets[0]["row_count"] == 1 and res.datasets[0]["rows"] == [{"c": 42}]


async def test_execute_interpret_round_delivers(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阶段A 闭环:取数→解读轮 AI 写【交付】→ 文件真正生成、artifacts 有引用。"""

    async def _fake_run(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {"status": "ok", "columns": ["dau"], "rows": [{"dau": 42}],
                "row_count": 1, "truncated": False}

    class _Rec:
        # 解读轮产出里带交付指令，应被 _interpret 代为执行
        output_content = (
            "昨日 DAU 42，整体平稳。\n"
            "【交付】名称：运营日报；格式：xlsx\n```\n"
            "| 指标 | 值 |\n| --- | --- |\n| DAU | 42 |\n```"
        )
        error_msg = None

    async def _fake_agent(_db: Any, agent: Any, **kw: Any) -> Any:
        return _Rec()

    saved: dict[str, Any] = {}

    async def _fake_put(object_name: str, data: bytes, content_type: str) -> str:
        saved["name"] = object_name
        return f"bucket/{object_name}"

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _fake_run)
    monkeypatch.setattr(query_skill, "run_agent", _fake_agent)
    monkeypatch.setattr(deliver_service.storage, "put_object", _fake_put)
    uid = uuid.uuid4()
    res = await query_skill.execute(
        db, _role(), "【取数】select count(*) dau from v_event_4",
        user_id=uid, user_intent="把昨天运营数据生成日报放交付区",
    )
    # 解读轮的【交付】被执行:落库一行 + artifacts 有引用 + note 提示
    row = (await db.execute(select(Deliverable))).scalar_one()
    assert row.file_name == "运营日报.xlsx" and row.owner_user_id == uid
    assert len(res.artifacts) == 1 and res.artifacts[0]["file_name"] == "运营日报.xlsx"
    assert any("已交付" in n for n in res.notes)


async def test_execute_no_directive_fast_path(db: AsyncSession) -> None:
    res = await query_skill.execute(db, _role(), "无取数的普通回复", user_id=None)
    assert res.notes == [] and res.consult_replies == []


async def test_execute_rejected_becomes_note_no_interpret(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """护栏拒绝 → note 说明，不回喂 AI。"""
    async def _fake_run(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {"status": "rejected", "reason": "只允许 SELECT 查询"}

    agent_called = False

    async def _fake_agent(*a: Any, **k: Any) -> Any:
        nonlocal agent_called
        agent_called = True

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _fake_run)
    monkeypatch.setattr(query_skill, "run_agent", _fake_agent)
    res = await query_skill.execute(db, _role(), "【取数】DROP TABLE v_event_4", user_id=None)
    assert len(res.notes) == 1 and "被拒" in res.notes[0]
    assert res.consult_replies == [] and agent_called is False


async def test_execute_failure_becomes_note_no_interpret(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_run(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {"status": "fail", "msg": "connector unavailable"}

    agent_called = False

    async def _fake_agent(*args: Any, **kwargs: Any) -> Any:
        nonlocal agent_called
        agent_called = True

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _fake_run)
    monkeypatch.setattr(query_skill, "run_agent", _fake_agent)
    result = await query_skill.execute(
        db,
        _role(),
        "【取数】select count(*) from v_event_4",
    )
    assert len(result.notes) == 1 and "取数失败" in result.notes[0]
    assert result.consult_replies == [] and agent_called is False


async def test_interpret_round_excludes_only_recursive_data_query(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_run(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "columns": ["dau"],
            "rows": [{"dau": 42}],
            "row_count": 1,
            "truncated": False,
        }

    class _Record:
        output_content = (
            "昨日 DAU 为 42。\n"
            "【交付】名称：运营日报；格式：xlsx\n"
            "【发起协作】目标部门：运营部；类别：analysis；内容：复核数据"
        )

    async def _fake_agent(*args: Any, **kwargs: Any) -> _Record:
        return _Record()

    captured: dict[str, Any] = {}

    class _Dispatcher:
        async def dispatch(
            self,
            session: AsyncSession,
            role: AgentRole,
            request: Any,
            context: ExecutionContext,
        ) -> SkillResult:
            return await query_skill.DataQuerySkillExecutor().execute(
                session, role, request, context
            )

        async def dispatch_text(
            self,
            _session: AsyncSession,
            _role: AgentRole,
            output: str,
            _context: ExecutionContext,
            *,
            exclude: set[str] | None = None,
        ) -> SkillResult:
            captured["output"] = output
            captured["exclude"] = exclude
            return SkillResult(
                artifacts=[
                    {"file_name": "运营日报.xlsx"},
                    {"collab_request_id": "request-id"},
                ]
            )

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _fake_run)
    monkeypatch.setattr(query_skill, "run_agent", _fake_agent)
    context = ExecutionContext(dispatcher=_Dispatcher())
    result = await query_skill.execute(
        db,
        _role(),
        "【取数】select dau from v_event_4",
        execution_context=context,
    )
    assert captured["exclude"] == {"data_query"}
    assert "【交付】" in captured["output"] and "【发起协作】" in captured["output"]
    assert len(result.artifacts) == 2


async def test_execute_disabled_flag(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全局急停关 → 不执行。"""
    async def _off(_db: Any, key: str, default: Any) -> Any:
        return False if key == "agent_data_query" else default

    monkeypatch.setattr(query_skill.config_service, "resolve", _off)
    called = False

    async def _run(*a: Any, **k: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(query_skill.data_query_service, "run_readonly_sql", _run)
    res = await query_skill.execute(db, _role(), "【取数】select 1 from v_event_4", user_id=None)
    assert res.notes == [] and called is False
