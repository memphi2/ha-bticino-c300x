"""Doorbell video helpers for BTicino C300X."""

from __future__ import annotations

from base64 import b64decode
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_VIDEO_STREAM_PATH, DOMAIN
from .entry_types import BticinoC300XConfigEntry

CAMERA_DOMAIN = "camera"
DOORBELL_CAMERA_UNIQUE_ID_SUFFIX = "doorbell_camera"
_CAMERA_PROXY_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAKAAAABaCAIAAACwpMoFAAACCUlEQVR4nO3dMU4CQRSA4cFwAmsTW6m9hCewpKS0"
    "8CAWlpSUnMBLWFNzE4uJZAKKMbBv3/7zfxUmIOv8voVdyTq7vXso4roZewM0LAPDGRjOwHAGhjMwnIHh5u0XT2+f"
    "v93v4/Xx/DfysTkf6wTDGRjOwHAGhjMwnIHhDAxnYLiZf/Bnc4LhDAxnYDgDwxkYzsBwBoYzMJyB4QwMN//7Lte2"
    "2uzinzSP9XIR+XSh56I7T9sKyxy3i7ZuK2w1ggJb91TMmkTsoo9+kuAXoWyCVyP6XXTndUv4CgweuP2FtW7VrsPQ"
    "O2qPg+EMDGdgOAPDGRhuhHPR/5X8JEnyQ4PsE5y8bkm/haknuK7d+/P92Btyzst2v9rs0s5x3gmeRN3yvYVp5zhp"
    "4KnUrTI3ThpY12JgOAPDGRjOwHCpj4Ov7mW7rzem8v78ch1N8KHu0W22jgL3ycBwHQVuX3f7eQ3u601WP10POprg"
    "PhkYzsBwBoYzMJyB4QwMlzRw/QzbVM4Y1+3M+bm7pIHLdBpnrluSn8laLxerzS5/47R1S+YJrjKvXZV8C1NPcJV8"
    "BZPLPsG6kIHhDAxnYDgDww0eOPKSQVMReWmp6Am2cfAKBF1t1q4/CjjED5pgT1acilmTuF20jVthqzHCP6fsfHdN"
    "vuK74nkcDGdgOAPDGRjOwHAGhjMwnIHhDAxnYLgvPyaFOUQD0gUAAAAASUVORK5CYII="
)

TRANSPARENT_CAMERA_PROXY_IMAGE = b64decode(_CAMERA_PROXY_IMAGE_B64)


def doorbell_camera_unique_id(entry: BticinoC300XConfigEntry) -> str:
    """Return the stable unique ID used by the doorbell camera entity."""

    return f"{entry.entry_id}_{DOORBELL_CAMERA_UNIQUE_ID_SUFFIX}"


def resolve_doorbell_camera_entity_id(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> str | None:
    """Resolve the current doorbell camera entity ID from the entity registry."""

    registry = er.async_get(hass)
    if registry is None or not hasattr(registry, "async_get_entity_id"):
        return None
    entity_id = registry.async_get_entity_id(
        CAMERA_DOMAIN,
        DOMAIN,
        doorbell_camera_unique_id(entry),
    )
    return entity_id if isinstance(entity_id, str) else None


def safe_stream_path(path: Any) -> str:
    """Return a stream path without exposing full RTSP URLs as attributes."""

    text = str(path or DEFAULT_VIDEO_STREAM_PATH)
    if text.startswith("rtsp://"):
        return DEFAULT_VIDEO_STREAM_PATH
    return text
