"""Published Knowledge Retrieval diagnostics contract tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.entrypoints.operations import (
    diagnose_retrieval_arms,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_retrieval,
)


async def test_published_diagnostics_preserve_probe_hit_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()

    async def _diagnose(
        session: Any,
        query: str,
        top_n: int,
        visible_ids: list[uuid.UUID] | None,
    ) -> tuple[list[SimpleNamespace], list[SimpleNamespace]]:
        assert session is not None
        assert query == "盒子A5"
        assert top_n == 3
        assert visible_ids == [knowledge_base_id]
        hit = SimpleNamespace(
            file_id=document_id,
            file_name="A5.md",
            chunk_index=2,
            chunk_text="旗舰款",
            distance=0.125,
        )
        return [hit], [hit]

    async def _search(
        session: Any,
        query: str,
        top_k: int,
        *,
        visible_kb_ids: list[uuid.UUID] | None,
    ) -> list[SimpleNamespace]:
        vector, _ = await _diagnose(session, query, top_k, visible_kb_ids)
        return vector

    monkeypatch.setattr(sqlalchemy_retrieval, "diagnostic_arms", _diagnose)
    monkeypatch.setattr(sqlalchemy_retrieval, "search", _search)
    result = await diagnose_retrieval_arms(
        object(),  # type: ignore[arg-type]
        SearchKnowledgeQuery(
            query="盒子A5",
            top_k=3,
            visible_knowledge_base_ids=(knowledge_base_id,),
        ),
    )

    assert result.vector.hits == result.keyword.hits == result.fused.hits
    hit = result.vector.hits[0]
    assert (
        hit.document_id,
        hit.document_name,
        hit.chunk_index,
        hit.content,
        hit.score_distance,
    ) == (document_id, "A5.md", 2, "旗舰款", 0.125)


async def test_blank_diagnostic_query_skips_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("blank diagnostic query must not reach infrastructure")

    monkeypatch.setattr(sqlalchemy_retrieval, "diagnostic_arms", _fail)
    result = await diagnose_retrieval_arms(
        object(),  # type: ignore[arg-type]
        SearchKnowledgeQuery(query="  ", top_k=3),
    )
    assert result.vector.hits == result.keyword.hits == result.fused.hits == ()
