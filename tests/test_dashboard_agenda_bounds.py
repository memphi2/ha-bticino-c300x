"""Calendar output limits also bound processing and permit cancellation."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.core import State
from test_dashboard_optional_pages import NOW, environment, event, loaded_page

from custom_components.bticino_c300x import dashboard_agenda as agenda


def setup_calendar(monkeypatch, events):
    monkeypatch.setattr(agenda.dt_util, "utcnow", lambda: NOW)
    hass, entry, callbacks = environment(
        {"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}},
        {"calendar.one": State("calendar.one", "off")},
    )
    hass.services.async_call.return_value = {"calendar.one": {"events": events}}
    return hass, entry, callbacks


def test_oversize_provider_response_is_failed_not_partial_success(monkeypatch):
    hass, entry, _ = setup_calendar(monkeypatch, [event(1)] * (agenda.MAX_PROVIDER_EVENTS + 1))
    page = asyncio.run(loaded_page(hass, entry))["agenda"]
    assert page["error"] and not page["events"]


def test_processing_yields_to_loop_and_unload(monkeypatch):
    hass, entry, callbacks = setup_calendar(monkeypatch, [event(1)] * agenda.MAX_PROVIDER_EVENTS)

    async def run():
        await agenda.async_agenda_dashboard_page(hass, entry)
        task = hass.data[agenda._DATA_KEY][entry.entry_id].task
        await asyncio.sleep(0)
        assert not task.done()
        callbacks[-1]()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not hass.data

    asyncio.run(run())


def test_processing_remains_inside_fetch_timeout(monkeypatch):
    hass, entry, _ = setup_calendar(monkeypatch, [event(1)] * agenda.MAX_PROVIDER_EVENTS)
    monkeypatch.setattr(agenda, "FETCH_TIMEOUT", 0)
    page = asyncio.run(loaded_page(hass, entry))["agenda"]
    assert page["error"] and not page["events"]


def test_next_five_considers_final_batch_and_bounds_field_processing():
    events = [event(20)] * (agenda.EVENT_BATCH_SIZE * 2) + [event(1, "Earliest")]
    result = asyncio.run(agenda._events(events, "calendar.one", "One", NOW, NOW + timedelta(days=7)))
    assert result[0]["summary"] == "Earliest"
    assert len(result) == 5
    assert agenda._event_time("2" * 10000) is None
    assert agenda._text("x" * 10000, 80) == "x" * 80
    assert agenda._text({"unexpected": "object"}, 80) == ""
