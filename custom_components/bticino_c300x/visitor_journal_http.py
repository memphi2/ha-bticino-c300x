"""Entry-scoped visitor list and existing media under the snapshot read policy."""

from __future__ import annotations

from aiohttp import web
from homeassistant.auth.permissions.const import POLICY_READ

from .config_snapshots import snapshot_options
from .const import DOMAIN
from .media import _media_response
from .snapshot_http import C300XSnapshotView
from .visitor_journal_media import read_clip

_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


class C300XVisitorJournalView(C300XSnapshotView):
    """Use exactly the existing camera/entry authorization decision."""

    url = f"/api/{DOMAIN}/visitor-journal/{{entry_id}}"
    extra_urls = [f"/api/{DOMAIN}/visitor-journal/{{entry_id}}/{{visit_id}}/{{kind}}"]
    name = f"api:{DOMAIN}:visitor_journal"

    async def get(self, request: web.Request, entry_id: str, visit_id: str | None = None,
                  kind: str | None = None) -> web.Response:
        _, manager, _ = self._authorize(request, entry_id, POLICY_READ)
        journal = manager.journal
        if journal is None or journal.closed:
            raise web.HTTPNotFound()
        items = journal.items()
        if visit_id is None:
            return web.json_response({"visits": [{
                "id": item["id"], "at": item["at"], "outcome": item["outcome"],
                "expires_at": item["at"] + snapshot_options(manager.entry).retention_days * 86400,
                "image": item["snapshot"] is not None, "video": item["clip"] is not None,
                "image_at": int(item["snapshot"].split("-")[1]) / 1000 if item["snapshot"] else None,
                "video_at": item["clip"]["signature"][3] / 1_000_000_000 if item["clip"] else None,
            } for item in items]}, headers=_HEADERS)
        item = next((item for item in items if item["id"] == visit_id), None)
        if item is None:
            raise web.HTTPNotFound()
        if kind == "image" and item["snapshot"]:
            response = await super().get(request, entry_id, item["snapshot"])
            self._authorize(request, entry_id, POLICY_READ)
            if journal.closed or item not in journal.items():
                raise web.HTTPNotFound()
            return response
        if kind != "video" or not item["clip"]:
            raise web.HTTPNotFound()
        # Bound concurrent local file reads using the existing entry disk lock.
        if manager.lock.locked():
            raise web.HTTPTooManyRequests(headers={"Retry-After": "2"})
        async with manager.lock:
            try:
                content = await manager.disk_job(read_clip, manager.hass, item["clip"])
            except (OSError, ValueError):
                content = None
        # Permission/lifecycle/retention can change while the executor was running.
        self._authorize(request, entry_id, POLICY_READ)
        if journal.closed or item not in journal.items() or content is None:
            raise web.HTTPNotFound()
        response = _media_response(request, content, "video/mp4")
        response.headers.update(_HEADERS)
        return response
