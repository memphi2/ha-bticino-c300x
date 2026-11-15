"""Actual display webhook bytes stay bounded without losing safety checks."""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_energy_payload_budget import maximum_energy
from test_executor import FakeHass, FakeState
from test_webhook import _FakeRequest

from custom_components.bticino_c300x import dashboard, dashboard_agenda, webhook
from custom_components.bticino_c300x.dashboard_leave_home import (
    leave_home_dashboard_page,
)
from custom_components.bticino_c300x.dashboard_response import (
    DASHBOARD_RESPONSE_MAX_BYTES,
    dashboard_response_size,
    display_json_dumps,
)
from custom_components.bticino_c300x.display_notifications import DisplayNotifications


def environment(character="\u00fc", combined=False, dense_names=True):
    contacts = [f"binary_sensor.{'a' * 70}{index:02d}" for index in range(24)]
    lights = [f"light.{'a' * 70}{index:02d}" for index in range(24)]
    entry = SimpleNamespace(
        entry_id="wire-budget", title="Wire budget", runtime_data=SimpleNamespace(),
        data={"device_ui_enabled": True, "shared_secret": "secret"},
        options={"leave_home_page": {"enabled": True, "contacts": contacts, "lights": lights}},
        async_on_unload=lambda _callback: None,
        async_create_background_task=lambda _hass, coro, _name, **_kwargs: asyncio.create_task(coro),
    )
    hass = FakeHass()
    hass.config.language = "en"
    name = character * 80 if dense_names else "Window " + character + " south side"
    for index, entity_id in enumerate(contacts + lights):
        hass.states.values[entity_id] = FakeState(
            ("on", "off", "unavailable")[index % 3],
            attributes={"friendly_name": name, "device_class": "window"},
        )
    if combined:
        actions = {f"leave_{index}": {"name": name, "domain": "script", "service": "turn_on",
                                      "target": {"entity_id": f"script.leave_{index}"}} for index in range(8)}
        entry.options.update({
            "energy_page": {"enabled": True},
            "agenda_page": {"enabled": True, "calendars": ["calendar.family"]},
            "alarm_entity_id": "alarm_control_panel.home", "actions": actions,
        })
        entry.options["leave_home_page"].update({"actions": list(actions), "show_alarm": True})
        hass.states.values["alarm_control_panel.home"] = FakeState("armed_away")
        hass.states.values["calendar.family"] = FakeState("on", attributes={"friendly_name": character * 80})
        now = datetime.now(UTC)
        hass.services.responses[("calendar", "get_events")] = {"calendar.family": {"events": [
            {"start": (now + timedelta(hours=index + 1)).isoformat(),
             "end": (now + timedelta(hours=index + 2)).isoformat(), "summary": character * 100}
            for index in range(5)
        ]}}
    return hass, entry


async def response(hass, entry):
    return await webhook._async_handle_webhook(hass, entry, _FakeRequest(
        "", {"type": "dashboard"}, extra_headers={webhook.HEADER_SHARED_SECRET: "secret"},
    ))


@pytest.mark.parametrize("character", ["\u00fc", "\u7a97", "\U0001f3e0"])
def test_long_ids_and_unicode_48_checks_fit_actual_webhook(character):
    hass, entry = environment(character)
    projected = leave_home_dashboard_page(hass, entry)["leave_home"]
    assert len(projected["checks"]) == 48
    assert projected["attention_count"] == 32
    assert all(set(check) == {"name", "state_label", "color"} for check in projected["checks"])
    assert [check["state_label"] for check in projected["checks"][:3]] == ["Open", "Closed", "Unavailable"]
    assert [check["color"] for check in projected["checks"][:3]] == ["#ff6b6b", "#58d68d", "#ffd166"]
    result = asyncio.run(response(hass, entry))
    assert result.status == 200
    assert len(result.body) <= DASHBOARD_RESPONSE_MAX_BYTES
    decoded = json.loads(result.body)
    sent = next(page["leave_home"] for page in decoded["data"]["pages"] if "leave_home" in page)
    assert sent == projected
    assert character.encode() in result.body
    assert len(result.body) == dashboard_response_size(decoded)
    legacy = copy.deepcopy(decoded)
    checks = next(page["leave_home"]["checks"] for page in legacy["data"]["pages"] if "leave_home" in page)
    settings = entry.options["leave_home_page"]
    for index, (check, entity_id) in enumerate(zip(checks, settings["contacts"] + settings["lights"], strict=True)):
        check.update({"entity_id": entity_id, "kind": "contacts" if index < 24 else "lights",
                      "state": ("on", "off", "unavailable")[index % 3], "attention": index % 3 != 1})
    assert len(json.dumps(legacy).encode()) > 32 * 1024


@pytest.mark.parametrize("extra", [0, 1])
def test_revision_and_utf8_bytes_are_included_at_exact_boundary(monkeypatch, extra):
    hass, entry = environment()
    payload = {"data": {"pages": [{"title": "\u00fc" * 100}]}}
    payload["padding"] = "a" * (DASHBOARD_RESPONSE_MAX_BYTES - dashboard_response_size(payload) - len(',"padding":""') + extra)

    async def project(*_args):
        return dashboard._fit_dashboard_response(entry, copy.deepcopy(payload))

    monkeypatch.setattr(webhook, "async_dashboard_payload", project)
    result = asyncio.run(response(hass, entry))
    assert result.status == (400 if extra else 200)
    if extra:
        assert json.loads(result.body) == {"ok": False, "error": "dashboard_too_large"}
    else:
        assert len(result.body) == DASHBOARD_RESPONSE_MAX_BYTES
        decoded = json.loads(result.body)
        decoded.pop("revision")
        assert decoded == payload


@pytest.mark.parametrize("character,dense_names,expected_status", [
    ("\u00fc", False, 200), ("\u00fc", True, 400), ("\U0001f3e0", True, 400),
])
def test_combined_energy_agenda_actions_alarm_and_notices_actual_wire(monkeypatch, character, dense_names, expected_status):
    hass, entry = environment(character, combined=True, dense_names=dense_names)
    energy = maximum_energy()
    original_energy = copy.deepcopy(energy)
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(return_value=energy))

    async def render():
        store = DisplayNotifications(asyncio.get_running_loop(), lambda: None)
        entry.runtime_data.display_notifications = store
        try:
            for index in range(8):
                store.show({"notification_id": f"notice_{index}", "title": character * 10,
                            "message": character * 100 + "x" * 400, "icon": "info", "priority": "normal",
                            "expires_in": 3600, "actions": []})
            await dashboard_agenda.async_agenda_dashboard_page(hass, entry)
            await hass.data[dashboard_agenda._DATA_KEY][entry.entry_id].task
            return await response(hass, entry)
        finally:
            store.close()

    result = asyncio.run(render())
    assert result.status == expected_status
    assert len(result.body) <= DASHBOARD_RESPONSE_MAX_BYTES
    assert energy == original_energy
    decoded = json.loads(result.body)
    if expected_status == 400:
        assert decoded == {"ok": False, "error": "dashboard_too_large"}
        return
    pages = decoded["data"]["pages"]
    assert next(page["energy"] for page in pages if "energy" in page) == original_energy["energy"]
    leave = next(page["leave_home"] for page in pages if "leave_home" in page)
    assert leave == leave_home_dashboard_page(hass, entry)["leave_home"]
    assert len(leave["checks"]) == 48 and len(leave["actions"]) == 8
    assert leave["alarm"]["state"] == "armed_away"
    agenda = next(page["agenda"] for page in pages if "agenda" in page)
    assert len(agenda["events"]) == 5 and agenda["loading"] is False
    assert len(decoded["notifications"]) == 8
    assert all(notice["message"] == character * 100 + "x" * 400 for notice in decoded["notifications"])


def test_serializer_preserves_json_values():
    original = {"names": ["\u00fc", "\u7a97", "\U0001f3e0"], "state": None, "available": False,
                "history": [0, -1.23456789, None, 1e100]}
    assert json.loads(display_json_dumps(original)) == original
