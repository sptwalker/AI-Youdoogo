"""F4a 审计+配置基座单测：audit/_mask + config_service + 提示词分层 + scheduler 守卫。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.execution.agent_execution.entrypoints import (
    operations as agent_execution,
)
from app.contexts.foundations.governance.audit_trail import public as audit_trail
from app.contexts.foundations.governance.audit_trail.domain.redaction import mask_secrets
from app.contexts.foundations.governance.system_configuration import (
    public as system_configuration,
)
from app.contexts.foundations.model_gateway import public as model_gateway
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole
from app.models.sys_config import SysConfig


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
    out = mask_secrets({"api_key": "sk-x", "note": "ok", "PASSWORD": "p"})
    assert out == {"api_key": "***", "note": "ok", "PASSWORD": "***"}


def test_mask_redacts_nested_secrets() -> None:
    """嵌套 dict 里的密钥也打码（防审计 detail 泄露）。"""
    out = mask_secrets({"config": {"api_key": "sk-x", "host": "h"}, "n": 1})
    assert out == {"config": {"api_key": "***", "host": "h"}, "n": 1}


async def test_audit_inserts_row(db: AsyncSession) -> None:
    await audit_trail.append_audit_record(
        db,
        audit_trail.AppendAuditRecordCommand(
            actor_id=uuid.uuid4(),
            actor_role="admin",
            action="task.accept",
            summary="验收",
            target_type="task_card",
            target_id=uuid.uuid4(),
            detail={"secret": "abc"},
        ),
    )
    logs = await audit_trail.query_audit_trail(
        db,
        audit_trail.AuditTrailQuery(limit=100),
    )
    assert len(logs) == 1 and logs[0].action == "task.accept"
    assert logs[0].detail == {"secret": "***"}  # 落库前打码


# ---- config_service ----


async def test_config_resolve_and_set(db: AsyncSession) -> None:
    # 无 DB 值 → 取 default
    assert await system_configuration.resolve_configuration(db, "x", "fallback") == "fallback"
    # 种子一行 editable 配置
    db.add(SysConfig(key="x", value="dbval", value_type="string", category="feature"))
    await db.commit()
    assert await system_configuration.resolve_configuration(db, "x", "fallback") == "dbval"
    # set_config 改值 + 落一条 config.update 审计
    admin = uuid.uuid4()
    await system_configuration.update_configuration(
        db,
        system_configuration.UpdateConfigCommand(
            key="x", value="new", updated_by=admin, actor_role="admin"
        ),
    )
    assert await system_configuration.resolve_configuration(db, "x") == "new"
    logs = await audit_trail.query_audit_trail(
        db,
        audit_trail.AuditTrailQuery(action="config.update"),
    )
    assert len(logs) == 1


async def test_set_config_rejects_non_editable(db: AsyncSession) -> None:
    db.add(SysConfig(key="locked", value=1, value_type="int", is_editable=False))
    await db.commit()
    with pytest.raises(ApplicationError, match="不可编辑"):
        await system_configuration.update_configuration(
            db,
            system_configuration.UpdateConfigCommand(
                key="locked", value=2, updated_by=None, actor_role="admin"
            ),
        )


# ---- 提示词分层注入 ----


async def test_run_agent_prepends_global_prompt(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _CaptureLLM:
        async def ainvoke(self, messages: list, **kwargs: Any) -> AIMessage:
            captured["messages"] = messages
            return AIMessage(content="ok", response_metadata={"model_name": "fake"})

    monkeypatch.setattr(
        model_gateway, "get_llm_for_role", lambda *a, **k: _CaptureLLM()
    )
    role = AgentRole(name="顾问", prompt_template="你是顾问。", model_role="daily")
    db.add(role)
    await db.commit()
    await db.refresh(role)

    await agent_execution.run_agent(
        db, role, task_type="t", input_summary="s", user_message="hi"
    )
    sys_msg = captured["messages"][0]
    assert isinstance(sys_msg, SystemMessage)
    # 全局红线前缀 + 角色特有段都在
    assert "公司红线" in sys_msg.content and "你是顾问。" in sys_msg.content
