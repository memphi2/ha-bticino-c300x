"""Current Agenda settings retire work before the normal options reload."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import State
from test_dashboard_optional_pages import NOW, environment, event, loaded_page

from custom_components.bticino_c300x import dashboard_agenda as agenda


@pytest.fixture
def tracked(monkeypatch):
    monkeypatch.setattr(agenda.dt_util, "utcnow", lambda: NOW)
    ids = ["calendar.one", "calendar.two"]
    hass, entry, unload = environment(
        {"agenda_page": {"enabled": True, "calendars": ids}},
        {key: State(key, "off") for key in ids},
    )
    entry.state = ConfigEntryState.LOADED
    entry.runtime_data = SimpleNamespace(resources=SimpleNamespace(closed=False))
    changes, ticks, updates, unsubs = [], [], [], []

    def register(callbacks, cb):
        callbacks.append(cb)
        unsubscribe = Mock()
        unsubs.append(unsubscribe)
        return unsubscribe

    entry.add_update_listener = lambda cb: register(updates, cb)
    monkeypatch.setattr(agenda, "async_track_state_change_event", lambda _h, _ids, cb: register(changes, cb))
    monkeypatch.setattr(agenda, "async_track_time_interval", lambda _h, cb, _interval: register(ticks, cb))
    hass.services.async_call.side_effect = lambda *_args, target, **_kwargs: {
        target["entity_id"]: {"events": [event(1)]},
    }
    return SimpleNamespace(hass=hass, entry=entry, unload=unload, changes=changes,
                           ticks=ticks, updates=updates, unsubs=unsubs, notify=Mock())


def change(env, reason):
    if reason == "disabled":
        env.entry.options["agenda_page"]["enabled"] = False
    elif reason == "empty":
        env.entry.options["agenda_page"]["calendars"] = []
    elif reason == "selection":
        env.entry.options["agenda_page"]["calendars"] = ["calendar.two"]
    elif reason == "unloading":
        env.entry.state = ConfigEntryState.UNLOAD_IN_PROGRESS
    elif reason == "closed":
        env.entry.runtime_data.resources.closed = True
    else:
        env.entry.runtime_data = SimpleNamespace(resources=SimpleNamespace(closed=False))


@pytest.mark.parametrize("reason", ["disabled", "empty"])
def test_inactive_start_allocates_no_cache_or_listeners(tracked, reason):
    async def run():
        env = tracked
        change(env, reason)
        assert agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify) is None
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        assert not env.hass.data
        assert not env.updates and not env.changes and not env.ticks and not env.unload
        env.hass.services.async_call.assert_not_awaited()

    asyncio.run(run())


def test_unrelated_options_keep_cached_events_and_single_subscription(tracked):
    async def run():
        env = tracked
        stop = agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        page = await loaded_page(env.hass, env.entry)
        cache = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        env.entry.options["agenda_page"]["position"] = 1
        await env.updates[0](env.hass, env.entry)
        agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        assert await loaded_page(env.hass, env.entry) == page
        assert env.hass.data[agenda._DATA_KEY][env.entry.entry_id] is cache
        assert len(env.updates) == len(env.changes) == len(env.ticks) == 1
        assert env.hass.services.async_call.await_count == 2
        stop()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["disabled", "empty"])
@pytest.mark.parametrize("trigger", ["page", "state", "timer", "options"])
def test_disabled_retires_cache_listeners_and_never_restarts(tracked, reason, trigger):
    async def run():
        env = tracked
        stop = agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        await loaded_page(env.hass, env.entry)
        cache = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        env.notify.reset_mock()
        env.hass.services.async_call.reset_mock()
        change(env, reason)
        if trigger == "page":
            await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        elif trigger == "options":
            assert len(env.updates) == 1
            await env.updates[0](env.hass, env.entry)
        else:
            (env.changes if trigger == "state" else env.ticks)[0](None)
        assert cache.closed and cache.task is None and not cache.events
        assert not env.hass.data
        for unsubscribe in env.unsubs:
            unsubscribe.assert_called_once()
        for cb in [*env.changes, *env.ticks]:
            cb(None)
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        assert agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify) is None
        assert not env.hass.data
        env.hass.services.async_call.assert_not_awaited()
        env.notify.assert_not_called()
        stop()
        for cb in env.unload:
            cb()
        for unsubscribe in env.unsubs:
            unsubscribe.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["disabled", "empty", "selection", "unloading", "closed", "replacement"])
@pytest.mark.parametrize("scheduled", [True, False])
def test_retired_job_cannot_read_next_calendar_or_publish(tracked, reason, scheduled):
    async def run():
        env = tracked
        agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        started, release = asyncio.Event(), asyncio.Event()

        async def read(*_args, target, **_kwargs):
            started.set()
            await release.wait()
            return {target["entity_id"]: {"events": [event(1)]}}

        env.hass.services.async_call.side_effect = read
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        cache = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        task = cache.task
        if not scheduled:
            await started.wait()
        change(env, reason)
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        assert env.hass.services.async_call.await_count == (0 if scheduled else 1)
        assert cache.closed and cache.task is None and not cache.events
        assert not env.hass.data
        env.notify.assert_not_called()
        for unsubscribe in env.unsubs:
            unsubscribe.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["disabled", "empty"])
def test_options_cancel_pending_provider_without_waiting_for_reload(tracked, reason):
    async def run():
        env = tracked
        agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def read(*_args, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        env.hass.services.async_call.side_effect = read
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        task = env.hass.data[agenda._DATA_KEY][env.entry.entry_id].task
        await started.wait()
        change(env, reason)
        assert len(env.updates) == 1
        await env.updates[0](env.hass, env.entry)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set() and not env.hass.data
        env.notify.assert_not_called()

    asyncio.run(run())


def test_selection_change_hides_old_events_and_stale_callbacks_preserve_replacement(tracked):
    async def run():
        env = tracked
        old_stop = agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        await loaded_page(env.hass, env.entry)
        old_cache = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        old_unload, old_update, old_state = env.unload[0], env.updates[0], env.changes[0]
        change(env, "selection")
        page = await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        assert not page["agenda"]["events"] and page["agenda"]["loading"]
        replacement = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        assert old_cache.closed and replacement is not old_cache
        stop = agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        old_stop()
        old_unload()
        await old_update(env.hass, env.entry)
        old_state(None)
        assert env.hass.data[agenda._DATA_KEY][env.entry.entry_id] is replacement
        result = await loaded_page(env.hass, env.entry)
        assert {item["entity_id"] for item in result["agenda"]["events"]} == {"calendar.two"}
        stop()

    asyncio.run(run())


def test_cancelled_old_provider_cannot_publish_or_close_new_cache(tracked):
    async def run():
        env = tracked
        agenda.async_setup_agenda_updates(env.hass, env.entry, env.notify)
        started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def read(*_args, target, **_kwargs):
            if target["entity_id"] == "calendar.one":
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release.wait()
            return {target["entity_id"]: {"events": [event(1)]}}

        env.hass.services.async_call.side_effect = read
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        old = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        old_task = old.task
        await started.wait()
        change(env, "selection")
        await agenda.async_agenda_dashboard_page(env.hass, env.entry)
        replacement = env.hass.data[agenda._DATA_KEY][env.entry.entry_id]
        await cancelled.wait()
        release.set()
        await old_task
        assert old.closed and not old.events
        assert env.hass.data[agenda._DATA_KEY][env.entry.entry_id] is replacement
        result = await loaded_page(env.hass, env.entry)
        assert {item["entity_id"] for item in result["agenda"]["events"]} == {"calendar.two"}
        assert env.hass.services.async_call.await_count == 2
        env.notify.assert_not_called()
        for cb in env.unload:
            cb()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["disabled", "empty"])
@pytest.mark.parametrize("agenda_first", [True, False])
def test_real_options_update_coexists_with_delayed_normal_reload(tmp_path, monkeypatch, reason, agenda_first):
    from homeassistant.config_entries import ConfigEntries, ConfigEntry
    from homeassistant.core import HomeAssistant, SupportsResponse

    from custom_components.bticino_c300x import runtime_manager

    async def run():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = ConfigEntries(hass, {})
        monkeypatch.setattr(hass.config_entries, "_async_schedule_save", Mock())
        monkeypatch.setattr(hass.config_entries, "_async_dispatch", Mock())
        options = {"agenda_page": {"enabled": True, "calendars": ["calendar.one"]}}
        entry = ConfigEntry(domain="bticino_c300x", title="Door", version=1, minor_version=1,
                            source="user", unique_id="agenda", discovery_keys={}, subentries_data=[],
                            data={}, options=options, state=ConfigEntryState.LOADED)
        hass.config_entries._entries[entry.entry_id] = entry
        started, release_reload = asyncio.Event(), asyncio.Event()
        notify = Mock()

        async def read(_call):
            started.set()
            await asyncio.Event().wait()

        async def reload(entry_id):
            assert entry_id == entry.entry_id
            await release_reload.wait()
            entry._async_set_state(hass, ConfigEntryState.UNLOAD_IN_PROGRESS, None)
            await entry._async_process_on_unload(hass)
            entry._async_set_state(hass, ConfigEntryState.LOADED, None)
            assert agenda.async_setup_agenda_updates(hass, entry, notify) is None

        monkeypatch.setattr(hass.config_entries, "async_reload", AsyncMock(side_effect=reload))
        monkeypatch.setattr(runtime_manager, "_async_reapply_display_patch_for_home_page", AsyncMock())
        hass.services.async_register("calendar", "get_events", read, supports_response=SupportsResponse.ONLY)
        hass.states.async_set("calendar.one", "off")
        normal_listener = runtime_manager._entry_update_listener(entry)
        if agenda_first:
            agenda.async_setup_agenda_updates(hass, entry, notify)
        entry.async_on_unload(entry.add_update_listener(normal_listener))
        if not agenda_first:
            agenda.async_setup_agenda_updates(hass, entry, notify)
        trailing_listener = AsyncMock()
        entry.async_on_unload(entry.add_update_listener(trailing_listener))
        await agenda.async_agenda_dashboard_page(hass, entry)
        old_cache = hass.data[agenda._DATA_KEY][entry.entry_id]
        task = old_cache.task
        await started.wait()
        changed = {**options["agenda_page"], **({"enabled": False} if reason == "disabled" else {"calendars": []})}
        hass.config_entries.async_update_entry(entry, options={"agenda_page": changed})
        with pytest.raises(asyncio.CancelledError):
            await task
        assert old_cache.closed and agenda._DATA_KEY not in hass.data
        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
        trailing_listener.assert_awaited_once()
        notify.assert_not_called()
        release_reload.set()
        await hass.async_block_till_done()
        assert not entry.update_listeners and not entry._background_tasks
        assert agenda._DATA_KEY not in hass.data
        hass.config_entries.async_update_entry(entry, options=options)
        stop = agenda.async_setup_agenda_updates(hass, entry, notify)
        assert stop is not None
        assert hass.data[agenda._DATA_KEY][entry.entry_id] is not old_cache
        await entry._async_process_on_unload(hass)
        assert not entry.update_listeners and agenda._DATA_KEY not in hass.data
        await hass.async_stop()

    asyncio.run(run())
