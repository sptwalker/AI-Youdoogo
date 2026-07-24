"""智能体协作原语单测（docs/13 §10，内存 SQLite，不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.contracts import ExecutionContext, SkillRequest
from app.agents.tool_dispatcher import ToolDispatcher
from app.contexts.business.collaboration_requests.entrypoints import (
    agent_capability as collaboration_capability,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints import (
    agent_capability,
)
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.collab import CollabRequest
from app.models.system import COMPANY, DEPT_L1, SysDepartment
from app.services import collab_protocol as proto

CONSULT = "先分析一下。\n【咨询 @财务总监】Q3预算上限是多少？\n以上仅供参考。"
COLLAB = "【发起协作】目标部门：平台运营部；类别：analysis；内容：请分析近7日DAU异动"


# ── parse ──────────────────────────────────────────────
def test_parse_consult_and_collab() -> None:
    d = proto.parse(CONSULT + "\n" + COLLAB)
    assert d.consults == [("财务总监", "Q3预算上限是多少？")]
    assert d.collabs == [("平台运营部", "analysis", "请分析近7日DAU异动")]


def test_parse_halfwidth_punctuation() -> None:
    d = proto.parse("【发起协作】目标部门:运营;类别:report;内容:周报汇总")
    assert d.collabs == [("运营", "report", "周报汇总")]


def test_parse_malformed_and_empty() -> None:
    assert proto.parse("【咨询 财务总监】没有@符号").consults == []
    assert proto.parse("【发起协作】目标部门：运营；内容：缺类别段").collabs == []
    assert proto.parse("普通回复，无指令") == proto.ParsedDirectives()
    assert proto.parse("") == proto.ParsedDirectives()


def test_parse_caps_at_two() -> None:
    text = "\n".join(f"【咨询 @AI{i}】问题{i}" for i in range(4))
    assert len(proto.parse(text).consults) == 2


def test_legacy_facade_exports_canonical_capability() -> None:
    assert proto.parse is collaboration_capability.parse
    assert proto.fold_notes is collaboration_capability.fold_notes
    assert proto.PROMPT_SECTION is collaboration_capability.PROMPT_SECTION
    assert issubclass(
        proto.CollabSkillExecutor,
        collaboration_capability.CollabSkillExecutor,
    )
    assert proto.CollabSkillExecutor is not collaboration_capability.CollabSkillExecutor


# ── execute ────────────────────────────────────────────
@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _agent(db: AsyncSession, name: str, **kw: Any) -> AgentRole:
    a = AgentRole(name=name, prompt_template="x", model_role="daily", **kw)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


def _stub_run_agent(calls: list[dict[str, Any]]):
    async def _run(db: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        calls.append({"role": role.name, **kw})
        return AgentTaskRecord(
            id=uuid.uuid4(), agent_role_id=role.id, task_type=kw.get("task_type", "t"),
            output_content=f"{role.name}的答复", status="success",
        )

    return _run


async def test_execute_consult(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """咨询命中：run_agent 恰 1 次，user_message 含问题与发起者名，答复带回。"""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(proto, "run_agent", _stub_run_agent(calls))
    initiator = await _agent(db, "运营总监")
    await _agent(db, "财务总监")

    r = await proto.execute(db, initiator, CONSULT)
    assert len(calls) == 1 and calls[0]["role"] == "财务总监"
    assert "Q3预算上限" in calls[0]["user_message"] and "运营总监" in calls[0]["user_message"]
    assert len(r.consult_replies) == 1
    assert r.consult_replies[0][1].output_content == "财务总监的答复"


async def test_execute_consult_guards(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """未知 AI / 私人助理 / 咨询自己 → note 且不调 run_agent。"""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(proto, "run_agent", _stub_run_agent(calls))
    initiator = await _agent(db, "运营总监")
    await _agent(db, "某人的助理", owner_user_id=uuid.uuid4())

    r = await proto.execute(
        db, initiator,
        "【咨询 @不存在的AI】q\n【咨询 @某人的助理】q",
    )
    assert calls == []
    assert len(r.notes) == 2
    assert "不存在" in r.notes[0] and "私人助理" in r.notes[1]

    r2 = await proto.execute(db, initiator, "【咨询 @运营总监】问自己")
    assert calls == [] and "不能咨询自己" in r2.notes[0]


async def test_execute_consult_runs_consulted_query(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """咨询链修 bug：被咨询 AI 在答复里写【取数】时应代为执行（不再静默断链），
    但禁止其再发起二次咨询（保持深度硬限 1 跳）。"""
    initiator = await _agent(db, "运营总监")
    consultant = await _agent(db, "首席运营顾问")
    finance = await _agent(db, "财务总监")

    # 被咨询者答复里带取数；其取数解读再次咨询，也必须继承 exclude=collab。
    async def _run(_db: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        task_type = kw.get("task_type", "t")
        if role.id == consultant.id and task_type == "agent_consult":
            out = "我去查一下。\n【取数】select count(*) c from v_event_4"
        elif role.id == consultant.id and task_type == "data_interpret":
            out = "盒子累计 1000 个。\n【咨询 @财务总监】顺带问下预算"
        else:
            out = "预算答复"
        return AgentTaskRecord(
            id=uuid.uuid4(), agent_role_id=role.id, task_type=task_type,
            output_content=out, status="success",
        )

    executed: dict[str, Any] = {}

    async def _fake_sql(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        executed["sql"] = sql
        return {"status": "ok", "columns": ["c"], "rows": [{"c": 1000}],
                "row_count": 1, "truncated": False}

    monkeypatch.setattr(proto, "run_agent", _run)
    monkeypatch.setattr(agent_capability, "run_readonly_sql", _fake_sql)

    r = await proto.execute(
        db,
        initiator,
        "【咨询 @首席运营顾问】盒子累计数量是多少",
        execution_context=ExecutionContext(
            agent_runner=_run,
            dispatcher=ToolDispatcher(),
        ),
    )
    # 被咨询者的取数被执行了（不再断链）
    assert executed.get("sql") == "select count(*) c from v_event_4"
    assert len(r.datasets) == 1 and r.datasets[0]["rows"] == [{"c": 1000}]
    # Query 解读轮仍继承单跳限制，不会再次运行财务总监。
    assert not any(rec[0].id == finance.id for rec in r.consult_replies)


async def test_legacy_consult_fallback_runs_query_without_dispatcher(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    initiator = await _agent(db, "运营总监")
    consultant = await _agent(db, "首席运营顾问")

    async def _run(_db: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        task_type = kw.get("task_type", "t")
        if task_type == "agent_consult":
            output = "【取数】select count(*) c from v_event_4"
        else:
            output = (
                "累计 1000 个。\n"
                "【交付】名称：盒子累计；格式：csv\n"
                "```\n| 指标 | 数值 |\n| --- | --- |\n| 累计 | 1000 |\n```"
            )
        return AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type=task_type,
            output_content=output,
            status="success",
        )

    async def _fake_sql(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "columns": ["c"],
            "rows": [{"c": 1000}],
            "row_count": 1,
            "truncated": False,
        }

    monkeypatch.setattr(proto, "run_agent", _run)
    monkeypatch.setattr(proto.data_query_service, "run_readonly_sql", _fake_sql)
    uploads: list[str] = []

    async def _put(object_name: str, data: bytes, content_type: str) -> str:
        uploads.append(object_name)
        return f"bucket/{object_name}"

    monkeypatch.setattr(
        "app.platform.object_storage.gateway.put_object",
        _put,
    )
    result = await proto.execute(
        db,
        initiator,
        "【咨询 @首席运营顾问】盒子累计数量是多少",
        user_id=uuid.uuid4(),
    )
    assert result.consult_replies[0][0].id == consultant.id
    assert result.datasets[0]["rows"] == [{"c": 1000}]
    assert result.artifacts[0]["file_name"] == "盒子累计.csv"
    assert len(uploads) == 1


async def test_direct_typed_consult_composes_query_interpretation_and_delivery(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    initiator = await _agent(db, "运营总监")
    consultant = await _agent(db, "首席运营顾问")

    async def _run(_db: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        task_type = kw.get("task_type", "t")
        output = (
            "【取数】select count(*) c from v_event_4"
            if task_type == "agent_consult"
            else (
                "累计 1000 个。\n"
                "【交付】名称：typed累计；格式：csv\n"
                "```\n| 指标 | 数值 |\n| --- | --- |\n| 累计 | 1000 |\n```"
            )
        )
        return AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type=task_type,
            output_content=output,
            status="success",
        )

    async def _fake_sql(_db: Any, sql: str, **kw: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "columns": ["c"],
            "rows": [{"c": 1000}],
            "row_count": 1,
            "truncated": False,
        }

    async def _put(object_name: str, data: bytes, content_type: str) -> str:
        return f"bucket/{object_name}"

    monkeypatch.setattr(agent_capability, "run_readonly_sql", _fake_sql)
    monkeypatch.setattr("app.platform.object_storage.gateway.put_object", _put)
    result = await ToolDispatcher().dispatch(
        db,
        initiator,
        SkillRequest(
            skill_key="collab",
            action_index=0,
            arguments={
                "kind": "consult",
                "name": consultant.name,
                "question": "盒子累计数量是多少",
            },
        ),
        ExecutionContext(
            user_id=uuid.uuid4(),
            agent_runner=_run,
        ),
    )
    assert result.datasets[0]["rows"] == [{"c": 1000}]
    assert result.artifacts[0]["file_name"] == "typed累计.csv"
    assert len(result.consult_replies) == 2


async def test_execute_collab(db: AsyncSession) -> None:
    """协作命中：CollabRequest 落库，title 折叠发起者、risk 自动分级、来源部门正确。"""
    root = SysDepartment(name="公司", code="c", node_type=COMPANY, level=0, path="")
    dept = SysDepartment(name="平台运营部", code="ops", node_type=DEPT_L1, level=1, path="")
    src = SysDepartment(name="财务部", code="fin", node_type=DEPT_L1, level=1, path="")
    db.add_all([root, dept, src])
    await db.commit()
    initiator = await _agent(db, "财务总监", department_id=src.id)

    r = await proto.execute(
        db, initiator, "【发起协作】目标部门：平台运营部；类别：finance；内容：核对Q3预算执行"
    )
    assert any("已提交协作请求" in n for n in r.notes)
    req = (await db.execute(select(CollabRequest))).scalar_one()
    assert req.title == "[财务总监] 核对Q3预算执行"
    assert req.requested_by == initiator.id
    assert req.source_department_id == src.id
    assert req.target_department_id == dept.id
    assert req.risk_level == "high"  # finance 红线类别自动分级


async def test_legacy_request_creator_monkeypatch_is_preserved(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    department = SysDepartment(
        name="平台运营部",
        code="ops-seam",
        node_type=DEPT_L1,
        level=1,
        path="",
    )
    db.add(department)
    await db.commit()
    initiator = await _agent(db, "财务总监")
    captured: dict[str, Any] = {}
    request_id = uuid.uuid4()

    async def _fake_create(_db: AsyncSession, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(id=request_id)

    monkeypatch.setattr(proto.collab_service, "create_request", _fake_create)
    result = await proto.execute(db, initiator, COLLAB)
    assert captured["target_department_id"] == department.id
    assert result.artifacts == [
        {
            "collab_request_id": str(request_id),
            "title": "[财务总监] 请分析近7日DAU异动",
        }
    ]


async def test_legacy_executor_resolves_monkeypatch_seams_after_construction(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    department = SysDepartment(
        name="平台运营部",
        code="ops-direct-seam",
        node_type=DEPT_L1,
        level=1,
        path="",
    )
    db.add(department)
    await db.commit()
    initiator = await _agent(db, "财务总监")
    consultant = await _agent(db, "预算顾问")
    executor = proto.CollabSkillExecutor()
    runner_calls: list[str] = []

    async def _run(_db: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        runner_calls.append(role.name)
        return AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type="agent_consult",
            output_content="预算答复",
            status="success",
        )

    created: list[dict[str, Any]] = []

    async def _create(_db: AsyncSession, **kwargs: Any) -> Any:
        created.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(proto, "run_agent", _run)
    monkeypatch.setattr(proto.collab_service, "create_request", _create)
    consult_result = await executor.execute(
        db,
        initiator,
        SkillRequest(
            skill_key="collab",
            action_index=0,
            arguments={
                "kind": "consult",
                "name": consultant.name,
                "question": "预算是多少",
            },
        ),
        ExecutionContext(),
    )
    request_result = await executor.execute(
        db,
        initiator,
        SkillRequest(
            skill_key="collab",
            action_index=1,
            arguments={
                "kind": "request",
                "department": department.name,
                "category": "analysis",
                "content": "复核预算",
            },
        ),
        ExecutionContext(idempotency_prefix="legacy-direct"),
    )
    assert runner_calls == [consultant.name]
    assert len(consult_result.consult_replies) == 1
    assert created[0]["idempotency_key"] == "legacy-direct:collab:1"
    assert len(request_result.artifacts) == 1


async def test_execute_collab_dept_guards(db: AsyncSession) -> None:
    """部门不存在 / 同名歧义 → note 且不落请求。"""
    d1 = SysDepartment(name="运营", code="a", node_type=DEPT_L1, level=1, path="")
    d2 = SysDepartment(name="运营", code="b", node_type=DEPT_L1, level=1, path="")
    db.add_all([d1, d2])
    await db.commit()
    initiator = await _agent(db, "总监")

    r = await proto.execute(
        db, initiator,
        "【发起协作】目标部门：不存在部；类别：a；内容：x\n"
        "【发起协作】目标部门：运营；类别：a；内容：y",
    )
    assert len(r.notes) == 2 and all("未提交" in n for n in r.notes)
    n = (await db.execute(select(func.count()).select_from(CollabRequest))).scalar_one()
    assert n == 0


async def test_execute_disabled_by_flag(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关关 → 空结果、不执行。"""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(proto, "run_agent", _stub_run_agent(calls))

    async def _off(_db: AsyncSession, key: str, default: Any) -> Any:
        return False if key == "agent_collab_protocol" else default

    monkeypatch.setattr(proto.config_service, "resolve", _off)
    initiator = await _agent(db, "运营总监")
    await _agent(db, "财务总监")
    r = await proto.execute(db, initiator, CONSULT)
    assert calls == [] and r.notes == [] and r.consult_replies == []


async def test_execute_never_raises(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """单条指令执行异常 → 转 note，不上抛。"""

    async def _boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("llm down")

    monkeypatch.setattr(proto, "run_agent", _boom)
    initiator = await _agent(db, "运营总监")
    await _agent(db, "财务总监")
    r = await proto.execute(db, initiator, CONSULT)
    assert any("执行失败" in n for n in r.notes)


def test_fold_notes() -> None:
    r = proto.ProtocolResult(notes=["已提交"])
    assert proto.fold_notes("正文", r) == "正文\n\n> 系统：已提交"
    assert proto.fold_notes("正文", proto.ProtocolResult()) == "正文"
