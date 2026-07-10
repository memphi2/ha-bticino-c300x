"""Device control: forwarding, locks, stair light, ringer, activations, metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from ._api_core import _SETUP_TIMEOUT, _C300XApiCore
from ._api_normalize import (
    _ok_response,
    normalize_activations,
    normalize_auth_config_status,
    normalize_ringer,
    normalize_smartphone_forwarding,
    normalize_smartphone_forwarding_mode,
    normalize_system_metrics,
)
from .agent_contracts import (
    AuthConfigStatus,
    CapabilityPayload,
    ForwardingStatus,
)
from .api_errors import (
    C300XAgentApiError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
)
from .api_validation import (
    normalize_activation_id,
    normalize_lock_id,
    normalize_stair_light_address,
)
from .device_activations import activation_items_json
from .value_parsing import (
    optional_mapping as _json_object,
)
from .value_parsing import (
    optional_string as _optional_string,
)


class _ApiDeviceMixin(_C300XApiCore):
    """Device control: forwarding, locks, stair light, ringer, activations, metrics."""

    async def async_validate_setup(self) -> CapabilityPayload:
        """Return agent/device metadata from `/api/v1/capabilities`."""

        data = await self._request_json(
            "GET",
            "/api/v1/capabilities",
            request_timeout=_SETUP_TIMEOUT,
        )
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("capabilities returned non-object JSON")
        agent = _json_object(data.get("agent"))
        device = _json_object(data.get("device"))
        capabilities = _json_object(data.get("capabilities"))
        return CapabilityPayload(
            raw=data,
            version=_optional_string(agent.get("version") or data.get("api_version")),
            agent=agent,
            implementation=_optional_string(agent.get("implementation")),
            api_version=_optional_string(data.get("api_version")),
            device_id=_optional_string(device.get("id")),
            model=_optional_string(device.get("model")),
            firmware=_optional_string(device.get("firmware")),
            capabilities=capabilities,
        )

    async def async_smartphone_forwarding_status(self) -> ForwardingStatus:
        """Return smartphone forwarding status."""

        try:
            data = await self._request_json("GET", "/api/v1/smartphone-forwarding")
        except C300XAgentApiUnsupportedError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_smartphone_forwarding(data)

    async def async_set_smartphone_forwarding_mode(self, mode: str) -> ForwardingStatus:
        """Set the smartphone forwarding mode."""

        normalized_mode = normalize_smartphone_forwarding_mode(mode)
        data = await self._request_json(
            "POST",
            "/api/v1/smartphone-forwarding",
            json_data={"mode": normalized_mode},
        )
        return normalize_smartphone_forwarding(data)

    async def async_stair_light(self, address: str) -> dict[str, Any]:
        """Activate the staircase light through an agent endpoint."""

        address = normalize_stair_light_address(address)
        data = await self._request_json(
            "POST",
            "/api/v1/stair-light/actions/activate",
            json_data={"address": address},
        )
        return _ok_response(data)

    async def async_unlock_door(self, lock_id: str = "default") -> dict[str, Any]:
        """Unlock the configured C300X door lock through the device agent."""

        normalized_lock_id = normalize_lock_id(lock_id)
        data = await self._request_json(
            "POST",
            f"/api/v1/locks/{quote(normalized_lock_id, safe='')}/actions/unlock",
        )
        return _ok_response(data)

    async def async_activations(self) -> dict[str, Any]:
        """Return configured C300X device activations."""

        data = await self._request_json("GET", "/api/v1/activations")
        return normalize_activations(data)

    async def async_run_device_activation(self, activation_id: str) -> dict[str, Any]:
        """Run one configured C300X device activation."""

        normalized_activation_id = normalize_activation_id(activation_id)
        data = await self._request_json(
            "POST",
            (
                "/api/v1/activations/"
                f"{quote(normalized_activation_id, safe='')}/actions/run"
            ),
        )
        return _ok_response(data)

    async def async_ringer_status(self) -> dict[str, Any]:
        """Return ringer mute and volume status."""

        try:
            data = await self._request_json("GET", "/api/v1/ringer")
        except C300XAgentApiError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_ringer(data)

    async def async_system_metrics(self) -> dict[str, Any]:
        """Return low-frequency device-agent system metrics."""

        data = await self._request_json("GET", "/api/v1/system/metrics")
        return normalize_system_metrics(data)

    async def async_set_ringer_muted(self, muted: bool) -> dict[str, Any]:
        """Mute or unmute the device ringer."""

        data = await self._request_json(
            "POST",
            "/api/v1/ringer",
            json_data={"muted": muted},
        )
        return normalize_ringer(data)

    async def async_set_ringer_volume(self, volume: int) -> dict[str, Any]:
        """Set the device ringer volume."""

        data = await self._request_json(
            "POST",
            "/api/v1/ringer",
            json_data={"volume": int(volume)},
        )
        return normalize_ringer(data)

    async def async_configure_device_activations(
        self,
        *,
        enabled: bool,
        auto_discover: bool,
        items: Sequence[Mapping[str, Any]],
    ) -> AuthConfigStatus:
        """Configure native-agent C300X activation discovery."""

        payload: dict[str, Any] = {
            "activationsEnabled": bool(enabled),
            "activationsAutoDiscover": bool(auto_discover),
            "activationItemsJson": activation_items_json(items),
        }
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)
