"""Deliverable Management canonical contracts and recovery behavior."""

from __future__ import annotations

import codecs
import csv
import io
import uuid
from collections.abc import AsyncGenerator

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.contracts import ExecutionContext, SkillRequest
from app.agents.tool_dispatcher import ToolDispatcher
from app.contexts.foundations.execution.deliverable_management import public
from app.contexts.foundations.execution.deliverable_management.application.formatting import (
    build_bytes,
    safe_file_name,
)
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableFormat,
    PublishDeliverableCommand,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints.agent_capability import (
    DeliverySkillExecutor,
)
from app.models import Base
from app.models.agent import AgentRole
from app.models.deliverable import Deliverable
from app.models.workflow import TOOL_SUCCEEDED, ToolExecution
from app.platform.object_storage import gateway as object_storage


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _role() -> AgentRole:
    return AgentRole(
        id=uuid.uuid4(),
        name="交付助理",
        prompt_template="测试",
        tools=["deliver"],
    )


_DELIVERY = (
    "【交付】名称：运营日报；格式：xlsx\n```\n"
    "| 指标 | 值 |\n| --- | --- |\n| DAU | 42 |\n```"
)


async def test_canonical_executor_uses_patchable_platform_storage(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[tuple[str, bytes, str]] = []

    async def put_object(object_name: str, data: bytes, content_type: str) -> str:
        uploads.append((object_name, data, content_type))
        return f"platform-bucket/{object_name}"

    monkeypatch.setattr(object_storage, "put_object", put_object)
    role = _role()
    result = await DeliverySkillExecutor().execute(
        db,
        role,
        SkillRequest(
            skill_key="deliver",
            action_index=0,
            arguments={
                "name": "使用/说明",
                "format": "txt",
                "body": "正文",
            },
        ),
        ExecutionContext(user_id=uuid.uuid4()),
    )

    assert len(uploads) == 1
    object_name, data, content_type = uploads[0]
    assert object_name == (
        f"deliverables/{result.artifacts[0]['deliverable_id']}/使用_说明.txt"
    )
    assert data == "正文".encode()
    assert content_type == "text/plain; charset=utf-8"
    assert result.artifacts[0]["storage_path"] == f"platform-bucket/{object_name}"


async def test_failed_upload_can_retry_same_idempotent_path_without_partial_record(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_paths: list[str] = []

    async def fail_once_then_store(
        object_name: str,
        _data: bytes,
        _content_type: str,
    ) -> str:
        attempted_paths.append(object_name)
        if len(attempted_paths) == 1:
            raise RuntimeError("object storage unavailable")
        return f"platform-bucket/{object_name}"

    monkeypatch.setattr(object_storage, "put_object", fail_once_then_store)
    context = ExecutionContext(
        user_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        attempt=1,
        idempotency_prefix="workflow:deliverable-retry",
    )
    role = _role()

    failed = await ToolDispatcher().dispatch_text(db, role, _DELIVERY, context)

    assert failed.artifacts == []
    assert (await db.execute(select(func.count()).select_from(Deliverable))).scalar_one() == 0

    succeeded = await ToolDispatcher().dispatch_text(db, role, _DELIVERY, context)

    assert len(attempted_paths) == 2
    assert attempted_paths[0] == attempted_paths[1]
    assert attempted_paths[1].startswith("deliverables/idempotent/")
    assert len(succeeded.artifacts) == 1
    assert succeeded.artifacts[0]["storage_path"] == (
        f"platform-bucket/{attempted_paths[1]}"
    )
    assert (await db.execute(select(func.count()).select_from(Deliverable))).scalar_one() == 1
    executions = (await db.execute(select(ToolExecution))).scalars().all()
    assert len(executions) == 1
    assert executions[0].status == TOOL_SUCCEEDED


def test_canonical_formatting_and_safe_file_name() -> None:
    table = "| 指标 | 值 |\n| --- | ---: |\n| DAU | 42 |"

    csv_bytes = build_bytes(DeliverableFormat.CSV, table)
    assert csv_bytes.startswith(codecs.BOM_UTF8)
    assert list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig")))) == [
        ["指标", "值"],
        ["DAU", "42"],
    ]

    workbook = load_workbook(io.BytesIO(build_bytes(DeliverableFormat.XLSX, table)))
    assert list(workbook.active.values) == [("指标", "值"), ("DAU", "42")]

    markdown = "\n# 运营日报\n\n正文\n"
    assert build_bytes(DeliverableFormat.MARKDOWN, markdown) == (
        "# 运营日报\n\n正文".encode()
    )

    file_name = safe_file_name('  运营/日报:*?"<>|  ', DeliverableFormat.CSV)
    assert file_name.endswith(".csv")
    assert not set('/\\:*?"<>|').intersection(file_name)
    assert not file_name.startswith(" ")
    assert safe_file_name("运营日报.csv", DeliverableFormat.CSV) == "运营日报.csv"
    assert safe_file_name("   ", DeliverableFormat.TEXT) == "交付物.txt"


async def test_public_get_and_list_contracts_are_typed_and_owner_scoped(
    db: AsyncSession,
) -> None:
    async def put_object(object_name: str, _data: bytes, _content_type: str) -> str:
        return f"platform-bucket/{object_name}"

    owner_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    mine = await public.publish_deliverable(
        db,
        PublishDeliverableCommand(
            owner_user_id=owner_id,
            agent_id=None,
            agent_name="交付助理",
            name="我的说明",
            file_format=DeliverableFormat.MARKDOWN,
            body="# 内容",
        ),
        publisher=put_object,
    )
    await public.publish_deliverable(
        db,
        PublishDeliverableCommand(
            owner_user_id=other_owner_id,
            agent_id=None,
            agent_name="其他助理",
            name="其他说明",
            file_format=DeliverableFormat.TEXT,
            body="内容",
        ),
        publisher=put_object,
    )

    snapshot = await public.get_deliverable(db, mine.deliverable_id)
    assert snapshot is not None
    assert snapshot.deliverable_id == mine.deliverable_id
    assert snapshot.owner_user_id == owner_id
    assert snapshot.file_format is DeliverableFormat.MARKDOWN
    assert snapshot.storage_path == mine.storage_path
    assert snapshot.is_deleted is False
    assert await public.get_deliverable(db, uuid.uuid4()) is None

    listed = await public.list_deliverables(db, owner_id)
    assert isinstance(listed, tuple)
    assert [item.deliverable_id for item in listed] == [mine.deliverable_id]
    assert all(item.owner_user_id == owner_id for item in listed)
