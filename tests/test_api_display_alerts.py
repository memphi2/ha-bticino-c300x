"""Single-attempt display-alert transport with strict GUI acceptance."""

import asyncio

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.bticino_c300x.api import C300XAgentApi
from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.const import HEADER_MAINTENANCE_TOKEN


@pytest.mark.parametrize("status,body", [
    (200, {"ok": True, "accepted": True}),
    (200, {"ok": True}), (200, {"ok": True, "accepted": False}),
    (200, {"ok": 1, "accepted": True}), (200, {"ok": True, "accepted": 1}),
    (200, []), (200, None), (404, {"error": "unsupported"}),
    (409, {"error": "busy"}), (503, {"error": "display_alerts_gui_unavailable"}),
])
def test_real_http_transport_once(status, body):
    async def run():
        requests = []
        payload = {"id": "a" * 32, "notification_id": "test", "revision": "b" * 32,
                   "severity": "warning", "title": "Alert", "message": "Text",
                   "wake_duration": 30, "sound_duration": 30, "expires_in": 3600}

        async def receive(request):
            requests.append((request.method, request.path, request.headers.get("Authorization"), request.headers.get(HEADER_MAINTENANCE_TOKEN), await request.json()))
            return web.json_response(body, status=status)

        app = web.Application()
        app.router.add_post("/api/v1/display/alert", receive)
        async with TestServer(app) as server, ClientSession() as session:
            api = C300XAgentApi(session, str(server.make_url("")), "token", "maintenance")
            if status == 200 and body == {"ok": True, "accepted": True} and type(body["ok"]) is bool and type(body["accepted"]) is bool:
                assert await api.async_send_display_alert(payload) == body
            else:
                with pytest.raises(C300XAgentApiError):
                    await api.async_send_display_alert(payload)
        assert requests == [("POST", "/api/v1/display/alert", "Bearer token", None, payload)]
    asyncio.run(run())


def test_timeout_is_not_retried():
    calls = []

    class TimeoutSession:
        def request(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise TimeoutError

    api = C300XAgentApi(TimeoutSession(), "http://agent", "token")
    with pytest.raises(C300XAgentApiError, match="timed out"):
        asyncio.run(api.async_send_display_alert({"id": "a" * 32}))
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 8.0
