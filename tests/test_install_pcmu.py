"""A new installation on a C300X with firmware 1.7.x or 2.0.2 switches to PCMU with one restart."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import station_flow_harness

from custom_components.bticino_c300x import (
    config_flow,
    config_flow_auth,
    install_pcmu,
    runtime_manager,
)
from custom_components.bticino_c300x._api_calls import normalize_calls
from custom_components.bticino_c300x._api_normalize import normalize_doorbell_video
from custom_components.bticino_c300x.api import C300XAgentApi, C300XAgentApiError
from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DISPLAY_SETTING_PENDING,
    CONF_INSTALL_PCMU_PENDING,
    CONF_MAINTENANCE_TOKEN,
    CONF_REINSTALL_AGENT,
    CONF_VIDEO_ENABLED,
    SIGNAL_AUDIO_CODEC_STATUS,
)

FW_1_7_19 = {"model": "C300X", "display_kind": "qt4_ondisk", "firmware": "1.7.19"}
FW_2_0_2 = {"model": "C300X", "display_kind": "qt4_ondisk", "firmware": "2.0.2"}
FW_3_0_6 = {"model": "C300X", "display_kind": "qt5_rcc", "firmware": "3.0.6"}
C100X = {"model": "C100X", "display_kind": "qt5_ondisk", "firmware": "1.5.8"}
TEXTS = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"


# --- the setup --------------------------------------------------------------


def _flow(monkeypatch: pytest.MonkeyPatch, info: dict[str, Any], *, needs_token: bool = False) -> Any:
    flow = BticinoC300XConfigFlow()
    flow.hass = station_flow_harness.hass()
    flow.context = {"source": "user"}
    flow._setup_connection = {"name": "Door", CONF_AGENT_HOST: "a.local", CONF_AGENT_PORT: 8091}
    flow._setup_agent_needs_token = needs_token
    flow._c100x_confirmed = True
    flow._async_abort_if_manual_setup_duplicate = AsyncMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()

    async def adopt(**_kwargs: Any) -> None:
        flow._setup_agent_info.clear()
        flow._setup_agent_info.update(info)

    flow._async_adopt_agent_unique_id = adopt
    installed = SimpleNamespace(display_pending=False, display_kind=info.get("display_kind", ""))
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent", AsyncMock(return_value=installed))
    monkeypatch.setattr(config_flow, "_async_probe_agent", AsyncMock(return_value="reachable"))
    monkeypatch.setattr(config_flow, "async_migrate_legacy_mqtt_for_connection", AsyncMock())
    monkeypatch.setattr(
        config_flow_auth, "async_validate_connection",
        AsyncMock(return_value=({"device_id": "device-a", **info}, {})),
    )
    return flow


def _create(flow: Any, first_step: Any) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        result = await first_step(flow)
        assert result["step_id"] == "user_features"
        feature_data, errors = config_flow._feature_input({CONF_VIDEO_ENABLED: False})
        assert not errors
        return await flow._async_create_setup_entry(feature_data)

    result = asyncio.run(run())
    assert result["type"] == "create_entry"
    return result


def _install(flow: Any) -> Any:
    return flow.async_step_agent_missing({"bootstrap_install_agent": True})


@pytest.mark.parametrize("info", [FW_1_7_19, FW_2_0_2])
def test_a_new_installation_on_1_7_or_2_0_marks_its_entry_and_says_so(monkeypatch, info):
    result = _create(_flow(monkeypatch, info), _install)
    assert result["data"][CONF_INSTALL_PCMU_PENDING] is True
    # The Display setting still comes first at the first start.
    assert result["data"][CONF_DISPLAY_SETTING_PENDING] is True
    assert result["description"] == "pcmu_restart"
    assert result["description_placeholders"] == {"model": "C300X"}


@pytest.mark.parametrize("info", [FW_3_0_6, C100X, {}], ids=["3.0.6", "c100x", "unknown"])
def test_3_0_6_and_the_c100x_get_no_mark(monkeypatch, info):
    result = _create(_flow(monkeypatch, info), _install)
    assert CONF_INSTALL_PCMU_PENDING not in result["data"]
    assert result.get("description") is None


def test_an_agent_that_was_there_already_keeps_its_codec(monkeypatch):
    flow = _flow(monkeypatch, FW_1_7_19, needs_token=True)
    result = _create(
        flow, lambda flow: flow.async_step_agent_auth({CONF_AGENT_TOKEN: "a", CONF_MAINTENANCE_TOKEN: "m"}),
    )
    assert CONF_INSTALL_PCMU_PENDING not in result["data"]
    assert result.get("description") is None


def test_the_setup_reinstall_of_an_agent_without_its_keys_keeps_the_codec(monkeypatch):
    flow = _flow(monkeypatch, FW_1_7_19, needs_token=True)
    result = _create(flow, lambda flow: flow.async_step_agent_auth({CONF_REINSTALL_AGENT: True}))
    config_flow.async_install_device_agent.assert_awaited_once()
    assert CONF_INSTALL_PCMU_PENDING not in result["data"]
    assert result.get("description") is None


def test_the_restart_text_exists_in_every_language():
    words = {
        "strings": ("restarts once", "PCMU"), "en": ("restarts once", "PCMU"),
        "de": ("einmal neu", "PCMU"), "it": ("riavvia una volta", "PCMU"), "fr": ("redémarre une fois", "PCMU"),
        "es": ("se reinicia una vez", "PCMU"),
    }
    base = json.loads((TEXTS / "strings.json").read_text(encoding="utf-8"))
    assert base["config"]["create_entry"] == json.loads(
        (TEXTS / "translations" / "en.json").read_text(encoding="utf-8")
    )["config"]["create_entry"]
    for lang, expected in words.items():
        path = TEXTS / "strings.json" if lang == "strings" else TEXTS / "translations" / f"{lang}.json"
        text = json.loads(path.read_text(encoding="utf-8"))["config"]["create_entry"]["pcmu_restart"]
        assert "{model}" in text and all(word in text for word in expected), lang


# --- the first start --------------------------------------------------------


class _Api:
    def __init__(self, *, busy: list[str] | None = None, apply_error: Exception | None = None,
                 reboot_error: Exception | None = None, running: str = "speex") -> None:
        self.calls: list[Any] = []
        self.busy = list(busy or [])
        self.apply_error = apply_error
        self.reboot_error = reboot_error
        self.running = running

    async def async_calls(self) -> Any:
        self.calls.append("calls")
        state = self.busy[0] if self.busy else "idle"
        calls = [{"call_id": "0a1b2c3d-1", "kind": "ring", "state": "ringing"}] if state == "ringing" else []
        station = {"code": 0, "state": "idle", "age_ms": 5000}
        if state == "conversation":
            station = {"code": 5, "state": "conversation", "age_ms": 5000}
        return normalize_calls({"calls": calls, "station_state": station})

    async def async_doorbell_video_status(self) -> Any:
        self.calls.append("video")
        state = self.busy.pop(0) if self.busy else "idle"
        return normalize_doorbell_video({"bridge": {"clients": 1 if state == "stream" else 0}})

    async def async_apply_audio_codec(self, *, reboot: bool = True) -> dict[str, Any]:
        self.calls.append(("apply", reboot))
        if self.apply_error is not None:
            raise self.apply_error
        return {
            "ok": True, "state": self.running, "configured_state": "pcmu", "running_state": self.running,
            "changed": self.running != "pcmu", "reboot_required": self.running != "pcmu", "rebooting": False,
        }

    async def async_reboot(self) -> dict[str, Any]:
        self.calls.append("reboot")
        if self.reboot_error is not None:
            raise self.reboot_error
        return {"ok": True, "action": "reboot", "scheduled": True}


_ADVERTISED = {"maintenance": {"supported": True, "audio_codec_apply": True, "reboot": True}}


def _entry(info: dict[str, Any] = FW_1_7_19, *, marked: bool = True, api: _Api | None = None,
           capabilities: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        entry_id="entry-1", data={"agent_host": "a", **({CONF_INSTALL_PCMU_PENDING: True} if marked else {})},
        options={},
        runtime_data=SimpleNamespace(
            agent_info=dict(info), capabilities=_ADVERTISED if capabilities is None else capabilities,
            qml_patch_status={}, api=api or _Api(),
        ),
    )


def _hass() -> Any:
    def update_entry(target: Any, *, data: dict[str, Any]) -> None:
        target.data = data

    return SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock(side_effect=update_entry)))


def _switch(monkeypatch: pytest.MonkeyPatch, entry: Any) -> tuple[Any, list[Any]]:
    sent: list[Any] = []
    monkeypatch.setattr(install_pcmu, "async_dispatcher_send", lambda _hass, *args: sent.append(args))
    hass = _hass()
    asyncio.run(install_pcmu.async_switch_install_pcmu(hass, entry, poll_seconds=0))
    return hass, sent


@pytest.mark.parametrize("info", [FW_1_7_19, FW_2_0_2])
def test_the_first_start_writes_pcmu_without_a_restart_then_restarts_the_station_once(monkeypatch, info):
    api = _Api()
    entry = _entry(info, api=api)
    _hass_, sent = _switch(monkeypatch, entry)
    assert api.calls == ["calls", "video", ("apply", False), "reboot"]
    assert CONF_INSTALL_PCMU_PENDING not in entry.data
    # The codec select reads the staged codec and shows it live after the restart.
    assert sent == [(SIGNAL_AUDIO_CODEC_STATUS, "entry-1", {
        "ok": True, "state": "speex", "configured_state": "pcmu", "running_state": "speex",
        "changed": True, "reboot_required": True, "rebooting": False,
    })]
    # A later start finds no mark and restarts nothing again.
    api.calls.clear()
    _switch(monkeypatch, entry)
    assert api.calls == []


def test_the_first_start_waits_until_no_call_or_stream_runs(monkeypatch):
    api = _Api(busy=["ringing", "conversation", "stream"])
    _switch(monkeypatch, _entry(api=api))
    assert api.calls == ["calls", "video"] * 4 + [("apply", False), "reboot"]


def test_a_station_state_without_its_end_holds_the_restart_only_for_a_while(monkeypatch):
    stale = {"code": 5, "state": "conversation", "age_ms": install_pcmu._STATION_STATE_HOLD_MS}
    api = _Api()

    async def calls() -> Any:
        api.calls.append("calls")
        return normalize_calls({"calls": [], "station_state": stale})

    api.async_calls = calls  # type: ignore[method-assign]
    _switch(monkeypatch, _entry(api=api))
    assert api.calls == ["calls", "video", ("apply", False), "reboot"]


def test_a_failed_write_leaves_speex_restarts_nothing_and_says_why(monkeypatch, caplog):
    api = _Api(apply_error=C300XAgentApiError("device agent returned HTTP 500: audio_codec_apply_failed"))
    entry = _entry(api=api)
    with caplog.at_level(logging.WARNING, logger=install_pcmu.__name__):
        _hass_, sent = _switch(monkeypatch, entry)
    assert api.calls == ["calls", "video", ("apply", False)]
    assert sent == []
    assert CONF_INSTALL_PCMU_PENDING not in entry.data
    assert "stays on Speex" in caplog.text and "audio_codec_apply_failed" in caplog.text


def test_a_busy_agent_is_waited_for_before_the_write(monkeypatch):
    api = _Api()
    busy = [C300XAgentApiConnectionError("device agent returned HTTP 409: maintenance_busy")]
    write = api.async_apply_audio_codec

    async def apply(*, reboot: bool = True) -> dict[str, Any]:
        if busy:
            api.calls.append(("busy", reboot))
            raise busy.pop()
        return await write(reboot=reboot)

    api.async_apply_audio_codec = apply  # type: ignore[method-assign]
    monkeypatch.setattr("custom_components.bticino_c300x.agent_update.asyncio.sleep", AsyncMock())
    _switch(monkeypatch, _entry(api=api))
    assert api.calls == ["calls", "video", ("busy", False), ("apply", False), "reboot"]


def test_a_failed_restart_is_not_asked_for_again(monkeypatch, caplog):
    api = _Api(reboot_error=C300XAgentApiError("device agent request failed"))
    entry = _entry(api=api)
    with caplog.at_level(logging.WARNING, logger=install_pcmu.__name__):
        _switch(monkeypatch, entry)
    assert api.calls == ["calls", "video", ("apply", False), "reboot"]
    assert CONF_INSTALL_PCMU_PENDING not in entry.data
    assert "did not restart" in caplog.text
    api.calls.clear()
    _switch(monkeypatch, entry)
    assert api.calls == []


def test_a_station_on_pcmu_already_does_not_restart(monkeypatch):
    api = _Api(running="pcmu")
    _switch(monkeypatch, _entry(api=api))
    assert api.calls == ["calls", "video", ("apply", False)]


@pytest.mark.parametrize(
    ("info", "capabilities"),
    [
        (FW_3_0_6, None),
        (C100X, None),
        (FW_1_7_19, {"maintenance": {"supported": True, "audio_codec_apply": True}}),
        (FW_1_7_19, {"maintenance": {"supported": True, "reboot": True}}),
    ],
    ids=["3.0.6", "c100x", "no-restart", "no-codec-switch"],
)
def test_no_write_and_no_restart_where_the_switch_does_not_belong(monkeypatch, info, capabilities):
    api = _Api()
    entry = _entry(info, api=api, capabilities=capabilities)
    _switch(monkeypatch, entry)
    assert api.calls == []
    assert CONF_INSTALL_PCMU_PENDING not in entry.data


@pytest.mark.parametrize("info", [FW_1_7_19, FW_3_0_6, C100X])
def test_an_existing_entry_keeps_its_codec(monkeypatch, info):
    api = _Api()
    entry = _entry(info, marked=False, api=api)
    entry.async_create_background_task = Mock()
    install_pcmu.async_start_install_pcmu(_hass(), entry)
    entry.async_create_background_task.assert_not_called()
    _switch(monkeypatch, entry)
    assert api.calls == []


def test_the_reauth_reinstall_keeps_the_codec(monkeypatch):
    from custom_components.bticino_c300x import config_flow_reinstall

    existing = SimpleNamespace(
        data={CONF_AGENT_HOST: "c300x.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "lost",
              CONF_MAINTENANCE_TOKEN: "lost-too"},
        options={}, unique_id="bticino_c300x:c300x.local:8091", entry_id="entry", title="Door",
        update_listeners=[], runtime_data=None,
    )
    flow = BticinoC300XConfigFlow()
    flow.context = {"source": "reauth", "entry_id": "entry"}
    flow._get_reauth_entry = lambda: existing
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_schedule_reload=Mock()))
    flow.async_update_and_abort = Mock(return_value={"type": "abort", "reason": "reauth_successful"})
    monkeypatch.setattr(config_flow_reinstall, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(
        config_flow_reinstall, "async_install_device_agent",
        AsyncMock(return_value=SimpleNamespace(display_pending=False, display_kind="qt4_ondisk")),
    )
    result = asyncio.run(flow.async_step_reauth_confirm({CONF_REINSTALL_AGENT: True}))
    assert result["reason"] == "reauth_successful"
    assert CONF_INSTALL_PCMU_PENDING not in flow.async_update_and_abort.call_args.kwargs["data_updates"]


def test_the_switch_runs_last_at_the_first_start(monkeypatch):
    """After the media user and the Display setting: its one restart starts their files too."""

    order: list[str] = []

    async def step(name: str) -> None:
        order.append(name)

    async def nothing(*_args: Any) -> None:
        return None

    for name in ("_async_track_display_updates", "_async_configure_display_bridge", "_async_refresh_self_test"):
        monkeypatch.setattr(runtime_manager, name, nothing)
    monkeypatch.setattr(runtime_manager, "_async_sync_device_user", lambda *_args: step("media user"))
    monkeypatch.setattr(runtime_manager, "async_settle_display_setting", lambda *_args: step("display"))
    entry = _entry()
    entry.data[CONF_DISPLAY_SETTING_PENDING] = True
    entry.runtime_data.resources = SimpleNamespace()
    tasks: list[Any] = []

    def background(_hass: Any, target: Any, name: str) -> None:
        order.append("pcmu")
        tasks.append((target, name))

    entry.async_create_background_task = background
    hass = _hass()
    manager = runtime_manager.C300XRuntimeManager(hass, entry)
    manager.api = Mock(spec_set=C300XAgentApi)
    manager._platform_gate_state_loaded = True
    asyncio.run(manager.async_sync_device_state())
    assert order == ["media user", "display", "pcmu"]
    target, name = tasks[0]
    assert name == "bticino_c300x_install_pcmu_entry-1"
    monkeypatch.setattr(install_pcmu, "async_dispatcher_send", lambda *_args: None)
    target.close()
    asyncio.run(install_pcmu.async_switch_install_pcmu(hass, entry, poll_seconds=0))
    assert entry.runtime_data.api.calls[-2:] == [("apply", False), "reboot"]

