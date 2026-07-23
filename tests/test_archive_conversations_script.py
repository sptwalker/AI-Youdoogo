"""Conversation archive cron script smoke test."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.contexts.business.assistant_conversations.application.contracts import Principal
from scripts import archive_conversations

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module_name",
    ("desktop_service", "desktop_chat_service", "desktop_chat_streaming"),
)
def test_legacy_desktop_service_facades_are_removed(module_name: str) -> None:
    assert not (ROOT / "app/services" / f"{module_name}.py").exists()


class _ScalarResult:
    def __init__(self, users: list[SimpleNamespace]) -> None:
        self._users = users

    def scalars(self) -> list[SimpleNamespace]:
        return self._users


class _Session:
    def __init__(self, users: list[SimpleNamespace]) -> None:
        self._users = users

    async def execute(self, statement: Any) -> _ScalarResult:
        del statement
        return _ScalarResult(self._users)


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> _Session:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc, traceback


@pytest.mark.asyncio
async def test_run_archives_each_user_and_preserves_cli_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alice_id, bob_id, carol_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    users = [
        SimpleNamespace(
            id=alice_id,
            username="alice",
            real_name="爱丽丝",
            department_id=None,
        ),
        SimpleNamespace(
            id=bob_id,
            username="bob",
            real_name=None,
            department_id=None,
        ),
        SimpleNamespace(
            id=carol_id,
            username="carol",
            real_name="Carol",
            department_id=None,
        ),
    ]
    session = _Session(users)
    monkeypatch.setattr(
        archive_conversations,
        "async_session_factory",
        lambda: _SessionContext(session),
    )
    calls: list[Principal] = []

    async def _archive(_session: _Session, principal: Principal) -> int:
        assert _session is session
        calls.append(principal)
        if principal.id == carol_id:
            raise RuntimeError("boom")
        return 2 if principal.id == alice_id else 0

    monkeypatch.setattr(archive_conversations.assistant_conversations, "archive_old", _archive)

    assert await archive_conversations._run() == 0
    assert [(call.id, call.display_name) for call in calls] == [
        (alice_id, "爱丽丝"),
        (bob_id, "bob"),
        (carol_id, "Carol"),
    ]
    output = capsys.readouterr().out
    assert "用户 alice：归档 2 条旧对话" in output
    assert "用户 carol 归档失败：boom" in output
    assert "完成，共归档 2 条。" in output
