from __future__ import annotations

from datetime import UTC, datetime

from custom_components.bticino_c300x.media_timeline import C300XMediaTimeline


def test_media_timeline_keeps_bounded_safe_diagnostics() -> None:
    timeline = C300XMediaTimeline()

    for index in range(42):
        timeline.record(
            kind="webrtc",
            event=f"event_{index}",
            media_state="on_demand_active",
            owner="doorbell",
            session_count=index,
            ring_preview_sessions=0,
            ready_sessions=1,
            details={
                "provider": "go2rtc",
                "url": "rtsp://192.0.2.60:6554/doorbell",
                "candidate": "private-candidate",
                "long": "x" * 130,
                "wants_audio": True,
            },
            now=datetime(2026, 7, 5, 12, index % 60, tzinfo=UTC),
        )

    diagnostics = timeline.diagnostics()

    assert len(diagnostics) == 40
    assert diagnostics[0]["event"] == "event_2"
    assert diagnostics[-1]["event"] == "event_41"
    assert diagnostics[-1]["details"]["provider"] == "go2rtc"
    assert diagnostics[-1]["details"]["wants_audio"] is True
    assert diagnostics[-1]["details"]["long"].endswith("...")
    assert "url" not in diagnostics[-1]["details"]
    assert "candidate" not in diagnostics[-1]["details"]
