"""Bounded, transient HA-owned messages for the native display."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant

from .capabilities import entry_device_ui_enabled_or_patch_active
from .dashboard_config import configured_actions
from .entry_types import BticinoC300XConfigEntry
from .schema_compat import vol

MAX_NOTIFICATIONS = 8
MAX_NOTIFICATION_BYTES = 16384
NOTIFICATION_PREFIX = "notification."
_PRIORITY = {"normal": 0, "important": 1, "urgent": 2}


def notification_id(value: Any) -> str:
    """Keep identifiers compatible with the existing bounded display route."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", value):
        raise vol.Invalid(
            "notification_id must contain 1-64 lowercase letters, digits, _ or -"
        )
    return value


def _text(limit: int) -> Callable[[Any], str]:
    def validate(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise vol.Invalid(f"expected nonempty text up to {limit} characters")
        return value.strip()

    return validate


SHOW_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Required("notification_id"): notification_id,
        vol.Required("title"): _text(80),
        vol.Required("message"): _text(500),
        vol.Optional("icon", default="info"): vol.In({"info", "warning", "calendar"}),
        vol.Optional("priority", default="normal"): vol.In(set(_PRIORITY)),
        vol.Optional("expires_in", default=3600): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=604800)
        ),
        vol.Optional("actions", default=list): vol.All(
            [
                vol.Schema(
                    {
                        vol.Required("action_id"): _text(64),
                        vol.Required("label"): _text(40),
                    }
                )
            ],
            vol.Length(max=2),
        ),
    }
)
DISMISS_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): str,
        vol.Required("notification_id"): notification_id,
    }
)


class DisplayNotifications:
    """One expiry timer in HA; no device files, history, or periodic polling."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, notify: Callable[[], None]
    ) -> None:
        self._loop = loop
        self._notify = notify
        self._items: dict[str, dict[str, Any]] = {}
        self._sequence = 0
        self._expiry: asyncio.TimerHandle | None = None
        self.closed = False
        self.busy: set[str] = set()

    def show(self, data: dict[str, Any]) -> None:
        if self.closed:
            raise ValueError("display_notifications_unloaded")
        self._purge()
        key = data["notification_id"]
        candidate = dict(self._items)
        candidate[key] = {
            "id": key,
            "revision": uuid4().hex,
            "sequence": self._sequence + 1,
            "title": data["title"],
            "message": data["message"],
            "icon": data["icon"],
            "priority": data["priority"],
            "actions": [dict(action) for action in data["actions"]],
            "deadline": self._loop.time() + data["expires_in"],
        }
        # Budget escaped JSON too: Unicode text can expand in the native response.
        while (
            len(candidate) > MAX_NOTIFICATIONS
            or len(json.dumps(list(candidate.values()))) > MAX_NOTIFICATION_BYTES
        ):
            victims = [
                other
                for other in candidate
                if other != key
                and _PRIORITY[candidate[other]["priority"]]
                <= _PRIORITY[data["priority"]]
            ]
            if not victims:
                raise ValueError("display_notification_queue_full")
            oldest = min(
                victims,
                key=lambda other: (
                    _PRIORITY[candidate[other]["priority"]],
                    candidate[other]["sequence"],
                ),
            )
            del candidate[oldest]
        self._sequence += 1
        self._items = candidate
        self._schedule()
        self._notify()

    def dismiss(self, key: str) -> None:
        if self._items.pop(key, None) is not None:
            self._schedule()
            self._notify()

    def payload(self) -> list[dict[str, Any]]:
        self._purge()
        return [
            {
                key: value
                for key, value in item.items()
                if key not in {"deadline", "sequence"}
            }
            for item in sorted(
                self._items.values(),
                key=lambda item: (
                    -_PRIORITY[item["priority"]],
                    -item["sequence"],
                ),
            )
        ]

    def close(self) -> None:
        self.closed = True
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        self._items.clear()

    def _purge(self) -> None:
        expired = [
            key
            for key, item in self._items.items()
            if item["deadline"] <= self._loop.time()
        ]
        for key in expired:
            del self._items[key]
        if expired:
            self._notify()

    def _schedule(self) -> None:
        if self._expiry is not None:
            self._expiry.cancel()
            self._expiry = None
        if self._items and not self.closed:
            next_deadline = min(item["deadline"] for item in self._items.values())
            self._expiry = self._loop.call_at(next_deadline, self._expire)

    def _expire(self) -> None:
        self._expiry = None
        self._purge()
        self._schedule()


def notifications_for_entry(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry
) -> DisplayNotifications:
    """Create the store only when an automation first uses notifications."""
    from .runtime_manager import _async_schedule_display_bridge_notify

    if not entry_device_ui_enabled_or_patch_active(entry):
        raise ValueError("display_disabled")
    store = getattr(entry.runtime_data, "display_notifications", None)
    if store is None:
        store = DisplayNotifications(
            hass.loop,
            lambda: _async_schedule_display_bridge_notify(
                hass, entry, notifications=True
            ),
        )
        entry.runtime_data.display_notifications = store
        entry.runtime_data.resources.close_display_notifications = store.close
    return store


def notification_payload(entry: BticinoC300XConfigEntry) -> list[dict[str, Any]]:
    store = getattr(getattr(entry, "runtime_data", None), "display_notifications", None)
    return store.payload() if store is not None else []


def show_notification(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, data: dict[str, Any]
) -> None:
    data = SHOW_SCHEMA(data)
    allowed = configured_actions(entry)
    if any(action["action_id"] not in allowed for action in data["actions"]):
        raise ValueError("unknown_notification_action")
    notifications_for_entry(hass, entry).show(data)


async def async_notification_action(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    key: str,
    option: str | None,
) -> dict[str, Any]:
    """Resolve a revision-checked message action, never a client service target."""
    from .executor import async_execute_action

    notification_id(key)
    store = notifications_for_entry(hass, entry)
    try:
        command = json.loads(option or "")
    except (ValueError, TypeError) as err:
        raise ValueError("invalid_notification_action") from err
    if (
        not isinstance(command, dict)
        or set(command) != {"revision", "action_id"}
        or not isinstance(command["revision"], str)
    ):
        raise ValueError("invalid_notification_action")
    item = next((item for item in store.payload() if item["id"] == key), None)
    if (
        not isinstance(command, dict)
        or item is None
        or command.get("revision") != item["revision"]
    ):
        raise ValueError("stale_notification")
    if key in store.busy:
        raise ValueError("notification_action_pending")
    action_id = command.get("action_id")
    if action_id is None:
        store.dismiss(key)
        return {"ok": True}
    if not isinstance(action_id, str) or action_id not in {
        action["action_id"] for action in item["actions"]
    }:
        raise ValueError("unknown_notification_action")
    store.busy.add(key)
    try:
        await async_execute_action(hass, entry, action_id)
    finally:
        store.busy.discard(key)
    return {"ok": True}
