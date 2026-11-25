"""A C100X is not offered a device-firmware codec switch."""

import asyncio
from pathlib import Path

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
ROOT = Path(__file__).resolve().parents[1]


def _assert_translated_refusal(error, model):
    """The refusal is a translated message of the integration, with the entry's model."""

    assert error.translation_domain == "bticino_c300x"
    assert error.translation_key == "maintenance_action_not_supported"
    assert error.translation_placeholders["model"] == model
    source = (ROOT / "custom_components/bticino_c300x/select.py").read_text(encoding="utf-8")
    assert "test build" not in source and "test scope" not in source


@pytest.mark.parametrize("option", ["pcmu", "speex"])
def test_existing_c100_select_cannot_bypass_native_recovery_policy(option):
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)
    assert entity.available
    entry.runtime_data.agent_info = {"model": "C100X"}
    asyncio.run(entity.async_update())  # Read-only codec status still works.
    assert entity.current_option == "speex"
    assert not entity.available
    with pytest.raises(HomeAssistantError) as refused:
        asyncio.run(entity.async_select_option(option))
    _assert_translated_refusal(refused.value, "C100X")
    assert entry.runtime_data.api.audio_codec_calls == []


def test_existing_select_obeys_updated_capability():
    entry = _audio_codec_entry()
    entity = C300XAudioCodecSelect(entry)
    entry.runtime_data.capabilities["maintenance"]["audio_codec_apply"] = False
    assert not entity.available
    with pytest.raises(HomeAssistantError) as refused:
        asyncio.run(entity.async_select_option("pcmu"))
    _assert_translated_refusal(refused.value, "C300X")
    assert entry.runtime_data.api.audio_codec_calls == []
