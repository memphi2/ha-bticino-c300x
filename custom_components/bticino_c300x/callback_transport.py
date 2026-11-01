"""Opt in to agent TLS through the callback override, without HTTP idle work."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from .api import C300XAgentApi, C300XAgentApiError, C300XAgentApiUnsupportedError
from .const import CONF_CALLBACK_BASE_URL
from .entry_config import entry_config_value
from .entry_types import BticinoC300XConfigEntry

_TRANSPORT_KEYS = (
    "https_callbacks",
    "https_callbacks_configurable",
    "https_callbacks_configured",
    "https_callbacks_enabled",
)


class CallbackTransport:
    """Reconcile once per registration lifecycle; reuse its existing retries."""

    def __init__(
        self,
        entry: BticinoC300XConfigEntry,
        api: C300XAgentApi,
        capabilities: dict[str, Any],
    ) -> None:
        override = str(entry_config_value(entry, CONF_CALLBACK_BASE_URL, "") or "")
        self._enabled = urlsplit(override.strip()).scheme.lower() == "https"
        self._api = api
        self._capabilities = capabilities
        self._ready = False
        self._refresh_required = False
        self._restart_requested = False
        self._changed = False
        self._lock = asyncio.Lock()

    async def async_prepare(self, callback_url: str) -> bool:
        """Return whether a completed mode change needs bridge registration."""

        async with self._lock:
            changed = await self._async_prepare()
            if urlsplit(callback_url).scheme == "https" and not self._enabled:
                raise C300XAgentApiError(
                    "HTTPS callbacks require an explicit HTTPS callback base URL override"
                )
            return changed

    async def _async_prepare(self) -> bool:
        if self._ready:
            return False
        if self._refresh_required:
            setup = await self._api.async_validate_setup()
            capabilities = setup.get("capabilities", {})
            for key in _TRANSPORT_KEYS:
                self._capabilities[key] = capabilities.get(key)

        capabilities = self._capabilities
        if capabilities.get("https_callbacks_configurable") is not True:
            if self._enabled:
                raise C300XAgentApiUnsupportedError(
                    "Update the C300X agent to enable optional HTTPS callbacks"
                )
            self._ready = True
            return False

        configured = capabilities.get("https_callbacks_configured") is True
        active = capabilities.get("https_callbacks_enabled") is True
        if configured != self._enabled:
            self._refresh_required = True
            status = await self._api.async_configure_callback_https(self._enabled)
            if status.get("https_callbacks_configured") is not self._enabled:
                raise C300XAgentApiError("Agent did not confirm callback HTTPS configuration")
            capabilities["https_callbacks_configured"] = self._enabled
            self._changed = True

        if active != self._enabled:
            self._refresh_required = True
            self._changed = True
            if not self._restart_requested:
                await self._api.async_restart_agent(only_if_idle=True)
                self._restart_requested = True
            raise C300XAgentApiError("Callback transport change is awaiting agent restart")

        if self._enabled and capabilities.get("https_callbacks") is not True:
            raise C300XAgentApiError("HTTPS callbacks are unavailable on the device")
        self._ready = True
        return self._changed
