"""The display follow-up of an agent update is decided by state, not by an answer.

The station applies an update by itself once it has the files; Home Assistant
re-applies the display hooks afterwards. The entry data carries one mark: an
update was started and its follow-up has not run to its end. These tests run
the repair flow against a station model that keeps what is on its display and
counts every display write and restart.
"""

from __future__ import annotations

import asyncio
import contextlib
import types
from typing import Any

import pytest
from test_agent_update_repairs import (
    FakeAgentUpdateState,
    FakeEntry,
    FakeHass,
    FakePatchApi,
    FakeRuntimeData,
    FakeSelfUpdateState,
)

from custom_components.bticino_c300x import repairs
from custom_components.bticino_c300x.agent_update import compare_agent_bundle
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentUpdateError,
)
from custom_components.bticino_c300x.const import (
    CONF_AGENT_UPDATE_QML_PENDING,
    CONF_DEVICE_UI_ENABLED,
)

BUNDLE = {"agent_version": "1.1.0", "bundle_hash": "sha256:new"}
SSH_LOGIN = {"bootstrap_ssh_username": "root", "bootstrap_ssh_password": "secret"}
DONE = {"type": "create_entry", "data": {}}


class _HomeAssistantStopped(BaseException):
    """Home Assistant ends while the step waits for the station."""


class _Station(FakePatchApi):
    """A station with an agent version, display sources and installed pages.

    ``core`` and ``full`` are the versions of the pages on the display, None
    when not installed; ``source`` is the version the agent carries. The
    patch status only looks for markers, as the real one does: old pages
    count as "patched".
    """

    def __init__(self, *, full: bool = True, display_patch: bool = True) -> None:
        super().__init__()
        self.version = "1.0.0"
        self.self_update = True
        self.display_patch = display_patch
        self.source = 1
        self.core: int | None = 1 if display_patch else None
        self.full: int | None = 1 if full and display_patch else None
        self.writes: list[str] = []
        self.restarts = 0
        self.updates = 0
        self.stop_at: str | None = None
        # What an update of this bundle changes on the station.
        self.update_changes_display = False
        # How the next apply request ends: "ok", "lost", "http_500", "refused",
        # "not_sent" or "stop".
        self.apply_ends = "ok"
        self.installer_ends = "ok"
        self.firewall_status = {"available": True, "patched": False, "state": "original"}
        self.ipv6_firewall_status = dict(self.firewall_status)

    # -- the station itself -------------------------------------------------

    def install_bundle(self) -> dict[str, Any]:
        changed = self.version != "1.1.0"
        display_changed = changed and self.update_changes_display
        self.version = "1.1.0"
        self.self_update = True
        if display_changed:
            self.source = 2
        if changed:
            self.updates += 1
        return {"ok": True, "runtime_changed": changed, "qml_patch_changed": display_changed}

    def setup(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        if not self.display_patch:
            capabilities["maintenance"] = {"supported": True, "qml_core_patch": False}
        agent: dict[str, Any] = {"self_update_supported": self.self_update}
        if self.version == "1.1.0":
            agent["bundle_hash"] = "sha256:new"
        return {"version": self.version, "capabilities": capabilities, "agent": agent}

    def display_current(self) -> bool:
        return all(page in (None, self.source) for page in (self.core, self.full))

    def stop(self, point: str) -> None:
        if self.stop_at == point:
            self.stop_at = None
            raise _HomeAssistantStopped(point)

    def _status(self, changed_files: int | None = None) -> dict[str, Any]:
        status: dict[str, Any] = {
            "available": True,
            "patched": self.full is not None,
            "state": "patched" if self.full is not None else "original",
            "core_patched": self.core is not None,
            "core_state": "patched" if self.core is not None else "original",
        }
        if changed_files is not None:
            # As the API client returns it: the script's answer under "raw".
            status["raw"] = {**status, "changed_files": changed_files}
        return status

    # -- the API the repair uses --------------------------------------------

    async def async_validate_setup(self) -> dict[str, Any]:
        return self.setup()

    async def async_qml_patch_status(self) -> dict[str, Any]:
        self.calls.append("qml_status")
        self.stop("status")
        return self._status()

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        self.stop("core_apply")
        assert self.display_patch, "this agent has no Display patch"
        changed = int(self.core != self.source)
        if changed:
            self.core = self.source
            self.writes.append("core")
            self.restarts += 1
        if self.stop_at == "status_after":
            self.stop_at = "status"
        return self._status(changed)

    async def async_apply_qml_patch(self, *, dynamic_homepage: bool = False) -> dict[str, Any]:
        self.stop("full_apply")
        assert self.display_patch, "this agent has no Display patch"
        changed = int(self.full != self.source)
        if changed:
            self.full = self.source
            self.writes.append("full")
            self.restarts += 1
        return self._status(changed)

    async def async_reload_gui(self) -> dict[str, Any]:
        self.stop("reload")
        self.restarts += 1
        return {"ok": True, "action": "reload_gui"}


def _update_state(station: _Station, data: dict[str, Any]) -> Any:
    # As RuntimeManager.async_validate_agent compares at every setup.
    return compare_agent_bundle(
        station.setup(), BUNDLE, qml_patch_pending=CONF_AGENT_UPDATE_QML_PENDING in data,
    )


def _start(
    station: _Station,
    data: dict[str, Any] | None = None,
    *,
    display: bool | None = True,
) -> tuple[FakeEntry, repairs.DeviceAgentUpdateRepairFlow]:
    """Set the entry up from its stored data and open the update repair."""

    options = {} if display is None else {CONF_DEVICE_UI_ENABLED: display}
    runtime = FakeRuntimeData(station)
    runtime.agent_info = station.setup()
    entry = FakeEntry(
        runtime_data=runtime,
        data={"agent_host": "192.0.2.60", "agent_token": "token", **(data or {})},
        options=options,
    )
    state = _update_state(station, entry.data)
    # The repair is opened although nothing is due only in these tests.
    entry.runtime_data.agent_update_state = state if state.update_required else FakeSelfUpdateState()
    flow = repairs.DeviceAgentUpdateRepairFlow(FakeHass(entry), "entry-1")  # type: ignore[arg-type]
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}  # type: ignore[method-assign]
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}  # type: ignore[method-assign]
    return entry, flow


def _restart(
    station: _Station, entry: FakeEntry,
) -> tuple[FakeEntry, repairs.DeviceAgentUpdateRepairFlow]:
    """Home Assistant starts again: new runtime and flow, the stored entry."""

    return _start(station, dict(entry.data), display=entry.options.get(CONF_DEVICE_UI_ENABLED))


def _confirm(flow: repairs.DeviceAgentUpdateRepairFlow) -> Any:
    return asyncio.run(flow.async_step_confirm({}))


def _assert_settled(station: _Station, entry: FakeEntry) -> None:
    assert station.display_current()
    assert CONF_AGENT_UPDATE_QML_PENDING not in entry.data
    assert not _update_state(station, entry.data).update_required


def _assert_repair_offered(station: _Station, entry: FakeEntry) -> None:
    state = _update_state(station, entry.data)
    assert state.update_required
    assert state.self_update_repair_supported


@pytest.fixture(autouse=True)
def home_assistant(monkeypatch) -> None:
    async def apply_update(_hass: Any, api: _Station) -> dict[str, Any]:
        ends, api.apply_ends = api.apply_ends, "ok"
        if ends == "not_sent":
            raise RuntimeError("packaged native-agent bundle is missing")
        if ends == "refused":
            raise C300XAgentUpdateError("refused", status=409, code="update_root_already_writable")
        answer = api.install_bundle()
        if ends == "stop":
            raise _HomeAssistantStopped("apply")
        if ends == "lost":
            lost = C300XAgentApiConnectionError("device-agent request timed out")
            lost.__cause__ = TimeoutError()
            raise lost
        if ends == "http_500":
            # agent_update.c reports a failed finalisation after the files are
            # committed; http.c answers 500 update_apply_failed.
            raise C300XAgentApiConnectionError("device agent returned HTTP 500: update_apply_failed")
        return answer

    async def verify(_hass: Any, api: _Station, _result: Any) -> dict[str, Any]:
        api.stop("verify")
        return api.setup()

    async def migrate_mqtt(_api: Any) -> None:
        return None

    async def bundle(_hass: Any) -> dict[str, Any]:
        return BUNDLE

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)
    monkeypatch.setattr(repairs, "_async_verify_agent_after_update", verify)
    monkeypatch.setattr(repairs, "_async_migrate_mqtt_after_update", migrate_mqtt)
    monkeypatch.setattr(repairs, "async_load_packaged_bundle_metadata", bundle)
    monkeypatch.setattr(repairs, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda **_: None)


# -- the normal path ---------------------------------------------------------


@pytest.mark.parametrize("display", [True, False])
def test_update_without_display_changes_writes_no_page(display) -> None:
    station = _Station(full=display)
    entry, flow = _start(station, display=display)

    assert _confirm(flow) == DONE

    assert station.updates == 1
    assert station.writes == []
    # Active pages are restarted once for the new agent; no page is written.
    assert station.restarts == (1 if display else 0)
    _assert_settled(station, entry)


@pytest.mark.parametrize(("display", "written"), [(True, ["core", "full"]), (False, ["core"])])
def test_update_with_display_changes_reapplies_the_pages(display, written) -> None:
    station = _Station(full=display)
    station.update_changes_display = True
    entry, flow = _start(station, display=display)

    assert _confirm(flow) == DONE

    assert station.writes == written
    _assert_settled(station, entry)


# -- an update that did not happen -------------------------------------------


@pytest.mark.parametrize("ends", ["not_sent", "refused"])
def test_refused_update_writes_nothing_and_the_retry_finishes(ends) -> None:
    station = _Station()
    station.update_changes_display = True
    entry, flow = _start(station)
    station.apply_ends = ends

    failed = _confirm(flow)

    assert failed["type"] == "form"
    assert failed["errors"]
    assert station.updates == 0
    assert (station.writes, station.restarts) == ([], 0)

    # The retry in the same flow updates the station and finishes the follow-up.
    assert _confirm(flow) == DONE
    assert station.writes == ["core", "full"]
    _assert_settled(station, entry)


def test_refused_update_of_a_current_station_ends_without_a_restart() -> None:
    """Whatever a refused run left is cleared by a follow-up that finds nothing to do."""

    station = _Station()
    station.install_bundle()
    entry, flow = _start(station)
    station.apply_ends = "refused"
    assert _confirm(flow)["type"] == "form"

    entry, flow = _restart(station, entry)
    assert _confirm(flow) == DONE

    assert (station.writes, station.restarts) == ([], 0)
    _assert_settled(station, entry)


# -- the answer of the apply does not arrive, or reports a failure -----------


@pytest.mark.parametrize("ends", ["lost", "http_500"])
@pytest.mark.parametrize("display", [True, False])
def test_failed_answer_after_the_stations_apply_keeps_the_follow_up(ends, display) -> None:
    """Holes 1 and 2: HTTP 500 after the commit, and an entry with Display off."""

    station = _Station(full=display)
    station.update_changes_display = True
    entry, flow = _start(station, display=display)
    station.apply_ends = ends

    failed = _confirm(flow)

    assert failed["errors"] == {"base": "update_failed"}
    assert station.updates == 1
    assert not station.display_current()
    _assert_repair_offered(station, entry)

    # The station has the bundle already and reports no change this time.
    assert _confirm(flow) == DONE
    assert station.writes == (["core", "full"] if display else ["core"])
    _assert_settled(station, entry)


def test_lost_answer_without_display_changes_does_not_restart_the_display() -> None:
    station = _Station()
    entry, flow = _start(station)
    station.apply_ends = "lost"
    assert _confirm(flow)["type"] == "form"

    assert _confirm(flow) == DONE

    assert (station.writes, station.restarts) == ([], 0)
    _assert_settled(station, entry)


# -- Home Assistant stops between "before apply" and "follow-up done" --------


@pytest.mark.parametrize(
    "stopped_at", ["apply", "verify", "core_apply", "full_apply", "reload", "status_after"]
)
@pytest.mark.parametrize("display", [True, False])
def test_restart_at_any_point_finishes_the_follow_up(stopped_at, display) -> None:
    station = _Station(full=display)
    station.update_changes_display = True
    entry, flow = _start(station, display=display)
    if stopped_at == "apply":
        station.apply_ends = "stop"
    else:
        station.stop_at = stopped_at

    try:
        result = _confirm(flow)
    except _HomeAssistantStopped:
        assert station.updates == 1
        _assert_repair_offered(station, entry)

        entry, flow = _restart(station, entry)
        assert _confirm(flow) == DONE
    else:
        # With Display off the full apply never runs, so nothing stopped.
        assert (stopped_at, display) == ("full_apply", False)
        assert result == DONE

    assert sorted(set(station.writes)) == (["core", "full"] if display else ["core"])
    _assert_settled(station, entry)


def test_bootstrap_update_checks_the_display_whatever_the_answers_say(monkeypatch) -> None:
    """The two-pass update of an old agent: its updater's answer is not relied on."""

    station = _Station()
    entry, flow = _start(station)
    entry.runtime_data.agent_update_state = types.SimpleNamespace(
        self_update_repair_supported=True, update_required=True,
        payload_bootstrap_required=True, repair_placeholders={},
    )
    passes: list[int] = []

    async def apply_update(_hass: Any, api: _Station) -> dict[str, Any]:
        passes.append(1)
        api.install_bundle()
        # New pages are installed that the answer does not report.
        api.source = 2
        return {"ok": True, "qml_patch_changed": False}

    monkeypatch.setattr(repairs, "async_apply_packaged_agent_update", apply_update)

    assert _confirm(flow) == DONE

    assert len(passes) == 2
    assert station.writes == ["core", "full"]
    _assert_settled(station, entry)


# -- the Display setting of the moment decides -------------------------------


def test_display_switched_off_after_the_update_is_not_patched_again() -> None:
    """Hole 4: a follow-up noted with Display on runs after Display was switched off."""

    station = _Station()
    station.update_changes_display = True
    entry, flow = _start(station)
    station.apply_ends = "stop"
    with pytest.raises(_HomeAssistantStopped):
        _confirm(flow)
    assert entry.data[CONF_AGENT_UPDATE_QML_PENDING] is True

    # The user switches Display off: the switch restores the stock pages.
    station.full = None
    entry.options = {CONF_DEVICE_UI_ENABLED: False}
    entry, flow = _restart(station, entry)

    assert _confirm(flow) == DONE

    assert station.writes == ["core"]
    assert station.full is None
    _assert_settled(station, entry)


def test_display_switched_on_after_the_update_gets_the_new_pages() -> None:
    station = _Station(full=False)
    station.update_changes_display = True
    entry, flow = _start(station, display=False)
    station.apply_ends = "stop"
    with pytest.raises(_HomeAssistantStopped):
        _confirm(flow)

    entry.options = {CONF_DEVICE_UI_ENABLED: True}
    entry, flow = _restart(station, entry)

    assert _confirm(flow) == DONE

    assert station.writes == ["core", "full"]
    _assert_settled(station, entry)


# -- values stored by released versions --------------------------------------


@pytest.mark.parametrize(
    ("stored", "display", "full_installed", "written"),
    [
        # An entry that never chose a Display setting: the stored value tells.
        (True, None, True, ["core", "full"]),
        (False, None, False, ["core"]),
        # A chosen setting wins over the stored value.
        (False, True, True, ["core", "full"]),
        (True, False, False, ["core"]),
    ],
)
def test_stored_values_of_released_versions_still_finish(
    stored, display, full_installed, written,
) -> None:
    station = _Station(full=full_installed)
    station.install_bundle()
    station.source = 2
    entry, flow = _start(station, {CONF_AGENT_UPDATE_QML_PENDING: stored}, display=display)
    _assert_repair_offered(station, entry)

    assert _confirm(flow) == DONE

    assert station.writes == written
    assert (station.full is not None) is full_installed
    _assert_settled(station, entry)


def test_stored_value_with_current_pages_clears_without_a_restart() -> None:
    station = _Station()
    station.install_bundle()
    entry, flow = _start(station, {CONF_AGENT_UPDATE_QML_PENDING: True})

    assert _confirm(flow) == DONE

    assert (station.writes, station.restarts) == ([], 0)
    _assert_settled(station, entry)


# -- an agent without a Display patch ----------------------------------------


@pytest.mark.parametrize("ends", ["ok", "lost", "stop"])
def test_agent_without_display_patch_gets_no_follow_up(ends) -> None:
    """Hole 5: nothing is due on such a station, so a lost answer leaves no repair."""

    station = _Station(display_patch=False)
    # The Display setting is on, as an entry can carry it to such a station.
    entry, flow = _start(station, display=True)
    station.apply_ends = ends

    with contextlib.suppress(_HomeAssistantStopped):
        _confirm(flow)

    assert station.updates == 1
    assert CONF_AGENT_UPDATE_QML_PENDING not in entry.data
    assert not _update_state(station, entry.data).update_required


def test_agent_without_display_patch_clears_a_stored_mark() -> None:
    station = _Station(display_patch=False)
    station.install_bundle()
    entry, flow = _start(station, {CONF_AGENT_UPDATE_QML_PENDING: True}, display=False)

    assert _confirm(flow) == DONE

    _assert_settled(station, entry)


# -- the SSH install of an agent that cannot update itself -------------------


@pytest.fixture
def ssh_station(monkeypatch) -> _Station:
    station = _Station()
    station.self_update = False
    station.update_changes_display = True

    async def install(*_args: Any, **_kwargs: Any) -> Any:
        ends, station.installer_ends = station.installer_ends, "ok"
        if ends == "login":
            raise RuntimeError("login refused")
        answer = station.install_bundle()
        if ends == "stop":
            raise _HomeAssistantStopped("installer")
        if ends == "fails":
            # The files are on the station, then the restart check fails.
            raise RuntimeError("startup verification failed")
        changed = ["/home/bticino/cfg/extra/c300x/qml/HomeAssistant.qml"]
        return types.SimpleNamespace(changed_files=changed if answer["qml_patch_changed"] else [])

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def wait_for_agent(api: _Station) -> dict[str, Any]:
        api.stop("wait")
        return api.setup()

    monkeypatch.setattr(repairs, "async_install_device_agent", install)
    monkeypatch.setattr(repairs, "async_ensure_installer_dependencies", nothing)
    monkeypatch.setattr(repairs, "_async_wait_for_agent_after_update", wait_for_agent)
    return station


def _ssh_install(flow: repairs.DeviceAgentUpdateRepairFlow) -> Any:
    return asyncio.run(flow.async_step_ssh_install(SSH_LOGIN))


def test_ssh_install_reapplies_the_pages(ssh_station) -> None:
    entry, flow = _start(ssh_station)
    assert not entry.runtime_data.agent_update_state.self_update_repair_supported

    assert _ssh_install(flow) == DONE

    assert ssh_station.writes == ["core", "full"]
    _assert_settled(ssh_station, entry)


@pytest.mark.parametrize("ends", ["fails", "stop", "wait"])
def test_ssh_install_cut_mid_way_is_finished_after_a_restart(ssh_station, ends) -> None:
    """Hole 3: the installer changed the station, then failed or Home Assistant stopped."""

    entry, flow = _start(ssh_station)
    if ends == "wait":
        ssh_station.stop_at = "wait"
    else:
        ssh_station.installer_ends = ends

    try:
        failed = _ssh_install(flow)
    except _HomeAssistantStopped:
        pass
    else:
        assert failed["errors"] == {"base": "ssh_install_failed"}
    assert ssh_station.updates == 1
    assert not ssh_station.display_current()

    # The new agent runs and can update itself: the setup offers the repair.
    _assert_repair_offered(ssh_station, entry)
    entry, flow = _restart(ssh_station, entry)
    assert _confirm(flow) == DONE

    assert ssh_station.writes == ["core", "full"]
    _assert_settled(ssh_station, entry)


def test_ssh_install_that_changed_nothing_is_retried_without_a_restart(ssh_station) -> None:
    entry, flow = _start(ssh_station)
    entry.runtime_data.agent_update_state = FakeAgentUpdateState()
    ssh_station.installer_ends = "login"

    assert _ssh_install(flow)["errors"] == {"base": "ssh_install_failed"}
    assert (ssh_station.updates, ssh_station.writes, ssh_station.restarts) == (0, [], 0)

    assert _ssh_install(flow) == DONE
    assert ssh_station.writes == ["core", "full"]
    _assert_settled(ssh_station, entry)


# -- the Qt 5 display of firmware 3.0.x ----------------------------------------


class _Qt5Station(_Station):
    """The same station with the Qt 5 display of firmware 3.0.x: its status
    names the overlay, and a restart is asked for with the longer wait."""

    def _status(self, changed_files: int | None = None) -> dict[str, Any]:
        status = super()._status(changed_files)
        status.update(qt5_overlay="active", gui_running=True)
        if changed_files is not None:
            status["raw"].update(qt5_overlay="active", gui_running=True)
        return status

    async def async_reload_gui(self, *, display_restart: bool = False) -> dict[str, Any]:
        assert display_restart
        return await super().async_reload_gui()

    @staticmethod
    def _restarted(status: dict[str, Any]) -> dict[str, Any]:
        # A write that changed files filed its own display restart.
        if status["raw"]["changed_files"]:
            status["raw"]["gui_restarted"] = True
        return status

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        return self._restarted(await super().async_apply_qml_core_patch())

    async def async_apply_qml_patch(self, *, dynamic_homepage: bool = False) -> dict[str, Any]:
        # The full apply carries the core files: one write, one restart.
        self.stop("full_apply")
        changed = int(self.full != self.source or self.core != self.source)
        if changed:
            self.core = self.full = self.source
            self.writes.append("full")
            self.restarts += 1
        return self._restarted(self._status(changed))


def _qt5(entry: FakeEntry) -> None:
    # The status read at setup names the Qt 5 overlay.
    entry.runtime_data.qml_patch_status = {"qt5_overlay": "active", "gui_running": True}


@pytest.mark.parametrize("display", [True, False])
def test_a_runtime_only_update_restarts_the_qt5_display_once(display) -> None:
    """The overlay's preload library is part of the agent runtime: the hooks are
    applied again (no page changed, none written) and the display restarts once,
    also with Display off, whose core hook is in the overlay too."""

    station = _Qt5Station(full=display)
    entry, flow = _start(station, display=display)
    _qt5(entry)

    assert _confirm(flow) == DONE

    assert station.writes == []
    assert station.restarts == 1
    _assert_settled(station, entry)


@pytest.mark.parametrize("restarted", [False, True])
def test_a_lost_answer_on_the_qt5_display_restarts_it_once(restarted) -> None:
    """Without the answer nobody knows whether the runtime with the preload
    library changed; on 1.7.x/2.0.x the same case restarts nothing."""

    station = _Qt5Station()
    entry, flow = _start(station)
    _qt5(entry)
    station.apply_ends = "lost"
    assert _confirm(flow)["type"] == "form"
    if restarted:
        entry, flow = _restart(station, entry)
        _qt5(entry)

    assert _confirm(flow) == DONE

    assert (station.writes, station.restarts) == ([], 1)
    _assert_settled(station, entry)


@pytest.mark.parametrize(("display", "written"), [(True, ["full"]), (False, ["core"])])
def test_an_update_with_new_pages_restarts_the_qt5_display_once(display, written) -> None:
    """Every live restart on 3.0.6 risks the display race: the full apply carries
    the core files, and its own restart is the only one."""

    station = _Qt5Station(full=display)
    station.update_changes_display = True
    entry, flow = _start(station, display=display)
    _qt5(entry)

    assert _confirm(flow) == DONE

    assert station.writes == written
    assert station.restarts == 1
    _assert_settled(station, entry)
