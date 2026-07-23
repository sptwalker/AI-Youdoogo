"""Identity adapter failures normalized before use-case error mapping."""


class IdentityWriteConflict(Exception):
    """Persistence rejected an Identity write because a unique fact conflicted."""


class FeishuExchangeFailed(Exception):
    """The external Feishu identity exchange failed with a safe message."""


class FeishuIdentityMissing(Exception):
    """The OAuth response did not contain a stable app-scoped identity."""
