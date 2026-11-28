"""Doorbell services report agent failures as translated errors and start reauth."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import services
from custom_components.bticino_c300x.api_errors import (
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
)
from custom_components.bticino_c300x.const import (
    CONF_DOOR_AUDIO_LEVEL_DB,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.data import (
    BticinoC300XRuntimeData,
    C300XConnectionState,
    C300XEventState,
)
from custom_components.bticino_c300x.use_cases import common


def _setup(monkeypatch):
    api = SimpleNamespace(
        async_doorbell_video_status=AsyncMock(return_value={"bridge": {}}),
        async_set_doorstation_audio_level=AsyncMock(),
        async_activate_doorbell_video=AsyncMock(return_value={"ok": True}),
        async_answer_doorbell_call=AsyncMock(return_value={"ok": True}),
    )
    runtime = BticinoC300XRuntimeData(
        api=api, capabilities={"doorbell_video": True, "doorbell_call": True},
        event_state=C300XEventState(), connection_state=C300XConnectionState(),
        agent_info={}, loaded_platforms=(),
    )
    entry = SimpleNamespace(
        entry_id="entry", runtime_data=runtime, data={},
        options={CONF_VIDEO_ENABLED: True, CONF_DOOR_AUDIO_LEVEL_DB: 6},
        async_start_reauth=Mock(), state=ConfigEntryState.LOADED,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=lambda *_a, **_k: [entry],
            async_loaded_entries=lambda _domain: [entry],
        ),
    )
    monkeypatch.setattr(common, "async_get_hass", Mock(return_value=hass))
    monkeypatch.setattr(common, "async_dispatcher_send", Mock())
    return hass, entry, api


@pytest.mark.parametrize("failure", ["offline", "auth"])
def test_answer_reports_a_failed_status_read_as_agent_command_failed(monkeypatch, failure):
    hass, entry, api = _setup(monkeypatch)
    api.async_doorbell_video_status.side_effect = (
        C300XAgentApiAuthError() if failure == "auth" else C300XAgentApiConnectionError("offline")
    )
    handler = services._C300XServiceHandlers(hass).async_answer_call
    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(handler(SimpleNamespace(data={})))
    assert err.value.translation_key == "agent_command_failed"
    api.async_answer_doorbell_call.assert_not_awaited()
    if failure == "auth":
        entry.async_start_reauth.assert_called_once_with(hass)
        assert entry.runtime_data.connection_state.authentication_failed
    else:
        entry.async_start_reauth.assert_not_called()


@pytest.mark.parametrize("service,operation", [
    ("answer_call", "answer_doorbell_call"), ("activate_doorbell_video", "activate_doorbell_video"),
])
def test_failed_level_write_is_logged_and_the_command_still_runs(monkeypatch, caplog, service, operation):
    hass, _entry, api = _setup(monkeypatch)
    api.async_set_doorstation_audio_level.side_effect = C300XAgentApiConnectionError("offline")
    handler = getattr(services._C300XServiceHandlers(hass), f"async_{service}")
    with caplog.at_level(logging.WARNING):
        asyncio.run(handler(SimpleNamespace(data={"audio": True})))
    api.async_set_doorstation_audio_level.assert_awaited_once_with(6, 0)
    command = getattr(api, f"async_{operation}")
    command.assert_awaited_once()
    assert "door audio level failed" in caplog.text


def test_failed_level_write_and_failed_command_report_the_command_error(monkeypatch):
    hass, entry, api = _setup(monkeypatch)
    api.async_set_doorstation_audio_level.side_effect = C300XAgentApiAuthError()
    api.async_activate_doorbell_video.side_effect = C300XAgentApiAuthError()
    handler = services._C300XServiceHandlers(hass).async_activate_doorbell_video
    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(handler(SimpleNamespace(data={"audio": True})))
    assert err.value.translation_key == "agent_command_failed"
    entry.async_start_reauth.assert_called_once_with(hass)


def test_a_unit_target_answers_and_hangs_up_only_that_units_call(monkeypatch):
    from custom_components.bticino_c300x.service_target import ServiceTarget

    hass, entry, api = _setup(monkeypatch)
    api.async_call_action_target = AsyncMock(return_value="0badc0de-2")
    api.async_hangup_doorbell_call = AsyncMock(return_value={"ok": True})
    entry.runtime_data.resources.prepare_doorbell_video_stop = None
    monkeypatch.setattr(services, "_target_for_call", lambda _hass, _call: ServiceTarget(entry, "21"))
    handlers = services._C300XServiceHandlers(hass)
    asyncio.run(handlers.async_answer_call(SimpleNamespace(data={})))
    asyncio.run(handlers.async_hangup_call(SimpleNamespace(data={})))
    api.async_answer_doorbell_call.assert_awaited_once_with(None, unit="21")
    api.async_call_action_target.assert_awaited_once_with(None, "hangup", unit="21")
    api.async_hangup_doorbell_call.assert_awaited_once_with("0badc0de-2")
