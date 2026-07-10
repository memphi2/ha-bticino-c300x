from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_display_bridge_alarm_notify_uses_thread_safe_scheduling() -> None:
    text = (
        ROOT / "custom_components" / "bticino_c300x" / "runtime_manager.py"
    ).read_text(encoding="utf-8")
    tracker_body = text.split(
        "def _async_track_display_bridge_updates",
        maxsplit=1,
    )[1].split(
        "def _async_schedule_display_bridge_notify",
        maxsplit=1,
    )[0]

    assert "@callback\n    def _handle_alarm_state_change" in tracker_body
    assert "@callback\n    def _handle_alarmo_event" in tracker_body
    assert "lambda _event: _async_schedule_display_bridge_notify" not in tracker_body
    assert (
        "hass.add_job(_async_notify_display_bridge_alarm_if_listening, entry, runtime_data)"
        in text
    )
    assert (
        "hass.async_create_task(_async_notify_display_bridge_alarm_if_listening(entry))"
        not in text
    )


def test_live_media_entities_do_not_use_ttl_state_callbacks() -> None:
    """Live media state must come from agent push events only."""

    for filename in ("webhook.py", "binary_sensor.py", "camera.py", "sensor.py"):
        text = (
            ROOT / "custom_components" / "bticino_c300x" / filename
        ).read_text(encoding="utf-8")
        assert "event_active_seconds" not in text
        assert "active_seconds" not in text
        assert "active_until" not in text
        assert "reset_video" not in text
        assert "SIGNAL_EVENT_STATE_CHANGED" not in text
        assert "_handle_event_state_changed" not in text
        assert "_mark_ha_video_window_active" not in text
        assert "_clear_ha_video_window" not in text
        assert '"talkback_requested"' not in text
        assert '"talkback_active"' not in text
        assert '"talkback_packets_sent"' not in text
        assert '"talkback_last_error"' not in text

    native_video = (
        ROOT / "native_agent" / "src" / "video_rtsp.c"
    ).read_text(encoding="utf-8")
    native_header = (
        ROOT / "native_agent" / "src" / "video_rtsp.h"
    ).read_text(encoding="utf-8")
    assert "external_active_until" not in native_video
    assert "external_active_until" not in native_header
    assert "external_media_guard_ttl_seconds" in native_video
    assert "external_event_expires_ms" in native_video
    assert "external_event_expires_ms" not in native_header
