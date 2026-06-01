from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
webhook = types.ModuleType("homeassistant.components.webhook")
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers_dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
helpers_event = types.ModuleType("homeassistant.helpers.event")
helpers_entity = types.ModuleType("homeassistant.helpers.entity")
helpers_entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
helpers_config_validation = types.ModuleType("homeassistant.helpers.config_validation")
core = types.ModuleType("homeassistant.core")


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


class DeviceInfo(dict):  # pragma: no cover - import-time stub only
    pass


class Entity:  # pragma: no cover - import-time stub only
    pass


class _ScheduledCall:
    def __init__(self, delay: int, callback: Any) -> None:
        self.delay = delay
        self.callback = callback
        self.canceled = False

    def __call__(self) -> None:
        self.canceled = True


class _FakeDispatcher:
    def __init__(self) -> None:
        self.signals: list[tuple[str, str]] = []

    def async_dispatcher_send(self, hass: HomeAssistant, signal: str, entry_id: str) -> None:
        self.signals.append((signal, entry_id))


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[_ScheduledCall] = []

    def async_call_later(
        self,
        hass: HomeAssistant,
        delay: int,
        callback: Any,
    ) -> _ScheduledCall:
        call = _ScheduledCall(delay, callback)
        self.calls.append(call)
        return call

    def reset(self) -> None:
        self.calls = []


fake_dispatcher = _FakeDispatcher()
fake_scheduler = _FakeScheduler()
webhook_calls: list[tuple[str, dict[str, Any]]] = []


def _webhook_url(_: HomeAssistant, webhook_id: str, **kwargs: Any) -> str:
    webhook_calls.append((webhook_id, kwargs))
    return f"http://localhost:8123/webhook/{webhook_id}"


webhook.async_generate_url = _webhook_url
helpers_dispatcher.async_dispatcher_send = fake_dispatcher.async_dispatcher_send
helpers_dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
helpers_event.async_call_later = fake_scheduler.async_call_later
helpers_entity.DeviceInfo = DeviceInfo
helpers_entity.Entity = Entity
helpers_entity_registry.EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
helpers_entity_registry.async_get = lambda hass: getattr(hass, "entity_registry", None)
helpers_config_validation.config_entry_only_config_schema = lambda _domain: dict

components.webhook = webhook
helpers.dispatcher = helpers_dispatcher
helpers.event = helpers_event
helpers.entity = helpers_entity
helpers.entity_registry = helpers_entity_registry
helpers.config_validation = helpers_config_validation
core.HomeAssistant = HomeAssistant
core.CALLBACK_TYPE = type(_ScheduledCall(0, lambda *args, **kwargs: None))
core.callback = lambda func: func
config_entries.ConfigEntry = ConfigEntry
homeassistant.components = components
sys.modules["homeassistant.components.webhook"] = webhook
sys.modules["homeassistant.helpers.dispatcher"] = helpers_dispatcher
sys.modules["homeassistant.helpers.event"] = helpers_event
sys.modules["homeassistant.helpers.entity"] = helpers_entity
sys.modules["homeassistant.helpers.entity_registry"] = helpers_entity_registry
sys.modules["homeassistant.helpers.config_validation"] = helpers_config_validation
sys.modules["homeassistant.core"] = core


@pytest.fixture(autouse=True)
def restore_webhook_stub() -> None:
    components.webhook = webhook
    sys.modules["homeassistant.components.webhook"] = webhook
    webhook.async_generate_url = _webhook_url

from custom_components.bticino_c300x.events import (  # noqa: E402,I001
    _filter_events_for_active_entities,
    async_start_agent_event_registration,
    event_token_fingerprint,
)
from custom_components.bticino_c300x import events as events_module  # noqa: E402


class _FakeApi:
    def __init__(
        self,
        responses: list[Any],
        *,
        subscriptions: list[dict[str, Any]] | Exception | None = None,
        subscription_lists: list[list[dict[str, Any]] | Exception] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.subscriptions = subscriptions
        self.subscription_lists = list(subscription_lists or [])
        self.list_calls = 0
        self.subscription_calls: list[tuple[str, str, list[str]]] = []
        self.delete_calls: list[str] = []

    async def async_list_event_subscriptions(self) -> dict[str, Any]:
        self.list_calls += 1
        if self.subscription_lists:
            response_or_error = self.subscription_lists.pop(0)
            if isinstance(response_or_error, Exception):
                raise response_or_error
            return {"subscriptions": response_or_error}
        if isinstance(self.subscriptions, Exception):
            raise self.subscriptions
        return {"subscriptions": self.subscriptions or []}

    async def async_register_event_subscription(
        self,
        *,
        callback_url: str,
        token: str,
        events: list[str],
    ) -> Any:
        self.subscription_calls.append((callback_url, token, list(events)))
        response_or_error = self.responses.pop(0)
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    async def async_delete_event_subscription(self, subscription_id: str) -> None:
        self.delete_calls.append(subscription_id)


@dataclass
class _FakeConnectionState:
    available: bool = True
    connection_state: str = "connected"
    reconnect_count: int = 0
    last_connection_error: str | None = None
    last_reconnect_reason: str | None = None
    next_reconnect_delay_seconds: int | None = None
    was_reconnecting: bool = False
    expire_unavailable: Any = None

    def mark_connected(self) -> None:
        self.available = True
        self.connection_state = "connected"
        self.next_reconnect_delay_seconds = None
        self.was_reconnecting = False
        if self.expire_unavailable is not None:
            self.expire_unavailable()
            self.expire_unavailable = None

    def mark_reconnecting(self, reason: str, next_delay_seconds: int, error: str) -> None:
        self.connection_state = "reconnecting"
        self.last_reconnect_reason = reason
        self.last_connection_error = error
        self.next_reconnect_delay_seconds = next_delay_seconds
        self.was_reconnecting = True

    def mark_unavailable(self) -> None:
        if self.connection_state == "reconnecting":
            self.available = False


class _FakeHass(HomeAssistant):
    def __init__(self) -> None:
        self.async_tasks: list[asyncio.Task[Any]] = []
        self.bus = _FakeBus()

    def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self.async_tasks.append(task)
        return task


class _FakeBus:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}

    def async_listen(self, event_type: str, callback: Any) -> Any:
        callbacks = self.listeners.setdefault(event_type, [])
        callbacks.append(callback)

        def _cancel() -> None:
            if callback in callbacks:
                callbacks.remove(callback)

        return _cancel

    def fire(self, event_type: str) -> None:
        for callback in list(self.listeners.get(event_type, [])):
            callback(types.SimpleNamespace(event_type=event_type, data={}))


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    options: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(
        default_factory=lambda: {
            "event_webhook_id": "event-hook",
            "event_webhook_token": "event-token",
        },
    )


class _FakeEntityRegistry:
    def __init__(self, *, disabled: set[tuple[str, str]] | None = None) -> None:
        self.disabled = disabled or set()

    def async_get_entity_id(
        self,
        domain: str,
        platform: str,
        unique_id: str,
    ) -> str | None:
        return f"{domain}.{unique_id}"

    def async_get(self, entity_id: str) -> Any:
        domain, unique_id = entity_id.split(".", 1)
        suffix = unique_id.split("_", 1)[1]
        disabled_by = "user" if (domain, suffix) in self.disabled else None
        return types.SimpleNamespace(disabled_by=disabled_by)


def test_async_start_agent_event_registration_reuses_persisted_subscription() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscriptions=[
            {
                "id": "sub-a",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("event-token"),
                "events": ["agent.restarted"],
            }
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()
    webhook_calls.clear()

    asyncio.run(
        async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            _FakeConnectionState(),
        )
    )

    assert api.list_calls == 1
    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]
    assert webhook_calls == [
        (
            "event-hook",
            {
                "allow_external": False,
                "allow_internal": True,
                "prefer_external": False,
            },
        )
    ]
    assert fake_scheduler.calls == []


def test_async_start_agent_event_registration_replaces_duplicate_subscriptions() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscriptions=[
            {
                "id": "sub-a",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("event-token"),
                "events": ["agent.restarted"],
            },
            {
                "id": "sub-old",
                "callback_url": "http://old-ha.local:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("event-token"),
                "events": ["agent.restarted"],
            },
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()
    webhook_calls.clear()

    asyncio.run(
        async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            _FakeConnectionState(),
        )
    )

    assert api.list_calls == 1
    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]
    assert fake_scheduler.calls == []


def test_filter_events_for_active_entities_skips_disabled_internal_diagnostics() -> None:
    assert _filter_events_for_active_entities(
        ["agent.diagnostics_changed", "agent.restarted"],
        "entry-1",
        _FakeEntityRegistry(
            disabled={
                ("sensor", "agent_writes"),
                ("event", "agent_event"),
            }
        ),
    ) == []


def test_filter_events_for_active_entities_keeps_metric_event_for_active_metric_sensor() -> None:
    assert _filter_events_for_active_entities(
        ["system.metrics_changed"],
        "entry-1",
        _FakeEntityRegistry(
            disabled={
                ("sensor", "device_cpu"),
                ("sensor", "device_load"),
                ("sensor", "device_temperature"),
            }
        ),
    ) == ["system.metrics_changed"]


def test_filter_events_for_active_entities_keeps_visible_event_for_event_entity() -> None:
    assert _filter_events_for_active_entities(
        ["door_unlock.started"],
        "entry-1",
        _FakeEntityRegistry(),
    ) == ["door_unlock.started"]


def test_async_start_agent_event_registration_registers_when_missing() -> None:
    api = _FakeApi([{"subscription": {"id": "sub-a"}}])
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()
    webhook_calls.clear()

    asyncio.run(
        async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            _FakeConnectionState(),
        )
    )

    assert api.list_calls == 1
    assert len(api.subscription_calls) == 1
    assert fake_scheduler.calls == []


def test_async_start_agent_event_registration_updates_event_set_mismatch() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscriptions=[
            {
                "id": "old-sub",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "events": [],
            }
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()

    connection_state = _FakeConnectionState()
    asyncio.run(
        async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            connection_state,
        )
    )

    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]
    assert api.delete_calls == []
    assert connection_state.connection_state == "connected"


def test_event_registration_removes_stale_subscriptions_when_no_events_are_active() -> None:
    api = _FakeApi(
        [],
        subscriptions=[
            {
                "id": "old-current-token-sub",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("event-token"),
                "events": ["agent.restarted"],
            },
            {
                "id": "old-rotated-token-sub",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("rotated-token"),
                "events": ["agent.restarted"],
            },
            {
                "id": "other-sub",
                "callback_url": "http://localhost:8123/webhook/other",
                "token_fingerprint": event_token_fingerprint("event-token"),
                "events": ["agent.restarted"],
            },
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()
    original_active_events = events_module._active_events_for_capabilities
    events_module._active_events_for_capabilities = lambda *args: []
    try:
        asyncio.run(
            async_start_agent_event_registration(
                hass,
                _FakeEntry(),  # type: ignore[arg-type]
                api,
                {},
                _FakeConnectionState(),
            )
        )
    finally:
        events_module._active_events_for_capabilities = original_active_events

    assert api.subscription_calls == []
    assert api.delete_calls == ["old-current-token-sub", "old-rotated-token-sub"]
    assert fake_scheduler.calls == []


def test_event_registration_recomputes_when_entity_registry_changes() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscription_lists=[
            [],
            [
                {
                    "id": "sub-a",
                    "callback_url": "http://localhost:8123/webhook/event-hook",
                    "token_fingerprint": event_token_fingerprint("event-token"),
                    "events": ["agent.restarted"],
                }
            ],
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()
    active_event_sets = [["agent.restarted"], []]
    original_active_events = events_module._active_events_for_capabilities
    events_module._active_events_for_capabilities = lambda *args: active_event_sets.pop(0)
    try:
        async def run() -> None:
            unregister = await async_start_agent_event_registration(
                hass,
                _FakeEntry(),  # type: ignore[arg-type]
                api,
                {},
                _FakeConnectionState(),
            )
            await asyncio.sleep(0)
            assert unregister is not None
            hass.bus.fire("entity_registry_updated")
            refresh_calls = [
                call
                for call in fake_scheduler.calls
                if call.delay == events_module._ENTITY_REGISTRY_REFRESH_SECONDS
            ]
            assert len(refresh_calls) == 1
            await refresh_calls[0].callback()
            await asyncio.sleep(0)
            unregister()

        asyncio.run(run())
    finally:
        events_module._active_events_for_capabilities = original_active_events

    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]
    assert api.delete_calls == ["sub-a"]


def test_async_start_agent_event_registration_updates_token_mismatch() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscriptions=[
            {
                "id": "old-sub",
                "callback_url": "http://localhost:8123/webhook/event-hook",
                "token_fingerprint": event_token_fingerprint("old-event-token"),
                "events": ["agent.restarted"],
            }
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()

    asyncio.run(
        async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            _FakeConnectionState(),
        )
    )

    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]


def test_async_start_agent_event_registration_reconnects_with_backoff() -> None:
    api = _FakeApi([RuntimeError("down"), {"subscription": {"id": "sub-ok"}}])
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()

    connection_state = _FakeConnectionState()
    async def start() -> None:
        await async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            connection_state,
        )
        await asyncio.sleep(0)

    asyncio.run(start())
    assert connection_state.connection_state == "reconnecting"
    assert connection_state.next_reconnect_delay_seconds == 30
    assert len(fake_scheduler.calls) == 2
    assert sorted(call.delay for call in fake_scheduler.calls) == [15, 30]

    retry_callback = fake_scheduler.calls[1].callback
    asyncio.run(retry_callback())
    asyncio.run(asyncio.sleep(0))

    assert connection_state.connection_state == "connected"
    assert connection_state.next_reconnect_delay_seconds is None


def test_event_registration_waits_for_offline_agent_before_reusing_subscription() -> None:
    api = _FakeApi(
        [{"subscription": {"id": "sub-a"}}],
        subscription_lists=[
            RuntimeError("agent offline"),
            [
                {
                    "id": "sub-a",
                    "callback_url": "http://localhost:8123/webhook/event-hook",
                    "token_fingerprint": event_token_fingerprint("event-token"),
                    "events": ["agent.restarted"],
                }
            ],
        ],
    )
    hass = _FakeHass()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()

    connection_state = _FakeConnectionState()

    async def start() -> None:
        await async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            connection_state,
        )
        await asyncio.sleep(0)

    asyncio.run(start())

    assert api.list_calls == 1
    assert api.subscription_calls == []
    assert connection_state.connection_state == "reconnecting"

    retry_callback = fake_scheduler.calls[1].callback
    asyncio.run(retry_callback())
    asyncio.run(asyncio.sleep(0))

    assert api.list_calls == 2
    assert api.subscription_calls == [
        ("http://localhost:8123/webhook/event-hook", "event-token", ["agent.restarted"]),
    ]
    assert connection_state.connection_state == "connected"


def test_event_registration_persists_subscription_on_unload() -> None:
    api = _FakeApi([{"subscription": {"id": "sub-leak"}}])
    hass = _FakeHass()
    connection_state = _FakeConnectionState()
    fake_dispatcher.signals.clear()
    fake_scheduler.reset()

    async def run_unload() -> None:
        unregister = await async_start_agent_event_registration(
            hass,
            _FakeEntry(),  # type: ignore[arg-type]
            api,
            {},
            connection_state,
        )
        await asyncio.sleep(0)
        assert unregister is not None
        unregister()
        await asyncio.sleep(0)
        if hass.async_tasks:
            await asyncio.gather(*hass.async_tasks, return_exceptions=True)

    asyncio.run(run_unload())
    assert not any(call.delay for call in fake_scheduler.calls if not call.canceled)
    assert api.delete_calls == []
