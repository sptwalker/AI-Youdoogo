"""ADR 0004 自证：跨 Context 专家写侧经 ExpertProvisioningPort，路由至既有 application 装配。

port 方法会话无关（利于 Phase 1 远端替换）；本地实现在构造期绑定 session，透传给
``build_expert_management_application``。monkeypatch 适配器模块内的该装配函数即可拦截——与
provisioning_adapter 的委托点一致，无需真实 DB。
"""

import uuid
from typing import Any

import pytest

from app.contexts.foundations.workforce.expert_management.infrastructure import (
    provisioning_adapter as adapter,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_provisioning_port,
)


class _RecordingApplication:
    """记录被路由的命令；每个写方法回吐哨兵，验证端口透传返回值。"""

    def __init__(self, captured: dict[str, Any], sentinel: object) -> None:
        self._captured = captured
        self._sentinel = sentinel

    async def create(self, command: Any) -> object:
        self._captured["create"] = command
        return self._sentinel

    async def seed(self, command: Any) -> object:
        self._captured["seed"] = command
        return self._sentinel

    async def delete(self, expert_id: uuid.UUID) -> None:
        self._captured["delete"] = expert_id


def _patch(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], sentinel: object) -> None:
    monkeypatch.setattr(
        adapter,
        "build_expert_management_application",
        lambda _session: _RecordingApplication(captured, sentinel),
    )


async def test_port_routes_create_through_application_with_serialized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端口 create → application.create，permission_scope 经 _json 序列化、owner_user_id 透传。"""
    sentinel = object()
    captured: dict[str, Any] = {}
    _patch(monkeypatch, captured, sentinel)
    owner_id = uuid.uuid4()

    port = build_local_expert_provisioning_port(object())  # session 仅透传给已打桩的装配
    result = await port.create(
        name="助理",
        prompt_template="p",
        duty=None,
        model_role="daily",
        department_id=None,
        permission_scope={"b": 1, "a": 2},
        tools=["x"],
        tier="member",
        title="专属助理",
        report_to_id=None,
        owner_user_id=owner_id,
    )

    command = captured["create"]
    assert result is sentinel
    assert command.permission_scope_json == '{"a":2,"b":1}'  # sort_keys + 紧凑分隔符
    assert command.tools_json == '["x"]'
    assert command.owner_user_id == owner_id


async def test_port_routes_seed_and_delete_through_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端口 seed/delete → application.seed/delete，透传 code 与 expert_id。"""
    sentinel = object()
    captured: dict[str, Any] = {}
    _patch(monkeypatch, captured, sentinel)
    expert_id = uuid.uuid4()

    port = build_local_expert_provisioning_port(object())
    seeded = await port.seed(
        code="sys_archivist",
        name="档案员",
        prompt_template="p",
        title="档案员",
        tier="member",
        model_role="daily",
        department_id=None,
    )
    await port.delete(expert_id)

    assert seeded is sentinel
    assert captured["seed"].code == "sys_archivist"
    assert captured["delete"] == expert_id
