"""飞书输出（compose 半）单测（离线）：草稿解析、compose 零飞书调用、自门控、发布器 docx/bitable
分派与未知类型、凭证门控、注册表成员。仿 test_read_attachment_skill.py。

机械发布半（feishu_publish 步配对 + 机械步 + 幂等重放）依赖 workflow-runtime 编排，待跨模块专项
统一重建后补测；本模块仅覆盖 compose 半 + 已就绪的发布器底层。
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.foundations.integration.feishu_output.entrypoints import (
    agent_capability,
    operations,
)
from app.contexts.foundations.integration.feishu_output.infrastructure import publisher
from app.core import runtime_config
from app.models import Base
from app.models.agent import AgentRole


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
    return AgentRole(id=uuid.uuid4(), name="发布助理", prompt_template="x", tools=[])


def _doc_block(title: str, body: str) -> str:
    return f"【整理飞书文档】标题：{title}\n```\n{body}\n```"


def _table_block(app_token: str, table_id: str, records_json: str) -> str:
    return f"【整理多维表格】表格：{app_token}/{table_id}\n```\n{records_json}\n```"


class _FakeFeishu:
    """记录飞书写调用次数的假客户端（断言 compose 零调用 / 发布器分派次数）。"""

    def __init__(self) -> None:
        self.doc_calls = 0
        self.block_calls = 0
        self.record_calls = 0

    async def create_document(self, title: str) -> str:
        self.doc_calls += 1
        return "doc-1"

    async def append_document_blocks(self, document_id: str, blocks: list[Any]) -> None:
        self.block_calls += 1

    async def bitable_create_record(
        self, app_token: str, table_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.record_calls += 1
        return {"record": {"record_id": f"rec-{self.record_calls}"}}


# ── parse（草稿解析，零外部调用）───────────────────────────
def test_parse_docx() -> None:
    drafts = agent_capability.parse(_doc_block("周报", "# 标题\n正文行"))
    assert drafts == [
        {
            "kind": "docx",
            "publish_key": "feishu_publish",
            "title": "周报",
            "body": "# 标题\n正文行",
        }
    ]


def test_parse_bitable() -> None:
    drafts = agent_capability.parse(_table_block("appX", "tblY", '[{"名称":"A","值":"1"}]'))
    assert drafts == [
        {
            "kind": "bitable",
            "publish_key": "feishu_publish",
            "app_token": "appX",
            "table_id": "tblY",
            "records": [{"名称": "A", "值": "1"}],
        }
    ]


def test_parse_caps_at_two() -> None:
    text = "\n\n".join(_doc_block(f"文档{i}", "正文") for i in range(3))
    assert len(agent_capability.parse(text)) == 2


def test_parse_bitable_bad_json_dropped() -> None:
    assert agent_capability.parse(_table_block("a", "b", "not json")) == []


def test_parse_empty() -> None:
    assert agent_capability.parse("普通回复，无飞书整理指令") == []


# ── compose execute：产草稿 + note，★零飞书调用★ ───────────
async def test_compose_execute_makes_draft_zero_feishu(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeFeishu()
    monkeypatch.setattr(publisher, "feishu_client", fake)
    res = await agent_capability.execute(db, _role(), _doc_block("经营周报", "# 概要\n营收上升"))
    assert len(res.artifacts) == 1 and res.artifacts[0]["kind"] == "docx"
    assert any("草稿" in note and "真人验收" in note for note in res.notes)
    # 红线核心：compose 不可逆写路径之前，绝不触任何飞书调用
    assert fake.doc_calls == 0 and fake.record_calls == 0


async def test_compose_execute_no_directive(db: AsyncSession) -> None:
    res = await agent_capability.execute(db, _role(), "普通回复，无整理指令")
    assert res.artifacts == [] and res.notes == []


# ── 自门控（prompt_section 按凭证门控）─────────────────────
async def test_prompt_section_advertises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _available() -> bool:
        return True

    monkeypatch.setattr(operations, "feishu_output_available", _available)
    section = await agent_capability.prompt_section()
    assert "【整理飞书文档】" in section and "【整理多维表格】" in section


async def test_prompt_section_gated_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable() -> bool:
        return False

    monkeypatch.setattr(operations, "feishu_output_available", _unavailable)
    assert await agent_capability.prompt_section() == ""


# ── publisher（真发布器分派，仅调假 client）─────────────────
async def test_publisher_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeFeishu()
    monkeypatch.setattr(publisher, "feishu_client", fake)
    out = await publisher.publish(
        {"kind": "docx", "title": "日报", "body": "# 大标题\n正文一\n## 小标题"}
    )
    assert out["kind"] == "docx" and out["document_id"] == "doc-1" and out["block_count"] == 3
    assert fake.doc_calls == 1 and fake.block_calls == 1


async def test_publisher_bitable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeFeishu()
    monkeypatch.setattr(publisher, "feishu_client", fake)
    out = await publisher.publish(
        {
            "kind": "bitable",
            "app_token": "appX",
            "table_id": "tblY",
            "records": [{"名称": "A"}, {"名称": "B"}],
        }
    )
    assert out["record_count"] == 2 and out["record_ids"] == ["rec-1", "rec-2"]
    assert fake.record_calls == 2


async def test_publisher_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="未知飞书草稿类型"):
        await publisher.publish({"kind": "pptx"})


async def test_publisher_bitable_missing_token_raises() -> None:
    with pytest.raises(ValueError, match="app_token"):
        await publisher.publish(
            {"kind": "bitable", "app_token": "", "table_id": "t", "records": [{}]}
        )


# ── 凭证门控 ────────────────────────────────────────────
def test_credentials_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {"feishu_app_id": "cli_x", "feishu_app_secret": "sec_y"}
    monkeypatch.setattr(
        runtime_config, "effective", lambda key, default="": values.get(key, default)
    )
    assert publisher.credentials_configured() is True


def test_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "effective", lambda key, default="": "")
    assert publisher.credentials_configured() is False


# ── 注册表成员（仅 compose 半；机械发布半待跨模块编排专项）──
def test_registry_membership() -> None:
    assert "compose_feishu" in REGISTRY
    compose = REGISTRY["compose_feishu"]
    assert compose.default_on is True and compose.legacy_executor is not None
    assert compose.executor_factory is None  # compose 走文本路径，不作结构化调用
    assert "feishu_publish" not in REGISTRY  # 机械发布半未随本模块落地
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 默认全开
    assert "compose_feishu" in keys
