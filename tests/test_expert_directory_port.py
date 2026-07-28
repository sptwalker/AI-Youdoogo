"""ADR 0003 自证：跨 Context 专家目录经 ExpertDirectoryPort，路由至 ``SQLAlchemyExpert*Query``。

port 方法会话无关（利于 Phase 1 远端替换）；本地实现在构造期绑定 session 并透传给查询装配，
故 monkeypatch 查询类方法即可拦截——与 directory_adapter 的委托点一致。
"""

import uuid
from typing import Any

import pytest

from app.contexts.foundations.workforce.expert_management.infrastructure import (
    sqlalchemy_query as query,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)


async def test_port_routes_get_execution_through_snapshot_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端口 get_execution → SQLAlchemyExpertSnapshotQuery.get_by_id，透传 expert_id 与结果。"""
    expert_id = uuid.uuid4()
    sentinel = object()
    captured: dict[str, Any] = {}

    async def fake_get_by_id(_self: Any, wanted: uuid.UUID) -> object:
        captured["expert_id"] = wanted
        return sentinel

    monkeypatch.setattr(query.SQLAlchemyExpertSnapshotQuery, "get_by_id", fake_get_by_id)
    port = build_local_expert_directory_port(object())  # session 仅透传给已打桩的查询
    result = await port.get_execution(expert_id)

    assert captured == {"expert_id": expert_id}
    assert result is sentinel


async def test_port_routes_list_roster_through_roster_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端口 list_roster → SQLAlchemyExpertRosterQuery.list_roster，透传 include_personal 与结果。"""
    sentinel: tuple[Any, ...] = ()
    captured: dict[str, Any] = {}

    async def fake_list_roster(_self: Any, *, include_personal: bool) -> tuple[Any, ...]:
        captured["include_personal"] = include_personal
        return sentinel

    monkeypatch.setattr(query.SQLAlchemyExpertRosterQuery, "list_roster", fake_list_roster)
    port = build_local_expert_directory_port(object())
    result = await port.list_roster(include_personal=False)

    assert captured == {"include_personal": False}
    assert result is sentinel
