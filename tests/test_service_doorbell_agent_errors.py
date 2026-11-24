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
    CONF_DOORSTATION_AUDIO_GAIN_DB,
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
        async_set_doorstation_audio_gain_db=AsyncMock(),
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
        options={CONF_VIDEO_ENABLED: True, CONF_DOORSTATION_AUDIO_GAIN_DB: 6.0},
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
    handler = services._C300XServiceHandlers(hass).async_answer_doorbell_call
    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(handler(SimpleNamespace(data={})))
    assert err.value.translation_key == "agent_command_failed"
    api.async_answer_doorbell_call.assert_not_awaited()
    if failure == "auth":
        entry.async_start_reauth.assert_called_once_with(hass)
        assert entry.runtime_data.connection_state.authentication_failed
    else:
        entry.async_start_reauth.assert_not_called()


@pytest.mark.parametrize("operation", ["answer_doorbell_call", "activate_doorbell_video"])
def test_failed_gain_write_is_logged_and_the_command_still_runs(monkeypatch, caplog, operation):
    hass, _entry, api = _setup(monkeypatch)
    api.async_set_doorstation_audio_gain_db.side_effect = C300XAgentApiConnectionError("offline")
    handler = getattr(services._C300XServiceHandlers(hass), f"async_{operation}")
    with caplog.at_level(logging.WARNING):
        asyncio.run(handler(SimpleNamespace(data={"audio": True})))
    api.async_set_doorstation_audio_gain_db.assert_awaited_once_with(6.0)
    command = getattr(api, f"async_{operation}")
    command.assert_awaited_once()
    assert "doorstation audio gain failed" in caplog.text


def test_failed_gain_write_and_failed_command_report_the_command_error(monkeypatch):
    hass, entry, api = _setup(monkeypatch)
    api.async_set_doorstation_audio_gain_db.side_effect = C300XAgentApiAuthError()
    api.async_activate_doorbell_video.side_effect = C300XAgentApiAuthError()
    handler = services._C300XServiceHandlers(hass).async_activate_doorbell_video
    with pytest.raises(HomeAssistantError) as err:
        asyncio.run(handler(SimpleNamespace(data={"audio": True})))
    assert err.value.translation_key == "agent_command_failed"
    entry.async_start_reauth.assert_called_once_with(hass)
