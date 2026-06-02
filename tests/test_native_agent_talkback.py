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


def test_native_agent_video_stream_requires_sip_setup_before_av_media() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    start = media_bridge.index("static bool start_media_session")
    session_body = media_bridge[start : media_bridge.index("static void stop_media_session", start)]

    assert "sip_ready = send_sip_setup(bridge);" in session_body
    assert 'c300x_video_bridge_set_error(bridge->video, "sip_setup_failed");' in session_body
    assert 'return false;' in session_body[
        session_body.index('c300x_video_bridge_set_error(bridge->video, "sip_setup_failed");') :
        session_body.index("if (wants_audio && sip_ready && !start_talkback_proxy(bridge))")
    ]
    assert "if (wants_audio && sip_ready && !start_talkback_proxy(bridge))" in session_body
    assert session_body.index("sip_ready = send_sip_setup(bridge);") < session_body.index(
        "if (!start_bt_av_media(bridge))"
    )
    assert "c300x_video_bridge_media_started(bridge->video, wants_audio);" in session_body


def test_native_agent_starts_local_flexisip_only_for_media_sessions() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )

    assert '#define FLEXISIP_INIT_SCRIPT "/etc/init.d/flexisipsh"' in media_bridge
    assert 'execl(FLEXISIP_INIT_SCRIPT, "flexisipsh", action, bind_ip' in media_bridge
    assert "FLEXISIP_PASSPHRASE_FIFO" not in media_bridge
    assert "ensure_local_sip_proxy(bridge)" in media_bridge
    assert "bool sip_proxy_started_by_agent;" in media_bridge
    assert 'run_flexisip_script("start", "127.0.0.1")' in media_bridge
    assert 'bridge->sip_proxy_started_by_agent = true;' in media_bridge
    assert "stop_sip_proxy = g_bridge.sip_proxy_started_by_agent;" in media_bridge
    assert "g_bridge.sip_proxy_started_by_agent = false;" in media_bridge
    assert 'run_flexisip_script("start", bridge->config->video_sip_local_ip)' not in media_bridge
    assert media_bridge.count("for (int attempt = 0; attempt < 45; attempt++)") >= 2
    assert "for (int attempt = 0; attempt < 20; attempt++)" not in media_bridge
    assert "goto retry_sip_setup;" in media_bridge
    assert "video_sip_local_ip" not in media_bridge
    bridge_start_body = media_bridge[
        media_bridge.index("bool c300x_media_bridge_start") :
        media_bridge.index("void c300x_media_bridge_stop")
    ]
    describe_body = media_bridge[
        media_bridge.index('} else if (strcmp(method, "DESCRIBE") == 0)') :
        media_bridge.index('} else if (strcmp(method, "SETUP") == 0)')
    ]
    stop_body = media_bridge[
        media_bridge.index("static void stop_media_session") :
        media_bridge.index("void c300x_media_session_stop")
    ]
    assert "start_media_session_async(&g_bridge);" in describe_body
    assert "ensure_local_sip_proxy" not in bridge_start_body
    assert "run_flexisip_script" not in bridge_start_body
    assert 'run_flexisip_script("stop", NULL)' in stop_body

    video_rtsp = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    activate_body = video_rtsp[
        video_rtsp.index("int c300x_video_activate") :
        video_rtsp.index("void c300x_video_stop")
    ]
    assert "return c300x_media_session_warmup(video) ? 1 : 0;" in activate_body


def test_native_agent_av_media_uses_safe_resolution_default_and_fallback() -> None:
    config = (ROOT / "native_agent" / "src" / "config.c").read_text(encoding="utf-8")
    example = (ROOT / "native_agent" / "config.example.json").read_text(
        encoding="utf-8"
    )
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    start = media_bridge.index("static bool start_bt_av_media")
    body = media_bridge[start : media_bridge.index("static void send_bt_av_media_stop", start)]

    assert "config->video_av_high_resolution = 0;" in config
    assert '"highResolution": false' in example
    assert "for (int attempt = 0; attempt < 2 && !started; attempt++)" in body
    assert "attempt == 0 ? quality : (quality == 0 ? 1 : 0)" in body
    assert "started = send_bt_av_media_command(command, reply, sizeof(reply));" in body
