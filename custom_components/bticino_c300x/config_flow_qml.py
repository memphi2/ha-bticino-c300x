"""Display patch status shown in the setup and settings forms."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from .api import C300XAgentApiError
from .config_flow_forms import async_display_patch_status_text
from .entry_types import BticinoC300XConfigEntry

_STATUS_CACHE_TTL = timedelta(seconds=30)
QML_PATCH_STATUS_UNKNOWN = "unknown"
_STATUS_UNAVAILABLE = "unavailable"


async def async_qml_patch_description_placeholders(
    config_entry: BticinoC300XConfigEntry,
) -> dict[str, str]:
    """Return placeholders for the device Display patch status."""

    return {
        "qml_patch_status": await async_display_patch_status_text(
            qml_patch_status_label(await _async_qml_patch_status(config_entry))
        )
    }


async def _async_qml_patch_status(
    config_entry: BticinoC300XConfigEntry,
) -> dict[str, Any]:
    """Return cached Display patch status, refreshing it only when useful."""

    runtime_data = getattr(config_entry, "runtime_data", None)
    if runtime_data is None:
        return {}

    cached_status = getattr(runtime_data, "qml_patch_status", {})
    if not isinstance(cached_status, dict):
        cached_status = {}

    updated_at = getattr(runtime_data, "qml_patch_status_updated_at", None)
    now = datetime.now(UTC)
    if (
        cached_status
        and isinstance(updated_at, datetime)
        and now - updated_at < _STATUS_CACHE_TTL
    ):
        return cached_status

    api = getattr(runtime_data, "api", None)
    if api is None:
        return cached_status

    try:
        status = await api.async_qml_patch_status()
    except C300XAgentApiError:
        return cached_status or {
            "available": False,
            "state": _STATUS_UNAVAILABLE,
        }

    runtime_data.qml_patch_status = status
    runtime_data.qml_patch_status_updated_at = now
    return cast(dict[str, Any], status)


def qml_patch_status_label(status: dict[str, Any]) -> str:
    """Return a concise, user-visible Display patch status label."""

    if not status:
        return QML_PATCH_STATUS_UNKNOWN
    if status.get("available") is False:
        return _STATUS_UNAVAILABLE
    patched = status.get("patched")
    if patched is True:
        return "display_failed" if status.get("qt5_overlay") == "failed" else "patched"
    if patched is False:
        return "original"
    state = str(status.get("state") or "").strip()
    return state or QML_PATCH_STATUS_UNKNOWN
