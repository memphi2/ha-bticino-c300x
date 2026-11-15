"""Measure exact Energy inspection data inside a realistic full dashboard."""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from test_energy_layout_harness import HARNESS
from test_executor import FakeHass, FakeState

from custom_components.bticino_c300x import dashboard, dashboard_agenda
from custom_components.bticino_c300x.dashboard_energy import EnergyMeter, EnergySources
from custom_components.bticino_c300x.dashboard_energy_power import PowerHistory, power_history_payload
from custom_components.bticino_c300x.display_notifications import DisplayNotifications


def maximum_energy():
    fixture = next(item for item in HARNESS.make_fixtures(include_consumers=True)
                   if item["language"] == "de" and item["name"] == "stress")
    start = datetime(2026, 10, 25, tzinfo=ZoneInfo("Europe/Berlin"))
    sources = EnergySources(
        grid_from=(EnergyMeter("grid"),), grid_power=("grid_power",),
        solar=(EnergyMeter("solar"),), solar_power=("solar_power",),
        battery_from=(EnergyMeter("battery"),), battery_power=("battery_power",),
    )
    raw = PowerHistory(start, start + timedelta(days=1), {
        "grid_power": tuple(index * 31.23456789 - 1234 for index in range(100)),
        "solar_power": tuple(index * 71.23456789 for index in range(100)),
        "battery_power": tuple(index * 21.23456789 - 1234 for index in range(100)),
    })
    fixture["energy"]["power"] = power_history_payload(sources, raw, "de")
    assert len(fixture["energy"]["sums"]) == 8
    assert len(fixture["energy"]["consumers"]["items"]) == 10
    return {"title": fixture["title"], "energy": fixture["energy"]}


@pytest.mark.parametrize("notifications", [0, 1, 8])
@pytest.mark.parametrize("localized", [False, True])
def test_energy_with_status_agenda_48_checks_and_notifications(monkeypatch, notifications, localized):
    energy = maximum_energy()
    contacts = [f"binary_sensor.ground_floor_window_{index:02d}" for index in range(24)]
    lights = [f"light.ground_floor_room_{index:02d}" for index in range(24)]
    entry = SimpleNamespace(entry_id="energy-budget", title="Energy budget", data={"device_ui_enabled": True},
                            options={"energy_page": {"enabled": True, "views": [view["id"] for view in energy["energy"]["views"]]},
                                     "agenda_page": {"enabled": True, "calendars": ["calendar.family"]},
                                     "leave_home_page": {"enabled": True, "contacts": contacts, "lights": lights}},
                            async_on_unload=lambda _callback: None,
                            async_create_background_task=lambda _hass, coro, _name, **_kwargs: asyncio.create_task(coro),
                            runtime_data=SimpleNamespace())
    hass = FakeHass()
    for index, entity_id in enumerate(contacts + lights):
        hass.states.values[entity_id] = FakeState("off", attributes={
            "friendly_name": (f"Wohnzimmerfenster S\u00fcdseite {index:02d}" if localized
                              else f"Ground floor living room window {index:02d}"), "device_class": "window",
        })
    hass.states.values["calendar.family"] = FakeState("on", attributes={"friendly_name": "Family calendar"})
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    hass.services.responses[("calendar", "get_events")] = {"calendar.family": {"events": [
        {"start": (now + timedelta(hours=index + 1)).isoformat(),
         "end": (now + timedelta(hours=index + 2)).isoformat(),
         "summary": ((f"Familientermin {index}: " + "Besuch bei Freunden in K\u00f6ln. " * 4) if localized
                     else (f"Family appointment {index}: " + "calendar description " * 5))[:100]}
        for index in range(5)
    ]}}
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(return_value=energy))

    async def render():
        store = DisplayNotifications(asyncio.get_running_loop(), lambda: None)
        entry.runtime_data.display_notifications = store
        try:
            for index in range(notifications):
                store.show({"notification_id": f"energy_budget_{index}",
                            "title": ("Hinweis f\u00fcr den Haushalt " if localized else "Household notification ") + str(index),
                            "message": (("Bitte pr\u00fcfen Sie vor dem Verlassen die Fenster und T\u00fcren. " if localized
                                         else "Please check the household before leaving. ") * 12)[:500],
                            "icon": "info", "priority": "normal", "expires_in": 3600,
                            "actions": [{"action_id": "household_action", "label": "Household action"}]})
            initial = await dashboard.async_dashboard_payload(hass, entry)
            assert next(page["agenda"] for page in initial["data"]["pages"] if "agenda" in page)["loading"] is True
            task = hass.data[dashboard_agenda._DATA_KEY][entry.entry_id].task
            assert task is not None
            await task
            loaded = await dashboard.async_dashboard_payload(hass, entry)
            assert next(page["agenda"] for page in loaded["data"]["pages"] if "agenda" in page)["loading"] is False
            return loaded
        finally:
            store.close()

    payload = asyncio.run(render())
    pages = payload["data"]["pages"]
    assert len(pages) == 4
    assert any(item["kind"] == "navigation" for page in pages for item in page.get("items", []))
    assert len(next(page["agenda"] for page in pages if "agenda" in page)["events"]) == 5
    assert len(next(page["leave_home"] for page in pages if "leave_home" in page)["checks"]) == 48
    assert len(payload["notifications"]) == notifications
    sizes = {"energy": len(json.dumps(energy)), "power": len(json.dumps(energy["energy"]["power"])),
             "dashboard": len(json.dumps(payload)), "notifications": len(json.dumps(payload["notifications"]))}
    print(f"localized={localized}, notifications={notifications}: {sizes}")
    assert sizes["dashboard"] <= dashboard.DASHBOARD_RESPONSE_MAX_BYTES, sizes
