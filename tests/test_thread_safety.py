from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_display_bridge_alarm_notify_uses_thread_safe_scheduling() -> None:
    text = (
        ROOT / "custom_components" / "bticino_c300x" / "__init__.py"
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
    assert "hass.add_job(_async_notify_display_bridge_alarm, entry)" in text
    assert (
        "hass.async_create_task(_async_notify_display_bridge_alarm(entry))"
        not in text
    )
