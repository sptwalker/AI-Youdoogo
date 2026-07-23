"""Identity application tests with no database, framework, or vendor client."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from app.contexts.foundations.identity.application.contracts import (
    AuthenticatePasswordCommand,
    CreateUserCommand,
    LoginByFeishuCommand,
    SyncExternalUserCommand,
    UpdateUserCommand,
)
from app.contexts.foundations.identity.application.errors import IdentityWriteConflict
from app.contexts.foundations.identity.application.ports import ExternalIdentity
from app.contexts.foundations.identity.application.use_cases import IdentityApplication
from app.contexts.foundations.identity.domain.models import IdentityAccount
from app.contexts.shared_kernel import (
    AuthenticationFailed,
    ConflictDetected,
    PermissionDenied,
)

NOW = datetime(2026, 7, 23, tzinfo=UTC)
USER_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
DEPARTMENT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")


def _account(**changes: object) -> IdentityAccount:
    values: dict[str, object] = {
        "id": USER_ID,
        "username": "member01",
        "password_hash": "hashed-secret",
        "real_name": "成员",
        "role_code": "member",
        "department_id": DEPARTMENT_ID,
        "is_active": True,
        "feishu_open_id": "ou_member_123456",
        "en_name": "Member",
        "title": "Engineer",
        "mobile": "",
        "avatar_url": "",
        "create_time": NOW,
        "is_deleted": False,
    }
    values.update(changes)
    return IdentityAccount(**values)  # type: ignore[arg-type]


class FakeRepository:
    def __init__(self, account: IdentityAccount | None = None) -> None:
        self.account = account
        self.added: IdentityAccount | None = None
        self.saved: IdentityAccount | None = None
        self.username_taken = False

    async def find_by_username(self, username: str) -> IdentityAccount | None:
        if self.account is not None and self.account.username == username:
            return self.account
        return None

    async def find_by_feishu_open_id(self, open_id: str) -> IdentityAccount | None:
        if self.account is not None and self.account.feishu_open_id == open_id:
            return self.account
        return None

    async def get_by_id(self, user_id: uuid.UUID) -> IdentityAccount | None:
        if self.account is not None and self.account.id == user_id:
            return self.account
        return None

    async def username_exists(self, username: str) -> bool:
        return self.username_taken

    async def add(self, account: IdentityAccount) -> None:
        self.added = account
        self.account = account

    async def save(self, account: IdentityAccount) -> None:
        self.saved = account

    async def list_accounts(self) -> list[IdentityAccount]:
        return [self.account] if self.account is not None else []


class FakeSourceChanges:
    def __init__(self) -> None:
        self.identity_ids: list[uuid.UUID] = []

    async def publish_identity_changed(self, identity_id: uuid.UUID) -> None:
        self.identity_ids.append(identity_id)


class FakeUnitOfWork:
    def __init__(self, account: IdentityAccount | None = None) -> None:
        self.identities = FakeRepository(account)
        self.source_changes = FakeSourceChanges()
        self.commit_count = 0
        self.flush_count = 0
        self.rollback_count = 0
        self.flush_error: Exception | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_error is not None:
            raise self.flush_error

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakePasswords:
    def __init__(self, verified: bool = True) -> None:
        self.verified = verified
        self.verify_hashes: list[str | None] = []

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, password_hash: str | None) -> bool:
        self.verify_hashes.append(password_hash)
        return self.verified


class FakeFeishu:
    def __init__(self, open_id: str = "ou_member_123456") -> None:
        self.open_id = open_id

    async def exchange(self, code: str) -> ExternalIdentity:
        return ExternalIdentity(open_id=self.open_id)


class FixedIdentifier:
    def new_id(self) -> uuid.UUID:
        return USER_ID


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _application(
    uow: FakeUnitOfWork,
    *,
    passwords: FakePasswords | None = None,
    feishu: FakeFeishu | None = None,
) -> IdentityApplication:
    return IdentityApplication(
        uow_factory=lambda: uow,
        passwords=passwords or FakePasswords(),
        feishu=feishu or FakeFeishu(),
        identifiers=FixedIdentifier(),
        clock=FixedClock(),
    )


async def test_missing_username_still_runs_password_verification() -> None:
    uow = FakeUnitOfWork()
    passwords = FakePasswords(verified=False)

    with pytest.raises(AuthenticationFailed, match="用户名或密码错误"):
        await _application(uow, passwords=passwords).authenticate_password(
            AuthenticatePasswordCommand(username="missing", password="secret")
        )

    assert passwords.verify_hashes == [None]


async def test_wrong_password_and_inactive_account_keep_distinct_errors() -> None:
    wrong_passwords = FakePasswords(verified=False)
    with pytest.raises(AuthenticationFailed, match="用户名或密码错误"):
        await _application(
            FakeUnitOfWork(_account()), passwords=wrong_passwords
        ).authenticate_password(
            AuthenticatePasswordCommand(username="member01", password="wrong")
        )

    with pytest.raises(PermissionDenied, match="账号已停用"):
        await _application(FakeUnitOfWork(_account(is_active=False))).authenticate_password(
            AuthenticatePasswordCommand(username="member01", password="secret")
        )


async def test_feishu_login_reuses_bound_account_and_preserves_role() -> None:
    uow = FakeUnitOfWork(_account(role_code="admin"))

    result = await _application(uow).login_by_feishu(LoginByFeishuCommand(code="code"))

    assert result.user.id == USER_ID
    assert result.user.role_code == "admin"
    assert uow.identities.added is None
    assert uow.commit_count == 0


async def test_create_publishes_one_change_and_commits_once() -> None:
    uow = FakeUnitOfWork()

    result = await _application(uow).create_user(
        CreateUserCommand(username="new-user", password="secret-88")
    )

    assert result.id == USER_ID
    assert uow.identities.added is not None
    assert uow.flush_count == 1
    assert uow.source_changes.identity_ids == [USER_ID]
    assert uow.commit_count == 1


async def test_create_translates_unique_feishu_conflict() -> None:
    uow = FakeUnitOfWork()
    uow.flush_error = IdentityWriteConflict()

    with pytest.raises(ConflictDetected, match="飞书身份"):
        await _application(uow).create_user(
            CreateUserCommand(
                username="new-user",
                password="secret-88",
                feishu_open_id="ou_new_user_123456",
            )
        )

    assert uow.source_changes.identity_ids == []
    assert uow.commit_count == 0


async def test_partial_update_preserves_department_and_unbinds_feishu() -> None:
    uow = FakeUnitOfWork(_account())

    result = await _application(uow).update_user(
        UpdateUserCommand(
            user_id=USER_ID,
            department_id=None,
            feishu_open_id=None,
            feishu_binding_changed=True,
        )
    )

    assert result.department_id == DEPARTMENT_ID
    assert result.feishu_open_id is None
    assert uow.source_changes.identity_ids == [USER_ID]
    assert uow.commit_count == 1


async def test_external_user_sync_creates_then_updates_by_feishu_identity() -> None:
    uow = FakeUnitOfWork()
    application = _application(uow)

    created = await application.sync_external_user(
        SyncExternalUserCommand(
            feishu_open_id="ou_external_123456",
            real_name="张三",
            en_name="San Zhang",
            title="工程师",
            mobile="13800000000",
            avatar_url="https://example.test/avatar.png",
            department_id=DEPARTMENT_ID,
        )
    )
    updated = await application.sync_external_user(
        SyncExternalUserCommand(
            feishu_open_id="ou_external_123456",
            real_name="张三（更新）",
            en_name="Zhang San",
            title="高级工程师",
            mobile="13900000000",
            avatar_url="https://example.test/avatar-new.png",
            department_id=None,
        )
    )

    assert created.created is True
    assert updated.created is False
    assert updated.user.id == created.user.id
    assert updated.user.role_code == "member"
    assert updated.user.real_name == "张三（更新）"
    assert updated.user.en_name == "Zhang San"
    assert updated.user.title == "高级工程师"
    assert updated.user.mobile == "13900000000"
    assert updated.user.avatar_url == "https://example.test/avatar-new.png"
    assert updated.user.department_id is None
    assert uow.commit_count == 2
    assert uow.source_changes.identity_ids == [USER_ID, USER_ID]
