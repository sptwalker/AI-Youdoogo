"""Identity-owned persistence, transaction, cryptography, and integration ports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.identity.domain.models import IdentityAccount


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    open_id: str


class IdentityRepository(Protocol):
    async def find_by_username(self, username: str) -> IdentityAccount | None: ...

    async def find_by_feishu_open_id(self, open_id: str) -> IdentityAccount | None: ...

    async def get_by_id(self, user_id: uuid.UUID) -> IdentityAccount | None: ...

    async def username_exists(self, username: str) -> bool: ...

    async def add(self, account: IdentityAccount) -> None: ...

    async def save(self, account: IdentityAccount) -> None: ...

    async def list_accounts(self) -> list[IdentityAccount]: ...


class SourceChangePort(Protocol):
    async def publish_identity_changed(self, identity_id: uuid.UUID) -> None: ...


class IdentityUnitOfWork(Protocol):
    @property
    def identities(self) -> IdentityRepository: ...

    @property
    def source_changes(self) -> SourceChangePort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def flush(self) -> None: ...

    async def rollback(self) -> None: ...


IdentityUnitOfWorkFactory = Callable[[], IdentityUnitOfWork]


class PasswordPort(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str | None) -> bool: ...


class FeishuIdentityPort(Protocol):
    async def exchange(self, code: str) -> ExternalIdentity: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
