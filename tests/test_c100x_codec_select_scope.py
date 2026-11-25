"""The first C100X package does not offer a device-firmware codec switch."""

import asyncio

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_select import _audio_codec_entry

from custom_components.bticino_c300x.select import (
    C300XAudioCodecSelect,
    async_setup_entry,
)


@pytest.mark.parametrize(
    "model,advertised", [("C100X", True), ("C100X", False), ("C300X", False)]
)
def test_scope_blocked_codec_select_is_not_created(model, advertised):
    entry = _audio_codec_entry()
    entry.runtime_data.agent_info = {"model": model}
    entry.runtime_data.capabilities["maintenance"]["audio_codec_apply"] = advertised
    added = []
    asyncio.run(async_setup_entry("hass", entry, added.append))
    assert added == []
    assert entry.runtime_data.api.audio_codec_calls == []


@pytest.mark.parametrize("option", ["pcmu", "speex"])
def test_existing_c100_select_cannot_bypass_native_recovery_policy(option):
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)
    assert entity.available
    entry.runtime_data.agent_info = {"model": "C100X"}
    asyncio.run(entity.async_update())  # Read-only codec status still works.
    assert entity.current_option == "speex"
    assert not entity.available
    with pytest.raises(HomeAssistantError, match="test build"):
        asyncio.run(entity.async_select_option(option))
    assert entry.runtime_data.api.audio_codec_calls == []


def test_existing_select_obeys_updated_capability():
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)
    entry.runtime_data.capabilities["maintenance"]["audio_codec_apply"] = False
    assert not entity.available
    with pytest.raises(HomeAssistantError, match="test build"):
        asyncio.run(entity.async_select_option("pcmu"))
    assert entry.runtime_data.api.audio_codec_calls == []
