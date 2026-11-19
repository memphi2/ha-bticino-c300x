"""Camera-authorized chronological HA snapshot/capture history, without device I/O."""

from __future__ import annotations

import re
import time
from typing import Any

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_READ

from .config_snapshots import snapshot_options
from .const import DOMAIN
from .media import _media_response, _media_window
from .media_history import PUBLIC_FIELDS, inventory, read_item, video_records
from .snapshot_http import C300XSnapshotView

_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


class C300XMediaHistoryView(C300XSnapshotView):
    """Reuse the snapshot camera policy and manager's cancellation-safe disk lock."""

    url = f"/api/{DOMAIN}/media-history/{{entry_id}}"
    extra_urls = [f"/api/{DOMAIN}/media-history/{{entry_id}}/{{media_id}}"]
    name = f"api:{DOMAIN}:media_history"

    async def get(self, request: web.Request, entry_id: str,
                  media_id: str | None = None) -> web.Response:
        entry, manager, _ = self._authorize(request, entry_id, POLICY_READ)
        journal = manager.journal
        runtime = getattr(entry, "runtime_data", None)
        if media_id is not None and not _ID.fullmatch(media_id):
            raise web.HTTPNotFound()
        if manager.lock.locked():
            raise web.HTTPTooManyRequests(headers={"Retry-After": "2"})

        def recheck(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            current_entry, current_manager, _ = self._authorize(request, entry_id, POLICY_READ)
            if (current_entry is not entry or current_manager is not manager
                    or getattr(entry, "runtime_data", None) is not runtime
                    or manager.journal is not journal
                    or (journal is not None and journal.closed)):
                raise web.HTTPNotFound()
            now = time.time()
            days = snapshot_options(entry).retention_days
            current_videos = {record["clip"]["name"]: record for record in video_records(journal)}
            kept = []
            for item in items:
                if (not now - days * 86400 < item["at"] <= now
                        or (item["kind"] == "image" and not manager.enabled)
                        or (item["kind"] == "video" and item["record"] !=
                            current_videos.get(item["identity"]["name"]))):
                    continue
                item["expires_at"] = item["at"] + days * 86400
                kept.append(item)
            return kept

        async with manager.lock:
            try:
                items = await manager.disk_job(
                    inventory, manager.hass, entry_id, manager.enabled,
                    snapshot_options(entry).retention_days, video_records(journal),
                )
                items = recheck(items)
                if media_id is None:
                    return web.json_response({"items": [
                        {key: item[key] for key in PUBLIC_FIELDS} for item in items
                    ]}, headers=_HEADERS)
                item = next((item for item in items if item["id"] == media_id), None)
                if item is None:
                    raise web.HTTPNotFound()
                size = item["identity"]["signature"][2] if item["kind"] == "video" else None
                content = await manager.disk_job(
                    read_item, manager.hass, entry_id, item, snapshot_options(entry).retention_days,
                    None if size is None else _media_window(request, size),
                )
            except (OSError, ValueError) as err:
                raise web.HTTPNotFound() from err
            if not recheck([item]) or content is None:
                raise web.HTTPNotFound()
        response = (web.Response(body=content, content_type="image/jpeg")
                    if item["kind"] == "image" else _media_response(request, content, "video/mp4", size=size))
        response.headers.update(_HEADERS)
        return response
