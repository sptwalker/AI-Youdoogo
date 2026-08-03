"""Stable failure categories for the optional Lodge resource-server boundary."""


class LodgeIdentityError(Exception):
    """Base error for Lodge identity handling."""


class LodgeIdentityConfigurationError(LodgeIdentityError):
    """The opted-in Lodge integration is incomplete or unsafe."""


class LodgeTokenRejected(LodgeIdentityError):
    """A presented browser target token cannot be trusted."""


class LodgeStatusDenied(LodgeIdentityError):
    """Online status did not affirm the verified token's authority."""
