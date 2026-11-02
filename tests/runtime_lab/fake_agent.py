"""Loopback-only agent protocol fixture; never opens a device connection."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from custom_components.bticino_c300x.events import event_token_fingerprint

TOKEN = "synthetic-agent-token"
EVENT_TOKEN = "synthetic-event-token"


class FakeAgent:
    """Serve real API requests and deliver real HTTP webhook callbacks."""

    def __init__(self) -> None:
        self.requests: Counter[tuple[str, str]] = Counter()
        self.unexpected: list[tuple[str, str]] = []
        self.subscriptions: list[dict] = []
        self.fail_list = False
        self.hold_list: asyncio.Event | None = None
        self.list_started = asyncio.Event()
        self.muted = False
        self.sequence = 0
        self.instance = "0123456789abcdef0123456789abcdef"
        self.memo_text = "Synthetic private memo"
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.server = TestServer(app, host="127.0.0.1")

    async def __aenter__(self):
        await self.server.start_server()
        return self

    async def __aexit__(self, *_):
        if self.hold_list is not None:
            self.hold_list.set()
        await self.server.close()

    def metrics(self) -> dict:
        self.sequence += 1
        return {
            "instance_id": self.instance,
            "sample_sequence": self.sequence,
            "sample_age_ms": 0,
            "sample_interval_seconds": 30,
            "sample_interval_ms": 30000,
            "heartbeat_seconds": 600,
            "cpu_usage_percent": 1.0,
            "memory_usage_percent": 20.0,
            "temperature_c": 35.0,
        }

    async def handle(self, request: web.Request) -> web.Response:
        key = request.method, request.path
        self.requests[key] += 1
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            raise web.HTTPUnauthorized()
        body = await request.json() if request.can_read_body else {}
        if key == ("GET", "/api/v1/capabilities"):
            return web.json_response(
                {
                    "api_version": "1",
                    "agent": {"version": "1.9.11", "implementation": "native-c"},
                    "device": {"model": "C300X", "firmware": "synthetic"},
                    "capabilities": {
                        "doorbell_events": True,
                        "ringer": True,
                        "stair_light": True,
                        "locks": {"supported": True, "default_id": "default"},
                        "system_metrics": {
                            "supported": True,
                            "cpu": True,
                            "memory": True,
                            "temperature": True,
                            "load": True,
                        },
                        "diagnostics": True,
                        "memos": True,
                        "doorbell_video": {"supported": True},
                    },
                }
            )
        if key == ("GET", "/api/v1/events/subscriptions"):
            self.list_started.set()
            if self.hold_list is not None:
                await self.hold_list.wait()
            if self.fail_list:
                request.transport.close()
                return web.Response()
            return web.json_response({"subscriptions": self.subscriptions})
        if key == ("POST", "/api/v1/events/subscriptions"):
            subscription = {
                **body,
                "id": "synthetic-subscription",
                "token_fingerprint": event_token_fingerprint(body.pop("token")),
            }
            subscription.pop("token", None)
            self.subscriptions = [subscription]
            return web.json_response({"subscription": subscription}, status=201)
        if key == ("GET", "/api/v1/maintenance/auth"):
            return web.json_response(
                {"activations_enabled": True, "activations_auto_discover": True}
            )
        if key == ("GET", "/api/v1/activations"):
            return web.json_response({"items": []})
        if key == ("GET", "/api/v1/display-bridge"):
            return web.json_response({"configured": False, "enabled": False})
        if key == ("GET", "/api/v1/self-test"):
            return web.json_response({"ok": True, "checks": {}})
        if key == ("GET", "/api/v1/diagnostics"):
            return web.json_response(
                {
                    "ok": True,
                    "diagnostics": {
                        "agent_write_count": 0,
                        "subscription_count": len(self.subscriptions),
                        "loop_iterations": 100,
                        "open_fd_count": 8,
                    },
                }
            )
        if key == ("GET", "/api/v1/system/metrics"):
            return web.json_response(self.metrics())
        if request.path == "/api/v1/ringer" and request.method in {"GET", "POST"}:
            self.muted = body.get("muted", self.muted)
            return web.json_response({"muted": self.muted, "volume": 5})
        if key == ("GET", "/api/v1/memos"):
            return web.json_response(
                {
                    "memos": [
                        {
                            "id": "memo-1",
                            "kind": "text",
                            "text": self.memo_text,
                            "created_at": "2026-01-01T12:00:00Z",
                        }
                    ]
                }
            )
        if key in {
            ("POST", "/api/v1/locks/default/actions/unlock"),
            ("POST", "/api/v1/stair-light/actions/activate"),
        }:
            return web.json_response({"ok": True})
        self.unexpected.append(key)
        raise web.HTTPNotImplemented(text="Unexpected synthetic agent request")

    async def push(
        self, callback_url: str, event_type: str, data: dict, *, token=EVENT_TOKEN
    ):
        self.sequence += 1
        async with (
            ClientSession() as session,
            session.post(
                callback_url,
                json={
                    "event_id": f"synthetic-{self.sequence}",
                    "type": event_type,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "data": data,
                    "ttl_seconds": 0,
                },
                headers={"X-Bticino-C300X-Event-Token": token},
            ) as response,
        ):
            return response.status, await response.text()
