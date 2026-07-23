"""Identity use cases with inward dependencies and explicit transaction ownership."""

from __future__ import annotations

import uuid

from app.contexts.foundations.identity.application.contracts import (
    AuthenticatedIdentity,
    AuthenticateFeishuCommand,
    AuthenticatePasswordCommand,
    CreateUserCommand,
    ExternalUserSyncResult,
    IdentityUserResult,
    LoginByFeishuCommand,
    ResolvePrincipalQuery,
    SyncExternalUserCommand,
    UpdateUserCommand,
)
from app.contexts.foundations.identity.application.errors import (
    FeishuExchangeFailed,
    FeishuIdentityMissing,
    IdentityWriteConflict,
)
from app.contexts.foundations.identity.application.ports import (
    Clock,
    FeishuIdentityPort,
    IdentifierPort,
    IdentityRepository,
    IdentityUnitOfWorkFactory,
    PasswordPort,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.foundations.identity.domain.models import (
    IdentityAccount,
    valid_feishu_open_id,
    validate_role,
)
from app.contexts.shared_kernel import (
    AuthenticationFailed,
    ConflictDetected,
    PermissionDenied,
    ResourceNotFound,
)

_LOGIN_FAILED = "用户名或密码错误"
_FEISHU_DENIED = "当前飞书账号暂无系统访问权限，请联系管理员完成账号授权或状态确认。"


def _principal(account: IdentityAccount) -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        principal_id=account.id,
        role_code=account.role_code,
        department_id=account.department_id,
        is_active=account.is_active,
    )


def _user_result(account: IdentityAccount) -> IdentityUserResult:
    return IdentityUserResult(
        id=account.id,
        username=account.username,
        real_name=account.real_name,
        role_code=account.role_code,
        department_id=account.department_id,
        is_active=account.is_active,
        feishu_open_id=account.feishu_open_id,
        en_name=account.en_name,
        title=account.title,
        mobile=account.mobile,
        avatar_url=account.avatar_url,
        create_time=account.create_time,
        is_delete=account.is_deleted,
    )


def _authenticated(account: IdentityAccount) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(principal=_principal(account), user=_user_result(account))


class IdentityApplication:
    """Canonical Identity application boundary."""

    def __init__(
        self,
        *,
        uow_factory: IdentityUnitOfWorkFactory,
        passwords: PasswordPort,
        feishu: FeishuIdentityPort,
        identifiers: IdentifierPort,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._passwords = passwords
        self._feishu = feishu
        self._identifiers = identifiers
        self._clock = clock

    async def authenticate_password(
        self, command: AuthenticatePasswordCommand
    ) -> AuthenticatedIdentity:
        async with self._uow_factory() as uow:
            account = await uow.identities.find_by_username(command.username)
            verified = self._passwords.verify(
                command.password,
                account.password_hash if account is not None else None,
            )
        if account is None or not verified:
            raise AuthenticationFailed(_LOGIN_FAILED)
        if not account.is_active:
            raise PermissionDenied("账号已停用")
        return _authenticated(account)

    async def authenticate_feishu(
        self, command: AuthenticateFeishuCommand
    ) -> AuthenticatedIdentity:
        if not valid_feishu_open_id(command.open_id):
            raise AuthenticationFailed("飞书未返回用户标识")
        async with self._uow_factory() as uow:
            account = await uow.identities.find_by_feishu_open_id(command.open_id)
        if account is None or account.is_deleted or not account.is_active:
            raise PermissionDenied(_FEISHU_DENIED)
        return _authenticated(account)

    async def login_by_feishu(
        self, command: LoginByFeishuCommand
    ) -> AuthenticatedIdentity:
        try:
            external = await self._feishu.exchange(command.code)
        except FeishuIdentityMissing as exc:
            raise AuthenticationFailed("飞书未返回用户标识") from exc
        except FeishuExchangeFailed as exc:
            raise AuthenticationFailed(f"飞书登录失败:{exc}") from exc
        return await self.authenticate_feishu(AuthenticateFeishuCommand(external.open_id))

    async def resolve_principal(
        self, query: ResolvePrincipalQuery
    ) -> AuthenticatedIdentity | None:
        async with self._uow_factory() as uow:
            account = await uow.identities.get_by_id(query.user_id)
        return _authenticated(account) if account is not None else None

    async def create_user(self, command: CreateUserCommand) -> IdentityUserResult:
        validate_role(command.role_code)
        try:
            async with self._uow_factory() as uow:
                if await uow.identities.username_exists(command.username):
                    raise ConflictDetected("用户名已存在")
                account = IdentityAccount(
                    id=self._identifiers.new_id(),
                    username=command.username,
                    password_hash=self._passwords.hash(command.password),
                    real_name=command.real_name,
                    role_code=command.role_code,
                    department_id=command.department_id,
                    is_active=True,
                    feishu_open_id=command.feishu_open_id,
                    en_name="",
                    title="",
                    mobile="",
                    avatar_url="",
                    create_time=self._clock.now(),
                )
                await uow.identities.add(account)
                await uow.flush()
                await uow.source_changes.publish_identity_changed(account.id)
                await uow.commit()
        except IdentityWriteConflict as exc:
            message = (
                "该飞书身份已绑定其他用户" if command.feishu_open_id else "用户名已存在"
            )
            raise ConflictDetected(message) from exc
        return _user_result(account)

    async def list_users(self) -> tuple[IdentityUserResult, ...]:
        async with self._uow_factory() as uow:
            accounts = await uow.identities.list_accounts()
        return tuple(_user_result(account) for account in accounts)

    async def sync_external_user(
        self,
        command: SyncExternalUserCommand,
    ) -> ExternalUserSyncResult:
        """Idempotently create or refresh one Feishu directory identity."""
        open_id = command.feishu_open_id.strip()
        if not open_id:
            raise ConflictDetected("飞书用户缺少 open_id")
        try:
            async with self._uow_factory() as uow:
                account = await uow.identities.find_by_feishu_open_id(open_id)
                if account is not None and account.is_deleted:
                    raise ConflictDetected("该飞书身份已绑定已删除用户")
                created = account is None
                if account is None:
                    account = IdentityAccount(
                        id=self._identifiers.new_id(),
                        username=f"fs_{open_id[:24]}",
                        password_hash="!feishu-sso",
                        real_name=command.real_name,
                        role_code="member",
                        department_id=command.department_id,
                        is_active=True,
                        feishu_open_id=open_id,
                        en_name=command.en_name,
                        title=command.title,
                        mobile=command.mobile,
                        avatar_url=command.avatar_url,
                        create_time=self._clock.now(),
                    )
                    await uow.identities.add(account)
                else:
                    account.sync_external_profile(
                        real_name=command.real_name,
                        en_name=command.en_name,
                        title=command.title,
                        mobile=command.mobile,
                        avatar_url=command.avatar_url,
                        department_id=command.department_id,
                    )
                    await uow.identities.save(account)
                await uow.flush()
                await uow.source_changes.publish_identity_changed(account.id)
                await uow.commit()
        except IdentityWriteConflict as exc:
            raise ConflictDetected("飞书用户同步冲突") from exc
        return ExternalUserSyncResult(user=_user_result(account), created=created)

    async def update_user(self, command: UpdateUserCommand) -> IdentityUserResult:
        try:
            async with self._uow_factory() as uow:
                account = await self._required(uow.identities, command.user_id)
                password_hash = (
                    self._passwords.hash(command.password)
                    if command.password is not None
                    else None
                )
                account.update(
                    password_hash=password_hash,
                    real_name=command.real_name,
                    role_code=command.role_code,
                    department_id=command.department_id,
                    is_active=command.is_active,
                    feishu_open_id=command.feishu_open_id,
                    feishu_binding_changed=command.feishu_binding_changed,
                )
                await uow.identities.save(account)
                await uow.flush()
                await uow.source_changes.publish_identity_changed(account.id)
                await uow.commit()
        except IdentityWriteConflict as exc:
            if command.feishu_binding_changed:
                raise ConflictDetected("该飞书身份已绑定其他用户") from exc
            raise
        return _user_result(account)

    @staticmethod
    async def _required(
        repository: IdentityRepository, user_id: uuid.UUID
    ) -> IdentityAccount:
        account = await repository.get_by_id(user_id)
        if account is None:
            raise ResourceNotFound("用户不存在")
        return account
