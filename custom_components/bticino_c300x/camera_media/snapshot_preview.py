"""Connect camera state to entry-owned visitor images without device requests."""

from typing import Any
from uuid import uuid4

from ..config_snapshots import snapshot_options
from ..snapshots import get_snapshots

STILL_IMAGE_CONTENT_TYPE = "image/svg+xml"
STILL_IMAGE_BYTES = b"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#111820"/><g fill="none" stroke="#8da2b5" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"><path d="M216 152h178v96H216z"/><path d="M394 180l82-46v132l-82-46z"/><path d="M250 152l-32-56h174l-32 56"/><path d="M305 248v48"/><path d="M250 296h142"/></g></svg>"""


def snapshot_attributes(hass: Any, entry: Any) -> dict[str, Any]:
    """Return the compact archive metadata shared with the bundled card."""

    options = snapshot_options(entry)
    manager = get_snapshots(hass, entry.entry_id) if hass else None
    latest = manager.latest if manager and manager.preview else None
    return {
        "stream_snapshots": manager.enabled if manager else False,
        "snapshot_delay_seconds": options.delay_seconds,
        "snapshot_retention_days": options.retention_days,
        "snapshot_latest": latest.name if latest else None,
        "snapshot_captured_at": latest.captured_at if latest else None,
    }


def snapshot_window_changed(camera: Any, was_available: bool) -> None:
    """Join or close a capture identity only at video-window boundaries."""

    manager = get_snapshots(camera.hass, camera._entry.entry_id) if camera.hass else None
    if not camera._video_window_available:
        key, camera._snapshot_capture_key = camera._snapshot_capture_key, None
        if key is not None and manager is not None:
            manager.capture_ended(key)
    elif not was_available and not camera._background_tasks.closing:
        camera._snapshot_capture_key = uuid4().hex
        if manager is not None:
            manager.capture_requested(camera._snapshot_capture_key)
