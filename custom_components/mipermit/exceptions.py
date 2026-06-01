"""Exceptions for the MiPermit integration."""


class MiPermitError(Exception):
    """Raised for expected MiPermit interaction failures."""


class InvalidCredentials(MiPermitError):
    """Raised when credentials are rejected by MiPermit."""


class CannotConnect(MiPermitError):
    """Raised when the MiPermit site cannot be reached."""
