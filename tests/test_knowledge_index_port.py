"""任务③ 自证：跨 Context 知识写入经 KnowledgeIndexPort，路由至底层写函数并透传参数。

port 方法会话无关（利于 Phase 2 远端替换）；本地实现在构造期绑定 session 并透传给写侧，
故 monkeypatch 模块级 ``sqlalchemy_index.ingest_text``/``delete_file`` 即可拦截——与
``test_knowledge_search_port`` 打桩 ``sqlalchemy_retrieval.search`` 一致。``list_documents``
经 gateway 直查 DB，改打桩 gateway 方法以证 ``limit`` 透传，均无需真实 DB。
"""

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    sqlalchemy_gateway,
    sqlalchemy_index,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    build_local_knowledge_index_port,
)


def _fake_record(uploader_id: uuid.UUID, knowledge_base_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        file_name="对话·记忆",
        knowledge_base_id=knowledge_base_id,
        category="conversation",
        uploader_id=uploader_id,
        storage_path="mem://x",
        file_size=None,
        mime_type=None,
        status="ready",
        create_time=datetime(2026, 7, 28),
    )


async def test_index_text_routes_and_passes_publish_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """port.index_text → use-case → gateway → 模块级 ingest_text，含 publish_events 透传。"""
    captured: dict[str, Any] = {}
    uploader, kb = uuid.uuid4(), uuid.uuid4()

    async def fake_ingest(_session: Any, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_record(uploader, kb)

    monkeypatch.setattr(sqlalchemy_index, "ingest_text", fake_ingest)
    port = build_local_knowledge_index_port(object())  # session 仅透传给已打桩函数
    result = await port.index_text(
        IndexTextCommand(
            title="对话·{title_suffix}",
            text="创想悦动",
            uploader_id=uploader,
            knowledge_base_id=kb,
            category="conversation",
            publish_events=False,
        )
    )

    assert captured["title"] == "对话·{title_suffix}" and captured["text"] == "创想悦动"
    assert captured["publish_events"] is False
    assert isinstance(result, IndexedDocument) and result.uploader_id == uploader


async def test_remove_routes_to_delete_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """port.remove_document_index → 模块级 delete_file，透传 document_id。"""
    captured: dict[str, Any] = {}
    doc_id = uuid.uuid4()

    async def fake_delete(_session: Any, file_id: uuid.UUID) -> None:
        captured["file_id"] = file_id

    monkeypatch.setattr(sqlalchemy_index, "delete_file", fake_delete)
    port = build_local_knowledge_index_port(object())
    await port.remove_document_index(doc_id)

    assert captured == {"file_id": doc_id}


async def test_list_documents_passes_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """port.list_documents → gateway.list_documents，透传 limit（不触真实 DB）。"""
    captured: dict[str, Any] = {}

    async def fake_list(
        self: Any, *, limit: int, knowledge_base_id: Any = None
    ) -> tuple[IndexedDocument, ...]:
        captured["limit"] = limit
        return ()

    monkeypatch.setattr(
        sqlalchemy_gateway.SqlAlchemyDocumentIndexGateway, "list_documents", fake_list
    )
    port = build_local_knowledge_index_port(object())
    result = await port.list_documents(limit=250)

    assert captured == {"limit": 250} and result == ()
