from __future__ import annotations

import asyncio
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = pytest.mark.usefixtures("entity_ha_boundary")

from custom_components.bticino_c300x.api import C300XAgentApiError  # noqa: E402
from custom_components.bticino_c300x.select import (  # noqa: E402
    C300XAudioCodecSelect,
    C300XSmartphoneForwardingModeSelect,
    async_setup_entry,
)


class _FakeApi:
    def __init__(self, *, fail_status: bool = False) -> None:
        self.active_reads = 0
        self.selected: list[str] = []
        self.fail_status = fail_status
        self.audio_codec_calls: list[tuple[str, bool]] = []
        self.audio_codec_state = "speex"
        self.audio_codec_running_state = "speex"
        self.audio_codec_reboots = True

    async def async_smartphone_forwarding_status(self) -> dict[str, Any]:
        self.active_reads += 1
        if self.fail_status:
            raise C300XAgentApiError("offline")
        return {"mode": 2, "state": "blocked"}

    async def async_set_smartphone_forwarding_mode(self, mode: str) -> dict[str, Any]:
        self.selected.append(mode)
        return {"mode": 1, "state": mode}

    async def async_audio_codec_status(self) -> dict[str, Any]:
        self.active_reads += 1
        if self.fail_status:
            raise C300XAgentApiError("offline")
        return {
            "ok": True,
            "supported": True,
            "state": self.audio_codec_running_state,
            "configured_state": self.audio_codec_state,
            "running_state": self.audio_codec_running_state,
            "backup_present": self.audio_codec_state == "pcmu",
            "reboot_required": self.audio_codec_state != self.audio_codec_running_state,
        }

    async def async_apply_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        self.audio_codec_calls.append(("apply", reboot))
        self.audio_codec_state = "pcmu"
        rebooting = reboot and self.audio_codec_reboots
        return {
            "ok": True,
            "state": self.audio_codec_running_state,
            "configured_state": "pcmu",
            "running_state": self.audio_codec_running_state,
            "reboot_required": self.audio_codec_state != self.audio_codec_running_state,
            "rebooting": rebooting,
        }

    async def async_restore_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        self.audio_codec_calls.append(("restore", reboot))
        self.audio_codec_state = "speex"
        rebooting = reboot and self.audio_codec_reboots
        return {
            "ok": True,
            "state": self.audio_codec_running_state,
            "configured_state": "speex",
            "running_state": self.audio_codec_running_state,
            "reboot_required": self.audio_codec_state != self.audio_codec_running_state,
            "rebooting": rebooting,
        }


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(
        default_factory=lambda: {"smartphone_forwarding": {"supported": True}}
    )
    api: _FakeApi = field(default_factory=_FakeApi)
    event_state: SimpleNamespace = field(default_factory=SimpleNamespace)
    connection_state: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(available=True)
    )


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)

    def __post_init__(self) -> None:
        # A set-up 3.1 entry: the config flow stored the station id.
        self.data.setdefault("station_id", "c300x-0123456789ab")


def test_smartphone_forwarding_select_refreshes_active_status() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entry.runtime_data.api.active_reads == 1
    assert entity.current_option == "blocked"
    assert entity.extra_state_attributes == {"mode": 2, "state": "blocked"}
    assert entry.runtime_data.event_state.smartphone_forwarding_mode == "blocked"


def test_select_setup_adds_supported_entities_after_initial_refresh() -> None:
    entry = _FakeEntry()
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert len(added) == 1
    assert len(added[0]) == 1
    entity = added[0][0]
    assert isinstance(entity, C300XSmartphoneForwardingModeSelect)
    assert entry.runtime_data.api.active_reads == 1
    assert entity.current_option == "blocked"


def test_select_setup_skips_unsupported_forwarding_capability() -> None:
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={}))
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert added == []
    assert entry.runtime_data.api.active_reads == 0


def test_smartphone_forwarding_select_marks_unavailable_on_api_error() -> None:
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=_FakeApi(fail_status=True)))
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False
    assert entity.current_option is None


def test_smartphone_forwarding_select_sets_three_state_mode() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("homeassistant"))

    assert entry.runtime_data.api.selected == ["homeassistant"]
    assert entity.current_option == "homeassistant"


def test_smartphone_forwarding_select_ignores_invalid_options() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("invalid"))

    assert entry.runtime_data.api.selected == []
    assert entity.current_option is None


def test_smartphone_forwarding_select_reports_unprovisioned_but_does_not_write() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    entity._apply_status({"mode": 3, "state": "unprovisioned"})
    asyncio.run(entity.async_select_option("unprovisioned"))

    assert entity.options == ["enabled", "homeassistant", "blocked"]
    assert entry.runtime_data.api.selected == []
    assert entity.current_option is None
    assert entity.extra_state_attributes == {"mode": 3, "state": "unprovisioned"}


def test_smartphone_forwarding_select_rejects_the_former_display_texts() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("Blocked"))

    assert entry.runtime_data.api.selected == []


def test_every_forwarding_option_has_a_text_in_every_language() -> None:
    import json
    from pathlib import Path

    component = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x"
    for path in [component / "strings.json", *sorted((component / "translations").glob("*.json"))]:
        states = json.loads(path.read_text(encoding="utf-8"))["entity"]["select"][
            "smartphone_forwarding_mode"
        ]["state"]
        assert list(states) == ["enabled", "homeassistant", "blocked"], path.name


def test_smartphone_forwarding_select_sets_the_smartphone_mode() -> None:
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("enabled"))

    assert entry.runtime_data.api.selected == ["enabled"]
    assert entity.current_option == "enabled"


def test_smartphone_forwarding_event_updates_select_state() -> None:
    entity = C300XSmartphoneForwardingModeSelect(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "smartphone_forwarding_changed",
                "mode": 1,
            }
        )
    )

    assert entity.current_option == "homeassistant"
    assert entity.extra_state_attributes == {"mode": 1, "state": "homeassistant"}


def test_smartphone_forwarding_event_shows_unprovisioned_state() -> None:
    entity = C300XSmartphoneForwardingModeSelect(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "smartphone_forwarding_changed",
                "mode": 3,
            }
        )
    )

    assert entity.current_option is None
    assert entity.extra_state_attributes == {"mode": 3, "state": "unprovisioned"}


def test_smartphone_forwarding_select_subscribes_to_agent_events() -> None:
    listeners: list[tuple[str, Any]] = []
    removers: list[Any] = []
    entity = C300XSmartphoneForwardingModeSelect(_FakeEntry())  # type: ignore[arg-type]
    entity.hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_listen=lambda event_type, callback: listeners.append(
                (event_type, callback)
            )
            or "unsub"
        )
    )
    entity.async_on_remove = removers.append  # type: ignore[method-assign]

    asyncio.run(entity.async_added_to_hass())

    assert listeners == [("bticino_c300x_agent_event_received", entity._handle_agent_event)]
    assert removers[0] == entity._cancel_reconnect_refresh
    assert callable(removers[1])
    assert callable(removers[2])
    assert removers[3] == "unsub"
    # The restart signal of the agent.
    assert len(removers) == 5 and callable(removers[4])


def test_smartphone_forwarding_select_ignores_unrelated_events() -> None:
    entity = C300XSmartphoneForwardingModeSelect(_FakeEntry())  # type: ignore[arg-type]

    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "other-entry",
                "event_type": "smartphone_forwarding_changed",
                "mode": 1,
            }
        )
    )
    entity._handle_agent_event(
        SimpleNamespace(
            data={
                "entry_id": "entry-1",
                "event_type": "doorbell_pressed",
                "mode": 1,
            }
        )
    )
    entity._apply_status({"mode": 99, "state": "not-a-mode"})

    assert entity.current_option is None
    assert entity.extra_state_attributes == {"mode": 99, "state": "not-a-mode"}


def _audio_codec_entry(*, fail_status: bool = False) -> _FakeEntry:
    return _FakeEntry(
        runtime_data=_FakeRuntimeData(
            capabilities={"maintenance": {"supported": True, "audio_codec_apply": True}},
            api=_FakeApi(fail_status=fail_status),
        )
    )


def test_audio_codec_select_added_when_advertised() -> None:
    entry = _audio_codec_entry()
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    entities = added[0]
    codec_entities = [
        entity for entity in entities if isinstance(entity, C300XAudioCodecSelect)
    ]
    assert codec_entities
    assert codec_entities[0].entity_registry_enabled_default is True


def test_audio_codec_select_skipped_when_not_advertised() -> None:
    entry = _FakeEntry(runtime_data=_FakeRuntimeData(capabilities={}))
    added: list[list[Any]] = []

    asyncio.run(async_setup_entry("hass", entry, added.append))  # type: ignore[arg-type]

    assert added == []


def test_audio_codec_select_reflects_and_switches_codec() -> None:
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes == {"state": "speex", "pending_option": None}
    # The running codec is mirrored into shared runtime state for consumers.
    assert entry.runtime_data.event_state.audio_codec == "speex"

    # Selecting pcmu stages the change and triggers a reboot, but the running
    # codec stays speex until the reboot lands -- no optimistic jump.
    asyncio.run(entity.async_select_option("pcmu"))
    assert entry.runtime_data.api.audio_codec_calls == [("apply", True)]
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes["pending_option"] == "pcmu"
    # The mirror also stays on the running codec while the switch is pending.
    assert entry.runtime_data.event_state.audio_codec == "speex"

    # The reboot drops the agent and it comes back -> re-read the now-live codec
    # (the fake status now reports pcmu), rather than optimistically assuming it.
    scheduled: list[Any] = []
    entity.hass = SimpleNamespace(async_create_task=scheduled.append)
    entry.runtime_data.connection_state.available = False
    entity._handle_reboot_reconnect("entry-1")
    entry.runtime_data.api.audio_codec_running_state = "pcmu"
    entry.runtime_data.connection_state.available = True
    entity._handle_reboot_reconnect("entry-1")
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
    assert entity.current_option == "pcmu"
    assert entity.extra_state_attributes["pending_option"] is None
    # Once the switch is live, the mirror follows to the new running codec.
    assert entry.runtime_data.event_state.audio_codec == "pcmu"


def test_audio_codec_select_pending_resolves_on_manual_reboot_when_not_rebooted() -> None:
    # reboot disabled: apply patches the files but the agent does not reboot, so
    # the change stays pending. A later manual reboot (a real down->up gap) must
    # still resolve it by re-reading the now-live codec.
    entry = _audio_codec_entry()
    entry.runtime_data.api.audio_codec_reboots = False
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]
    scheduled: list[Any] = []
    entity.hass = SimpleNamespace(async_create_task=scheduled.append)

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_select_option("pcmu"))
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes["pending_option"] == "pcmu"

    entry.runtime_data.connection_state.available = False
    entity._handle_reboot_reconnect("entry-1")
    entry.runtime_data.api.audio_codec_running_state = "pcmu"
    entry.runtime_data.connection_state.available = True
    entity._handle_reboot_reconnect("entry-1")
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
    assert entity.current_option == "pcmu"
    assert entity.extra_state_attributes["pending_option"] is None


def test_audio_codec_select_reconnect_keeps_pending_until_device_switches() -> None:
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]
    scheduled: list[Any] = []
    entity.hass = SimpleNamespace(async_create_task=scheduled.append)

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_select_option("pcmu"))
    assert entity.current_option == "speex"

    # A reconnect re-reads the live codec, but while the device still runs speex
    # (no reboot happened yet) the change stays pending -- the safety against a
    # premature switch comes from running_state, not from observing a down gap.
    entity._handle_reboot_reconnect("entry-1")
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes["pending_option"] == "pcmu"


def test_audio_codec_select_resolves_on_reconnect_without_observed_gap() -> None:
    # Regression: a device reboot from the codec apply often re-registers within
    # the reconnect grace window, so HA never sees `available` flip to False. The
    # pending change must still resolve on the reconnect signal -- it previously
    # stayed stuck on speex until a manual reload even though the device was pcmu.
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]
    scheduled: list[Any] = []
    entity.hass = SimpleNamespace(async_create_task=scheduled.append)

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_select_option("pcmu"))
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes["pending_option"] == "pcmu"

    # Device rebooted into pcmu and the agent re-registers (a connection signal)
    # WITHOUT HA ever having marked it unavailable.
    entry.runtime_data.api.audio_codec_running_state = "pcmu"
    entity._handle_reboot_reconnect("entry-1")
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
    assert entity.current_option == "pcmu"
    assert entity.extra_state_attributes["pending_option"] is None


def test_audio_codec_select_subscribes_to_connection_signal() -> None:
    entity = C300XAudioCodecSelect(_audio_codec_entry())  # type: ignore[arg-type]
    removers: list[Any] = []
    entity.hass = SimpleNamespace()
    entity.async_on_remove = removers.append  # type: ignore[method-assign]

    asyncio.run(entity.async_added_to_hass())

    assert removers
    assert all(callable(remover) for remover in removers)


@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize("suppress_cancel", [False, True])
def test_pending_codec_refresh_cannot_write_after_reload(remove, suppress_cancel) -> None:
    async def run() -> None:
        entry = _audio_codec_entry()
        entity = C300XAudioCodecSelect(entry)
        started, finish = asyncio.Event(), asyncio.Event()
        cancelled = False

        async def delayed_status():
            nonlocal cancelled
            started.set()
            try:
                await finish.wait()
            except asyncio.CancelledError:
                cancelled = True
                if not suppress_cancel:
                    raise
                await finish.wait()
            return {"running_state": "speex", "reboot_required": False}

        entry.runtime_data.api.async_audio_codec_status = delayed_status
        removers, tasks, writes = [], [], []

        def create(coro):
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

        entity.hass = SimpleNamespace(async_create_task=create)
        entity.async_on_remove = removers.append
        entity.async_write_ha_state = lambda: writes.append(True)
        await entity.async_added_to_hass()
        entity._pending_option = "pcmu"
        entity._handle_reboot_reconnect(entry.entry_id)
        await started.wait()
        # Repeated connection signals must not start overlapping status reads.
        entity._handle_reboot_reconnect(entry.entry_id)
        assert len(tasks) == 1
        if remove:
            for callback in removers:
                callback()
            await asyncio.sleep(0)
            assert cancelled
        replacement = _FakeRuntimeData()
        replacement.event_state.audio_codec = "pcmu"
        entry.runtime_data = replacement
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert replacement.event_state.audio_codec == "pcmu"
        assert writes == []
        assert entity._resolving_pending is False
        if remove:
            entity._handle_reboot_reconnect(entry.entry_id)
            assert len(tasks) == 1

    asyncio.run(run())


def test_audio_codec_select_stays_on_live_codec_while_reboot_is_deferred() -> None:
    entry = _audio_codec_entry()
    entry.runtime_data.api.audio_codec_reboots = False
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())
    assert entity.current_option == "speex"

    # Files are patched to pcmu, but no reboot fired: the running codec is still
    # speex, so the select must keep reporting speex (so the card does not switch
    # its gain path) and expose pcmu only as the pending change.
    asyncio.run(entity.async_select_option("pcmu"))
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes == {
        "state": "speex",
        "pending_option": "pcmu",
    }
    asyncio.run(entity.async_update())
    assert entity.current_option == "speex"
    assert entity.extra_state_attributes == {
        "state": "speex",
        "pending_option": "pcmu",
    }


def test_audio_codec_select_reloads_staged_codec_as_pending() -> None:
    entry = _audio_codec_entry()
    entry.runtime_data.api.audio_codec_state = "pcmu"
    entry.runtime_data.api.audio_codec_running_state = "speex"
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.current_option == "speex"
    assert entity.extra_state_attributes == {
        "state": "speex",
        "pending_option": "pcmu",
    }
    assert entry.runtime_data.event_state.audio_codec == "speex"


def test_audio_codec_select_partial_state_has_no_option() -> None:
    entry = _audio_codec_entry()
    entry.runtime_data.api.audio_codec_state = "partial"
    entry.runtime_data.api.audio_codec_running_state = "partial"
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.current_option is None


def test_audio_codec_select_keeps_pending_until_the_reboot_lands() -> None:
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]
    status = {
        "state": "pcmu",
        "running_state": "speex",
        "configured_state": "pcmu",
        "reboot_required": True,
    }

    entity._apply_status(status)
    entity._apply_status(status)

    assert entity.current_option == "speex"
    assert entity.extra_state_attributes["pending_option"] == "pcmu"
    assert entry.runtime_data.event_state.audio_codec == "speex"

    entity._apply_status(
        {**status, "running_state": "pcmu", "reboot_required": False}
    )

    assert entity.current_option == "pcmu"
    assert entity.extra_state_attributes["pending_option"] is None
    assert entry.runtime_data.event_state.audio_codec == "pcmu"


def test_audio_codec_select_unknown_option_is_ignored() -> None:
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_select_option("opus"))

    assert entry.runtime_data.api.audio_codec_calls == []


def test_audio_codec_select_marks_unavailable_on_api_error() -> None:
    entry = _audio_codec_entry(fail_status=True)
    entity = C300XAudioCodecSelect(entry)  # type: ignore[arg-type]

    asyncio.run(entity.async_update())

    assert entity.available is False


def test_smartphone_forwarding_push_without_a_reading_keeps_the_known_state() -> None:
    """The webhook preserves the last known mode when a push cannot be parsed
    and then fires the bus event carrying mode=None. This callback runs
    synchronously on that event and writes the same store, so treating the
    resulting "unknown" as a value would undo the preservation one line later."""

    entry = _FakeEntry()
    entry.runtime_data.event_state.smartphone_forwarding_mode = "blocked"
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]
    entity.hass = "hass"  # type: ignore[assignment]
    entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]

    entity._handle_agent_event(
        types.SimpleNamespace(
            data={
                "entry_id": entry.entry_id,
                "event_type": "smartphone_forwarding_changed",
                "mode": None,
            }
        )
    )

    # Displayed as unknown, but the shared store keeps the last real reading.
    assert entity._state == "unknown"
    assert entry.runtime_data.event_state.smartphone_forwarding_mode == "blocked"


def test_smartphone_forwarding_select_reads_again_after_an_agent_restart() -> None:
    """A restarted agent reads the mode silently; a change made on the device
    while it was down reaches Home Assistant only when it asks again."""

    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]
    tasks: list[Any] = []
    written: list[bool] = []
    entity.hass = SimpleNamespace(  # type: ignore[assignment]
        async_create_background_task=lambda coro, name: tasks.append(coro),
    )
    entity.async_write_ha_state = lambda: written.append(True)  # type: ignore[method-assign]

    entity._handle_agent_restarted("another-entry")
    assert tasks == []
    entity._handle_agent_restarted("entry-1")
    asyncio.run(tasks[0])

    assert entry.runtime_data.api.active_reads == 1
    assert entity.current_option == "blocked" and written


def test_a_forwarding_reading_tells_the_readiness_sensor(monkeypatch) -> None:
    from custom_components.bticino_c300x import select as select_module

    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr(select_module, "async_dispatcher_send", lambda *args: sent.append(args))
    entry = _FakeEntry()
    entity = C300XSmartphoneForwardingModeSelect(entry)  # type: ignore[arg-type]
    entity.hass = "hass"  # type: ignore[assignment]

    asyncio.run(entity.async_update())
    asyncio.run(entity.async_update())

    assert sent == [("hass", "bticino_c300x_forwarding_changed", "entry-1")]


def test_audio_codec_select_works_again_after_ha_adds_it_again() -> None:
    """HA removes the entity and adds the same object again after an entity_id change."""

    async def run() -> None:
        entry = _audio_codec_entry()
        entity = C300XAudioCodecSelect(entry)
        removers: list[Any] = []
        tasks: list[asyncio.Task[None]] = []
        entity.hass = SimpleNamespace(
            async_create_task=lambda coro: tasks.append(asyncio.create_task(coro)) or tasks[-1],
        )
        entity.async_on_remove = removers.append
        await entity.async_added_to_hass()
        await entity.async_update()
        await entity.async_select_option("pcmu")
        assert entity.extra_state_attributes["pending_option"] == "pcmu"

        for remove in removers:
            remove()
        removers.clear()
        await entity.async_added_to_hass()

        entry.runtime_data.api.audio_codec_running_state = "pcmu"
        entity._handle_reboot_reconnect(entry.entry_id)
        assert len(tasks) == 1
        await tasks[0]
        assert entity.current_option == "pcmu"
        assert entity.extra_state_attributes["pending_option"] is None

    asyncio.run(run())
