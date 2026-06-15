"""Exceptions raised by the C300X device-agent API client."""

from __future__ import annotations


class C300XAgentApiError(Exception):
    """Base error for device-agent API failures."""


class C300XAgentApiConnectionError(C300XAgentApiError):
    """Raised when the device agent cannot be reached."""


class C300XAgentApiResponseError(C300XAgentApiError):
    """Raised when the device agent returns an invalid response."""


class C300XAgentApiUnsupportedError(C300XAgentApiError):
    """Raised when the installed device agent does not expose an endpoint."""
