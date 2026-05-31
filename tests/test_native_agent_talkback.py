from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_agent_talkback_matches_c300x_speex_backchannel() -> None:
    header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "#define C300X_TALKBACK_RTP_PORT 40004" in header
    assert "#define C300X_TALKBACK_RTP_PAYLOAD_TYPE 97" in header
    assert '#define C300X_TALKBACK_CODEC "speex/8000"' in header
    assert "bind_udp_port(C300X_TALKBACK_RTP_PORT)" in media_bridge
    assert "TALKBACK_TARGET_PORT 4000" in media_bridge
    assert 'inet_pton(AF_INET, "127.0.0.1", &target.sin_addr)' in media_bridge
    assert '\\"talkback_supported\\":true' in http
    assert '\\"talkback_running\\":%s' in http
    assert '\\"talkback_payload_type\\":%d' in http


def test_native_agent_status_reports_talkback_runtime_state() -> None:
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )

    assert "int stream_audio;" in header
    assert "int talkback_running;" in header
    assert "status->stream_audio = video->stream_audio;" in video
    assert "int talkback_running = c300x_media_talkback_running(video)" in video
    assert "status->talkback_running = talkback_running;" in video
