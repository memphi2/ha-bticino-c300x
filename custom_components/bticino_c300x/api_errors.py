"""Exceptions raised by the C300X device-agent API client."""

from __future__ import annotations


class C300XAgentApiError(Exception):
    """Base error for device-agent API failures."""


class C300XAgentApiConnectionError(C300XAgentApiError):
    """Raised when the device agent cannot be reached."""


class C300XDisplayBridgeNotRegisteredError(C300XAgentApiConnectionError):
    """The event route is reachable but has lost its runtime bridge registration."""


class C300XAgentUpdateError(C300XAgentApiConnectionError):
    """Structured failure from a maintenance/update endpoint, without retry advice."""

    def __init__(self, message: str, *, status: int, code: str | None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def repair_key(self) -> str:
        """Translate only known status/code pairs; never infer from error text."""

        if (self.status, self.code) in {
            (409, "update_root_already_writable"),
            (500, "update_root_readonly_failed"),
            (500, "update_apply_failed"),
        }:
            return str(self.code)
        return "update_failed"


class C300XDeviceNotRegisteredError(C300XAgentApiConnectionError):
    """The C300X has no SIP domain: it was never added in the Door Entry app.

    Flexisip on the device gets its user, domain and certificates only from
    that registration, so the Home Assistant media user cannot be created yet.
    """


class C300XStationBusyError(C300XAgentApiConnectionError):
    """The agent answered `409 station_busy`: a call or stream is running.

    The station does not run the command meanwhile; nothing was changed.
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
