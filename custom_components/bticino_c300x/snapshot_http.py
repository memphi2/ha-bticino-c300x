"""Authenticated, camera-authorized image playback."""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.helpers import entity_registry as er

from .config_snapshots import snapshot_options
from .const import DOMAIN
from .identity import media_camera_unique_id
from .media import HomeAssistantView, runtime_entry
from .snapshots import get_snapshots


def authorize_snapshot_entry(hass: Any, user: Any, entry_id: str, policy: str) -> tuple[Any, Any, Any]:
    """Share the entry/camera permission decision across HTTP and WebSocket reads."""
    entry = runtime_entry(hass, entry_id)
    manager = get_snapshots(hass, entry_id)
    if entry is None or manager is None or manager.closed:
        raise web.HTTPNotFound()
    registry = er.async_get(hass)
    unique_id = media_camera_unique_id(entry)
    entity_id = registry.async_get_entity_id("camera", DOMAIN, unique_id) if unique_id else None
    registered = registry.async_get(entity_id) if entity_id else None
    if (registered is None or registered.disabled_by or user is None
            or not (user.is_admin or user.permissions.check_entity(entity_id, policy))):
        raise web.HTTPForbidden()
    return entry, manager, hass.states.get(entity_id)


class C300XSnapshotView(HomeAssistantView):
    """Read-only access to stored images, never public files or uploads."""

    url = f"/api/{DOMAIN}/snapshots/{{entry_id}}/{{image_id}}"
    name = f"api:{DOMAIN}:snapshots"
    requires_auth = True

    def _authorize(self, request: web.Request, entry_id: str, policy: str) -> tuple[Any, Any, Any]:
        return authorize_snapshot_entry(request.app["hass"], request.get("hass_user"), entry_id, policy)

    async def get(self, request: web.Request, entry_id: str, image_id: str) -> web.Response:
        entry, manager, _state = self._authorize(request, entry_id, POLICY_READ)
        if image_id == "latest":
            content = manager.preview
        elif manager.latest is not None and image_id == manager.latest.name and manager.image is not None:
            # Named archives remain readable with saving disabled. Share the
            # retained cache across cards without contending with disk work.
            if manager.latest.captured_at <= time.time() - snapshot_options(entry).retention_days * 86400:
                raise web.HTTPNotFound()
            content = manager.image
        else:
            if manager.lock.locked():
                raise web.HTTPTooManyRequests(headers={"Retry-After": "2"})
            async with manager.lock:
                try:
                    content = await manager.disk_job(
                        manager.store.read, image_id, snapshot_options(entry).retention_days
                    )
                except (OSError, ValueError) as err:
                    raise web.HTTPNotFound() from err
        if content is None:
            raise web.HTTPNotFound()
        return web.Response(body=content, content_type="image/jpeg", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })
