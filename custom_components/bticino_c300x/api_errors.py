"""Exceptions raised by the C300X device-agent API client."""

from __future__ import annotations


class C300XAgentApiError(Exception):
    """Base error for device-agent API failures."""


class C300XAgentApiConnectionError(C300XAgentApiError):
    """Raised when the device agent cannot be reached."""


class C300XDeviceNotRegisteredError(C300XAgentApiConnectionError):
    """The C300X has no SIP domain: it was never added in the Door Entry app.

    Flexisip on the device gets its user, domain and certificates only from
    that registration, so the Home Assistant media user cannot be created yet.
    """


class C300XAgentApiAuthError(C300XAgentApiError):
    """A credential was rejected, independently of transport availability."""

    def __init__(self, *, maintenance: bool = False) -> None:
        self.maintenance = maintenance
        super().__init__(
            "device agent rejected the maintenance key"
            if maintenance else "device agent rejected the access key"
        )


class C300XAgentApiResponseError(C300XAgentApiError):
    """Raised when the device agent returns an invalid response."""


class C300XAgentApiUnsupportedError(C300XAgentApiError):
    """Raised when the installed device agent does not expose an endpoint."""
