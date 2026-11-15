"""Confirmed controls for settings owned by the original device GUI."""

from typing import Any

from ._api_core import _C300XApiCore
from .api_errors import C300XAgentApiResponseError


def _touch_tone_status(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise C300XAgentApiResponseError("Invalid touch-tone response")
    if not isinstance(data.get("available"), bool):
        raise C300XAgentApiResponseError("Missing touch-tone availability")
    if data["available"] and not isinstance(data.get("enabled"), bool):
        raise C300XAgentApiResponseError("Missing confirmed touch-tone state")
    return data


class _ApiDisplayMixin(_C300XApiCore):
    async def async_touch_tone_status(self) -> dict[str, Any]:
        """Read the GUI-confirmed state, without querying firmware."""
        return _touch_tone_status(await self._request_json("GET", "/api/v1/display/touch-tone"))

    async def async_set_touch_tone(self, enabled: bool) -> dict[str, Any]:
        """Await the original GUI setting's acknowledgement."""
        data = _touch_tone_status(await self._request_json(
            "POST", "/api/v1/display/touch-tone", json_data={"enabled": enabled},
            request_timeout=8.0,
        ))
        if not data["available"] or data["enabled"] is not enabled:
            raise C300XAgentApiResponseError("Touch tone was not applied")
        return data
