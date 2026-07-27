"""A1 自证：跨 Context 知识检索经 KnowledgeSearchPort，且路由至 ``sqlalchemy_retrieval.search``。

port 方法会话无关（利于 Phase 2 远端替换）；本地实现在构造期绑定 session 并透传给检索层，
故 monkeypatch 模块级 ``search`` 即可拦截——与 ``test_agent_knowledge`` 的打桩点一致。
"""

import uuid
from typing import Any

import pytest

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_retrieval as retrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import (
    build_local_knowledge_search_port,
)


async def test_port_routes_search_through_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """端口 search → use-case → gateway → 模块级 retrieval.search，命中被发布为 KnowledgeHit。"""
    fid = uuid.uuid4()
    hit = retrieval.Hit(
        file_id=fid, file_name="资料.txt", chunk_index=1, chunk_text="创想悦动", distance=0.2
    )
    captured: dict[str, Any] = {}

    async def fake_search(_session: Any, query: str, **kwargs: Any) -> list[retrieval.Hit]:
        captured["query"] = query
        captured["top_k"] = kwargs.get("top_k")
        return [hit]

    monkeypatch.setattr(retrieval, "search", fake_search)
    port = build_local_knowledge_search_port(object())  # session 仅透传给已打桩的 search
    result = await port.search(SearchKnowledgeQuery(query="公司简介", top_k=5))

    assert captured == {"query": "公司简介", "top_k": 5}
    assert len(result.hits) == 1
    assert result.hits[0].document_id == fid and result.hits[0].content == "创想悦动"


async def test_port_short_circuits_blank_query() -> None:
    """空查询在 use-case 短路返回空结果，不触碰检索层（无需 session）。"""
    port = build_local_knowledge_search_port(object())
    result = await port.search(SearchKnowledgeQuery(query="   "))
    assert result.hits == ()
