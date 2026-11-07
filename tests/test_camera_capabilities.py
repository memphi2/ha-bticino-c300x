"""Native camera microphone capability without device I/O or older-HA regressions."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from homeassistant.components import camera as camera_platform

from custom_components.bticino_c300x import camera as camera_module
from custom_components.bticino_c300x.camera_media import ha_compat
from custom_components.bticino_c300x.const import CONF_NATIVE_TWO_WAY_AUDIO


@dataclass(frozen=True, kw_only=True)
class _Capabilities:
    two_way_audio: bool = False


@pytest.fixture
def camera(monkeypatch):
    entry = SimpleNamespace(
        entry_id="entry-1", title="C300X", data={}, options={},
        runtime_data=SimpleNamespace(),
    )
    monkeypatch.setattr(camera_module, "publish_agent_media_facts", lambda *_: None)
    return camera_module.C300XDoorbellCamera(entry)


@pytest.mark.parametrize("supported", [True, False, None, 0, 1, "true", "false"])
@pytest.mark.parametrize("audio_path", ["/doorbell", None, ""])
def test_native_microphone_requires_confirmed_support_and_audio_path(
    camera, monkeypatch, supported, audio_path,
):
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = True
    factory = ha_compat.CameraEntityCapabilities or _Capabilities
    monkeypatch.setattr(camera_module, "CameraEntityCapabilities", factory)
    camera._apply_status({
        "audio_stream_path": audio_path,
        "bridge": {"talkback_supported": supported},
    })
    assert camera._attr_camera_entity_capabilities.two_way_audio is (
        supported is True and bool(audio_path)
    )


def test_native_microphone_does_not_infer_support_from_codec_or_stream(camera, monkeypatch):
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = True
    factory = ha_compat.CameraEntityCapabilities or _Capabilities
    monkeypatch.setattr(camera_module, "CameraEntityCapabilities", factory)
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"audio_codec": "speex/8000"},
    })
    assert camera.extra_state_attributes["talkback_supported"] is True
    assert camera._attr_camera_entity_capabilities.two_way_audio is False


def test_old_ha_does_not_receive_the_new_capability(camera, monkeypatch):
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = True
    monkeypatch.setattr(camera_module, "CameraEntityCapabilities", None)
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": True},
    })
    assert "_attr_camera_entity_capabilities" not in camera.__dict__


def test_capability_import_matches_the_installed_ha():
    assert ha_compat.CameraEntityCapabilities is getattr(
        camera_platform, "CameraEntityCapabilities", None,
    )


@pytest.mark.parametrize("data,options,expected", [
    ({}, {}, False),
    ({CONF_NATIVE_TWO_WAY_AUDIO: True}, {}, True),
    ({CONF_NATIVE_TWO_WAY_AUDIO: True}, {CONF_NATIVE_TWO_WAY_AUDIO: False}, False),
    ({CONF_NATIVE_TWO_WAY_AUDIO: False}, {CONF_NATIVE_TWO_WAY_AUDIO: True}, True),
    ({}, {CONF_NATIVE_TWO_WAY_AUDIO: "false"}, False),
])
def test_native_microphone_is_opt_in_without_disabling_card_talkback(
    camera, monkeypatch, data, options, expected,
):
    camera._entry.data = data
    camera._entry.options = options
    factory = ha_compat.CameraEntityCapabilities or _Capabilities
    monkeypatch.setattr(camera_module, "CameraEntityCapabilities", factory)
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": True},
    })
    assert camera._attr_camera_entity_capabilities.two_way_audio is expected
    assert camera.extra_state_attributes["talkback_supported"] is True


@pytest.mark.skipif(
    ha_compat.CameraEntityCapabilities is None,
    reason="Native camera capabilities require HA 2026.11",
)
def test_real_ha_capability_cache_and_labs_gate(camera, monkeypatch):
    from homeassistant.components.camera import entity as camera_entity

    labs_enabled = False
    monkeypatch.setattr(
        camera_entity, "async_is_preview_feature_enabled",
        lambda *_: labs_enabled,
    )
    camera.hass = SimpleNamespace()
    assert camera.camera_entity_capabilities.two_way_audio is False
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = True
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": True},
    })
    assert isinstance(
        camera.camera_entity_capabilities, ha_compat.CameraEntityCapabilities,
    )
    assert camera.camera_entity_capabilities.two_way_audio is True
    assert camera.camera_capabilities.two_way_audio is False
    labs_enabled = True
    assert camera.camera_capabilities.two_way_audio is True
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = False
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": True},
    })
    assert camera.camera_entity_capabilities.two_way_audio is False
    assert camera.camera_capabilities.two_way_audio is False
    camera._entry.options[CONF_NATIVE_TWO_WAY_AUDIO] = True
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": True},
    })
    assert camera.camera_capabilities.two_way_audio is True
    assert camera.camera_capabilities.frontend_stream_types == {"web_rtc"}
    camera._supports_native_async_webrtc = False
    assert camera.camera_capabilities.frontend_stream_types == {"hls"}
    assert camera.camera_capabilities.two_way_audio is False
    camera._supports_native_async_webrtc = True
    camera._attr_supported_features = ha_compat.CameraEntityFeature(0)
    assert camera.camera_capabilities.two_way_audio is False
    camera._attr_supported_features = ha_compat.CameraEntityFeature.STREAM
    camera._apply_status({
        "audio_stream_path": "/doorbell",
        "bridge": {"talkback_supported": False},
    })
    assert camera.camera_entity_capabilities.two_way_audio is False
    assert camera.camera_capabilities.two_way_audio is False
