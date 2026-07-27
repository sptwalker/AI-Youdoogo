"""F4a 审计+配置基座单测：audit/_mask + config_service + 提示词分层 + scheduler 守卫。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, scheduler
from app.contexts.foundations.model_gateway import public as _mg_public
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole
from app.models.sys_config import SysConfig
from app.models.task import TaskCard
from app.services import audit_service, config_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---- audit_service ----

def test_mask_redacts_secrets() -> None:
    out = audit_service._mask({"api_key": "sk-x", "note": "ok", "PASSWORD": "p"})
    assert out == {"api_key": "***", "note": "ok", "PASSWORD": "***"}


def test_mask_redacts_nested_secrets() -> None:
    """嵌套 dict 里的密钥也打码（防审计 detail 泄露）。"""
    out = audit_service._mask({"config": {"api_key": "sk-x", "host": "h"}, "n": 1})
    assert out == {"config": {"api_key": "***", "host": "h"}, "n": 1}


async def test_audit_inserts_row(db: AsyncSession) -> None:
    await audit_service.audit(
        db, actor_id=uuid.uuid4(), actor_role="admin", action="task.accept",
        summary="验收", target_type="task_card", target_id=uuid.uuid4(),
        detail={"secret": "abc"},
    )
    logs = await audit_service.list_audit_logs(db)
    assert len(logs) == 1 and logs[0]["action"] == "task.accept"
    assert logs[0]["detail"]["secret"] == "***"  # 落库前打码


async def test_audit_retries_then_logs_error(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """审计写失败 → 重试一次仍失败 → 记 ERROR，但不抛（不阻断主链，H2.3）。"""
    calls = {"commit": 0}

    async def _boom() -> None:
        calls["commit"] += 1
        raise RuntimeError("db down")

    async def _noop() -> None:
        return None

    monkeypatch.setattr(db, "commit", _boom)
    monkeypatch.setattr(db, "rollback", _noop)
    errors: list[str] = []
    monkeypatch.setattr(
        audit_service.logger, "error",
        lambda *a, **k: errors.append(str(a[0]) if a else ""),
    )
    # 不抛异常（吞掉），但重试了 2 次并记 error
    await audit_service.audit(
        db, actor_id=uuid.uuid4(), actor_role="admin", action="x", summary="s",
    )
    assert calls["commit"] == 2 and len(errors) == 1


# ---- config_service ----

async def test_config_resolve_and_set(db: AsyncSession) -> None:
    # 无 DB 值 → 取 default
    assert await config_service.resolve(db, "x", "fallback") == "fallback"
    # 种子一行 editable 配置
    db.add(SysConfig(key="x", value="dbval", value_type="string", category="feature"))
    await db.commit()
    assert await config_service.resolve(db, "x", "fallback") == "dbval"
    # set_config 改值 + 落一条 config.update 审计
    admin = uuid.uuid4()
    await config_service.set_config(db, "x", "new", updated_by=admin, actor_role="admin")
    assert await config_service.resolve(db, "x") == "new"
    logs = await audit_service.list_audit_logs(db, action="config.update")
    assert len(logs) == 1


async def test_set_config_rejects_non_editable(db: AsyncSession) -> None:
    db.add(SysConfig(key="locked", value=1, value_type="int", is_editable=False))
    await db.commit()
    with pytest.raises(ApplicationError, match="不可编辑"):
        await config_service.set_config(db, "locked", 2, updated_by=None, actor_role="admin")


# ---- 提示词分层注入 ----

async def test_run_agent_prepends_global_prompt(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _CaptureLLM:
        async def ainvoke(self, messages: list, **kwargs: Any) -> AIMessage:
            captured["messages"] = messages
            return AIMessage(content="ok", response_metadata={"model_name": "fake"})

    monkeypatch.setattr(_mg_public, "get_llm_for_role", lambda *a, **k: _CaptureLLM())
    role = AgentRole(name="顾问", prompt_template="你是顾问。", model_role="daily")
    db.add(role)
    await db.commit()
    await db.refresh(role)

    await base.run_agent(
        db, role, task_type="t", input_summary="s", user_message="hi"
    )
    sys_msg = captured["messages"][0]
    assert isinstance(sys_msg, SystemMessage)
    # 全局红线前缀 + 角色特有段都在
    assert "公司红线" in sys_msg.content and "你是顾问。" in sys_msg.content


# ---- scheduler assignee_type 守卫 ----

async def test_scheduler_skips_user_task(db: AsyncSession) -> None:
    task = TaskCard(
        title="派真人", task_type="manual", creator_id=uuid.uuid4(), assignee_type="user"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    with pytest.raises(ApplicationError, match="真人受理"):
        await scheduler.run_task(db, task.id)
