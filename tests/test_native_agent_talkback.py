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
    assert "int bridge_open_fds;" in header
    assert "int bridge_active_threads;" in header
    assert "c300x_media_bridge_status(video, status);" in video


def test_native_agent_rtsp_response_does_not_send_truncated_stack_buffer() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    response_body = media_bridge[
        media_bridge.index("static void send_rtsp_response") :
        media_bridge.index("static void handle_rtsp_client")
    ]

    assert "int n = snprintf(" in response_body
    assert "n > 0 && n < (int)sizeof(response)" in response_body
    assert "send_all(fd, response, (size_t)n)" in response_body


def test_native_agent_rtsp_rejects_parallel_sessions_before_overwriting_state() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    client_body = media_bridge[
        media_bridge.index("static void handle_rtsp_client") :
        media_bridge.index("static int create_rtsp_listener")
    ]

    assert "busy = g_bridge.client_fd >= 0 && g_bridge.client_fd != fd;" in client_body
    assert "send_rtsp_response(fd, 453" in client_body
    assert client_body.index("if (!busy)") < client_body.index("g_bridge.client_fd = fd;")
    assert client_body.index("if (busy)") < client_body.index(
        "c300x_video_bridge_client_connected"
    )


def test_native_agent_sip_uses_configured_flexisip_endpoint_and_identities() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    setup_body = media_bridge[
        media_bridge.index("static bool send_sip_setup") :
        media_bridge.index("static bool send_bt_av_media_command")
    ]

    assert "sip_domain_from_config(bridge->config" in setup_body
    assert "bridge->config->video_sip_from" in setup_body
    assert "bridge->config->video_sip_to" in setup_body
    assert "sip_local_endpoint_from_config(bridge->config" in setup_body
    assert "connect_sip_socket(bridge->config)" in setup_body
    assert '"Via: SIP/2.0/%s %s:%u' in setup_body
    assert '"Contact: <sip:%s@%s;transport=%s>' in setup_body
    assert '"sip:webrtc@' not in media_bridge
    assert '"sip:c300x@127.0.0.1"' not in media_bridge
