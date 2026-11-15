"""Agenda reads are HA-only; departure checks never execute actions."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import dashboard_agenda as agenda
from custom_components.bticino_c300x import dashboard_leave_home as leave
from custom_components.bticino_c300x import runtime_manager
from custom_components.bticino_c300x.dashboard_updates import (
    dashboard_state_event_changes_display,
)

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def environment(options=None, states=None):
    callbacks = []
    entry = SimpleNamespace(entry_id="one", title="Door", data={}, options=options or {}, async_on_unload=callbacks.append,
                            async_create_background_task=lambda _h, coro, _name, **_kw: asyncio.create_task(coro))
    hass = SimpleNamespace(data={}, config=SimpleNamespace(language="en"),
                           states=SimpleNamespace(get=(states or {}).get),
                           services=SimpleNamespace(async_call=AsyncMock(return_value={})))
    return hass, entry, callbacks


async def loaded_page(hass, entry, language="en"):
    """Test-only join of the background fetch; production projection never waits."""
    page = await agenda.async_agenda_dashboard_page(hass, entry, language)
    cache = hass.data.get(agenda._DATA_KEY, {}).get(entry.entry_id)
    if cache is not None and cache.task is not None:
        await cache.task
        return await agenda.async_agenda_dashboard_page(hass, entry, language)
    return page


def event(hour, summary="Meeting", **extra):
    return {"start": (NOW + timedelta(hours=hour)).isoformat(),
            "end": (NOW + timedelta(hours=hour + 1)).isoformat(), "summary": summary, **extra}


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(agenda.dt_util, "utcnow", lambda: NOW)
    monkeypatch.setattr(agenda.dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Paris"))


def test_disabled_pages_do_not_allocate_or_fetch():
    hass, entry, callbacks = environment()
    assert asyncio.run(loaded_page(hass, entry)) is None
    assert leave.leave_home_dashboard_page(hass, entry) is None
    assert agenda.async_setup_agenda_updates(hass, entry, Mock()) is None
    assert not hass.data and not callbacks
    hass.services.async_call.assert_not_called()
    assert leave.leave_home_entity_ids(entry) == ()


def test_enabled_without_selected_calendars_has_no_io_or_cache():
    hass, entry, callbacks = environment({"agenda_page": {"enabled": True}})
    assert asyncio.run(loaded_page(hass, entry))["agenda"]["events"] == []
    assert agenda.async_setup_agenda_updates(hass, entry, Mock()) is None
    assert not hass.data and not callbacks
    hass.services.async_call.assert_not_called()


def test_agenda_next_five_sorted_bounded_selected_and_cached():
    hass, entry, callbacks = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one", "calendar.two"]}}, {
        "calendar.one": State("calendar.one", "off", {"friendly_name": "One"}),
        "calendar.two": State("calendar.two", "off", {"friendly_name": "Two"}),
    })
    hass.services.async_call.side_effect = [
        {"calendar.one": {"events": [event(h) for h in range(30, -1, -1)] + [event(-4), event(169)]}},
        {"calendar.two": {"events": [event(-0.5, "Ongoing"), event(0.2, "Second"), {"start": "bad"}]}}
    ]

    async def run():
        first, second = await asyncio.gather(loaded_page(hass, entry), loaded_page(hass, entry))
        assert first == second
        assert [item["summary"] for item in first["agenda"]["events"]] == ["Ongoing", "Meeting", "Second", "Meeting", "Meeting"]
        assert first["agenda"]["events"][1]["when"] == "15.11. 13:00"
        assert len(hass.data[agenda._DATA_KEY]["one"].events) <= 10
        assert not first["agenda"]["error"]
        # Payload mutations must not poison the cache.
        first["agenda"]["events"][0]["summary"] = "Changed"
        assert (await loaded_page(hass, entry))["agenda"]["events"][0]["summary"] == "Ongoing"

    asyncio.run(run())
    assert hass.services.async_call.await_count == 2
    for call in hass.services.async_call.call_args_list:
        assert call.args[:2] == ("calendar", "get_events")
        assert call.kwargs["blocking"] is True and call.kwargs["return_response"] is True
        assert call.args[2]["end_date_time"] == (NOW + timedelta(days=7)).isoformat()
    for callback in callbacks:
        callback()
    assert agenda._DATA_KEY not in hass.data


def test_all_day_dates_use_local_midnight_and_exclusive_end():
    hass, entry, _ = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}, {
        "calendar.one": State("calendar.one", "on"),
    })
    hass.services.async_call.return_value = {"calendar.one": {"events": [
        {"start": "2026-11-15", "end": "2026-11-16", "summary": "Today"},
        {"start": "2026-11-14", "end": "2026-11-15", "summary": "Over"},
        {"start": "2026-11-16T08:00:00", "end": "2026-11-16T09:00:00", "summary": "Local"},
    ]}}
    payload = asyncio.run(loaded_page(hass, entry, "de"))["agenda"]
    assert [item["summary"] for item in payload["events"]] == ["Today", "Local"]
    assert payload["events"][0]["all_day"] is True
    assert payload["events"][0]["start"].endswith("+01:00")
    assert "Ganzt" in payload["events"][0]["when"]
    assert payload["events"][1]["when"] == "16.11. 08:00"


@pytest.mark.parametrize("result", [HomeAssistantError("down"), RuntimeError("provider failed"), None, {}, {"calendar.one": {"events": "bad"}}])
def test_failed_reads_are_bounded_negative_cached_and_not_empty_success(result):
    hass, entry, _ = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}, {
        "calendar.one": State("calendar.one", "off"),
    })
    if isinstance(result, Exception):
        hass.services.async_call.side_effect = result
    else:
        hass.services.async_call.return_value = result

    async def run():
        for _ in range(2):
            payload = (await loaded_page(hass, entry))["agenda"]
            assert payload["error"] and payload["events"] == []

    asyncio.run(run())
    assert hass.services.async_call.await_count == 1


def test_expiry_retries_and_unavailable_calendar_does_not_call_service(monkeypatch):
    states = {"calendar.one": State("calendar.one", "off"), "calendar.two": State("calendar.two", "unavailable")}
    hass, entry, _ = environment({"agenda_page": {"enabled": True, "calendars": list(states)}}, states)
    hass.services.async_call.return_value = {"calendar.one": {"events": [event(0)]}}

    async def run():
        assert len((await loaded_page(hass, entry))["agenda"]["events"]) == 1
        monkeypatch.setattr(agenda.dt_util, "utcnow", lambda: NOW + timedelta(seconds=301))
        assert (await loaded_page(hass, entry))["agenda"]["error"]
        assert hass.services.async_call.await_count == 2

    asyncio.run(run())


def test_request_timeout_and_unload_during_read(monkeypatch):
    monkeypatch.setattr(agenda, "FETCH_TIMEOUT", 0.01)
    hass, entry, callbacks = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}, {
        "calendar.one": State("calendar.one", "off"),
    })

    async def never(*args, **kwargs):
        await asyncio.Event().wait()

    hass.services.async_call.side_effect = never
    assert asyncio.run(loaded_page(hass, entry))["agenda"]["error"]
    for callback in callbacks:
        callback()
    assert not hass.data

    async def run():
        await agenda.async_agenda_dashboard_page(hass, entry)
        request = hass.data[agenda._DATA_KEY][entry.entry_id].task
        await asyncio.sleep(0)
        callbacks[-1]()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not hass.data

    asyncio.run(run())


def test_leave_checks_actions_and_alarm_are_read_only(monkeypatch):
    hass, entry, _ = environment({
        "leave_home_page": {"enabled": True, "contacts": ["binary_sensor.door", "binary_sensor.missing"],
                            "lights": ["light.one"], "actions": ["leave", "deleted"], "show_alarm": True},
        "alarm_entity_id": "alarm_control_panel.home",
        "actions": {"leave": {"name": "Leave", "domain": "script", "service": "turn_on", "target": {"entity_id": "script.leave"}}},
    }, {"binary_sensor.door": State("binary_sensor.door", "on", {"device_class": "door"}),
        "light.one": State("light.one", "off"),
        "alarm_control_panel.home": State("alarm_control_panel.home", "disarmed")})
    monkeypatch.setattr(leave, "_alarm_commands_for_state", lambda *_: [{"command": "arm_away", "ready": False, "blocking_sensor_count": 2}])
    result = leave.leave_home_dashboard_page(hass, entry)["leave_home"]
    assert [item["state_label"] for item in result["checks"]] == ["Open", "Unavailable", "Off"]
    assert result["attention_count"] == 2
    assert result["actions"] == [{"domain": "c300x", "entity_id": "leave", "name": "Leave", "_kind": "button"}]
    assert result["alarm"]["ready"] is False and result["alarm"]["blocking_sensor_count"] == 2
    assert result["confirm_label"] == "Confirm"
    hass.services.async_call.assert_not_called()


def test_unknown_alarm_readiness_and_wrong_contact_class_fail_closed():
    hass, entry, _ = environment({"leave_home_page": {"enabled": True, "contacts": ["binary_sensor.motion"], "show_alarm": True},
                                 "alarm_entity_id": "alarm_control_panel.home"}, {
        "binary_sensor.motion": State("binary_sensor.motion", "off", {"device_class": "motion"}),
        "alarm_control_panel.home": State("alarm_control_panel.home", "disarmed"),
    })
    result = leave.leave_home_dashboard_page(hass, entry)["leave_home"]
    assert result["checks"][0]["state"] == "unavailable"
    assert result["alarm"]["ready"] is None
    assert result["alarm"]["state_label"] == "Unknown"


@pytest.mark.parametrize("state,label", [("armed_away", "Away"), ("arming", "Arming"), ("triggered", "Alarm"), ("unavailable", "Offline")])
def test_alarm_shows_current_state_instead_of_false_readiness(state, label):
    hass, entry, _ = environment({"leave_home_page": {"enabled": True, "show_alarm": True}, "alarm_entity_id": "alarm_control_panel.home"}, {
        "alarm_control_panel.home": State("alarm_control_panel.home", state),
    })
    alarm = leave.leave_home_dashboard_page(hass, entry)["leave_home"]["alarm"]
    assert alarm["state_label"] == label
    assert alarm["ready"] is None
    assert alarm["available"] is (state != "unavailable")


def test_leave_subscription_handles_names_even_with_hidden_tile_name():
    hass, entry, _ = environment({"leave_home_page": {"enabled": True, "contacts": ["binary_sensor.door"]},
                                 "dashboard_entity_display_overrides": {"binary_sensor.door": {"name": "entity_id"}}})
    data = {"entity_id": "binary_sensor.door", "old_state": State("binary_sensor.door", "off", {"friendly_name": "Old", "device_class": "door"}),
            "new_state": State("binary_sensor.door", "off", {"friendly_name": "New", "device_class": "door"})}
    assert dashboard_state_event_changes_display(hass, entry, data)


@pytest.mark.parametrize("enabled,calendars,ui", [(False, ["calendar.one"], True), (True, [], True), (True, ["calendar.one"], False), (True, ["calendar.one"], True)])
def test_runtime_lifecycle_calendar_and_selected_checks(monkeypatch, enabled, calendars, ui):
    from homeassistant.helpers import dispatcher

    hass, entry, callbacks = environment({"device_ui_enabled": ui, "agenda_page": {"enabled": enabled, "calendars": calendars},
                                         "leave_home_page": {"enabled": True, "lights": ["light.one"]}})
    bus_callbacks, timers, state_callbacks, unsubs = [], [], [], []
    hass.bus = SimpleNamespace(async_listen=lambda _event, cb: (bus_callbacks.append(cb), lambda: unsubs.append("bus"))[1])
    monkeypatch.setattr(dispatcher, "async_dispatcher_connect", lambda *_: lambda: unsubs.append("dispatcher"))
    monkeypatch.setattr(agenda, "async_track_state_change_event", lambda _h, ids, cb: (state_callbacks.append((ids, cb)), lambda: unsubs.append("state"))[1])
    monkeypatch.setattr(agenda, "async_track_time_interval", lambda _h, cb, interval: (timers.append((cb, interval)), lambda: unsubs.append("timer"))[1])
    notify = Mock()
    refresh = Mock()
    monkeypatch.setattr(agenda, "_start_refresh", refresh)
    monkeypatch.setattr(runtime_manager, "_async_schedule_display_bridge_notify", notify)
    stop = runtime_manager._async_track_display_bridge_updates(hass, entry)
    active = enabled and calendars and ui
    assert bool(timers) == bool(active)
    if ui:
        bus_callbacks[0](SimpleNamespace(data={"entity_id": "light.one"}))
        notify.assert_called_once_with(hass, entry)
        bus_callbacks[0](SimpleNamespace(data={"entity_id": "light.other"}))
        assert notify.call_count == 1
    if active:
        assert timers[0][1] == timedelta(seconds=300)
        state_callbacks[0][1](None)
        timers[0][0](None)
        assert notify.call_count == 1
        assert refresh.call_count == 2
        hass.services.async_call.assert_not_called()
    if stop:
        stop()
    for cb in callbacks:
        cb()
    if active:
        assert unsubs.count("timer") == unsubs.count("state") == 1
    assert agenda._DATA_KEY not in hass.data


def test_real_ha_entry_unload_reload_and_stale_callbacks(monkeypatch, tmp_path):
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant, SupportsResponse

    timers = []
    monkeypatch.setattr(agenda, "async_track_time_interval", lambda _h, cb, interval: (timers.append(cb), lambda: None)[1])

    async def run():
        hass = HomeAssistant(str(tmp_path))
        calls = []

        async def get_events(call):
            calls.append(call)
            return {"calendar.one": {"events": [event(2)]}}

        hass.services.async_register("calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY)
        hass.states.async_set("calendar.one", "off")

        def entry(entry_id):
            return ConfigEntry(domain="bticino_c300x", title="Door", entry_id=entry_id, version=1, minor_version=1,
                               source="user", unique_id=entry_id, discovery_keys={}, subentries_data=[],
                               data={}, options={"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}},
                               state=ConfigEntryState.LOADED)

        first, second = entry("first"), entry("second")
        notify_first, notify_second = Mock(), Mock()
        agenda.async_setup_agenda_updates(hass, first, notify_first)
        agenda.async_setup_agenda_updates(hass, second, notify_second)
        old_unload = first._on_unload[0]
        assert await loaded_page(hass, first)
        assert await loaded_page(hass, second)
        assert len(calls) == 2
        hass.states.async_set("calendar.one", "on")
        await hass.async_block_till_done()
        await loaded_page(hass, first)
        await loaded_page(hass, second)
        assert notify_first.call_count == notify_second.call_count == 2
        first._async_set_state(hass, ConfigEntryState.UNLOAD_IN_PROGRESS, None)
        await first._async_process_on_unload(hass)
        first._async_set_state(hass, ConfigEntryState.NOT_LOADED, None)
        timers[0](None)
        assert notify_first.call_count == 2
        assert await loaded_page(hass, first) is None
        assert agenda.async_setup_agenda_updates(hass, first, notify_first) is None
        assert set(hass.data[agenda._DATA_KEY]) == {"second"}
        first._async_set_state(hass, ConfigEntryState.LOADED, None)
        agenda.async_setup_agenda_updates(hass, first, notify_first)
        old_unload()
        assert set(hass.data[agenda._DATA_KEY]) == {"first", "second"}
        assert await loaded_page(hass, first)
        assert len(calls) == 5
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def slow(_call):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        hass.services.async_register("calendar", "get_events", slow, supports_response=SupportsResponse.ONLY)
        timers[-1](None)
        await started.wait()
        reading = hass.data[agenda._DATA_KEY][first.entry_id].task
        pushes = notify_first.call_count
        await first._async_process_on_unload(hass)
        assert reading.cancelled() and cancelled.is_set()
        assert notify_first.call_count == pushes
        assert not first._background_tasks
        await second._async_process_on_unload(hass)
        assert agenda._DATA_KEY not in hass.data
        await hass.async_stop()

    asyncio.run(run())


def test_change_during_read_preserves_invalidation_and_one_inflight_task(monkeypatch):
    hass, entry, callbacks = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}, {
        "calendar.one": State("calendar.one", "off"),
    })
    changes = []
    monkeypatch.setattr(agenda, "async_track_state_change_event", lambda _h, _ids, cb: (changes.append(cb), lambda: None)[1])
    monkeypatch.setattr(agenda, "async_track_time_interval", lambda *_: lambda: None)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def read(*args, **kwargs):
            started.set()
            await release.wait()
            return {"calendar.one": {"events": [event(1)]}}

        hass.services.async_call.side_effect = read
        notify = Mock()
        stop = agenda.async_setup_agenda_updates(hass, entry, notify)
        await agenda.async_agenda_dashboard_page(hass, entry)
        cache = hass.data[agenda._DATA_KEY][entry.entry_id]
        first = cache.task
        await started.wait()
        changes[0](None)
        assert cache.task is first
        release.set()
        await first
        assert cache.expires is None
        notify.assert_called_once()
        await loaded_page(hass, entry)
        assert hass.services.async_call.await_count == 2
        assert cache.expires is not None
        stop()
        before = notify.call_count
        changes[0](None)
        assert notify.call_count == before and not hass.data
        for callback in callbacks:
            callback()

    asyncio.run(run())


def test_slow_provider_never_blocks_dashboard_and_unload_cancels_without_late_push():
    from custom_components.bticino_c300x.dashboard import async_dashboard_payload

    hass, entry, callbacks = environment({"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}, {
        "calendar.one": State("calendar.one", "off"),
    })
    entry.options["device_ui_enabled"] = True

    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        hass.services.async_call.side_effect = slow
        notify = Mock()
        cache = agenda._cache(hass, entry)
        cache.notify = notify
        payload = await asyncio.wait_for(async_dashboard_payload(hass, entry), 0.1)
        assert payload["data"]["pages"][0]["title"] == "C300X"
        initial = next(page["agenda"] for page in payload["data"]["pages"] if "agenda" in page)
        assert initial["loading"] and initial["empty_text"] == "Loading events"
        await started.wait()
        task = cache.task
        for _ in range(3):
            assert (await agenda.async_agenda_dashboard_page(hass, entry))["agenda"]["loading"]
        assert cache.task is task and hass.services.async_call.await_count == 1
        callbacks[0]()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert cache.closed and cache.task is None and cache.events == []
        assert not hass.data
        notify.assert_not_called()

    asyncio.run(run())


def test_malformed_provider_dates_are_skipped(monkeypatch):
    assert agenda._event_time("2026-99-99") is None
    assert agenda._events(None, "calendar.one", "One", NOW, NOW + timedelta(days=7)) == []
    assert agenda._events([None, {}], "calendar.one", "One", NOW, NOW + timedelta(days=7)) == []
    monkeypatch.setattr(agenda.dt_util, "parse_datetime", Mock(side_effect=OverflowError))
    assert agenda._event_time("2026-11-15T99:00:00") is None
