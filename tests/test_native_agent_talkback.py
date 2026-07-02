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
    assert "forward_ring_talkback_packet(bridge, packet, n)" in media_bridge
    assert "forward_home_call_talkback_packet(bridge, packet, n)" in media_bridge
    assert "forward_ondemand_talkback_packet(bridge, packet, n)" in media_bridge
    assert "RING_AUDIO_PAYLOAD_TYPE" in media_bridge
    assert "MEDIA_AUDIO_PAYLOAD_TYPE" in media_bridge[
        media_bridge.index("static bool forward_home_call_talkback_packet") :
        media_bridge.index("static void drain_ondemand_media_socket")
    ]
    assert "MEDIA_AUDIO_PAYLOAD_TYPE" in media_bridge[
        media_bridge.index("static bool forward_ondemand_talkback_packet") :
        media_bridge.index("static void drain_ondemand_media_socket")
    ]
    assert "protect_and_send_srtp(" in media_bridge[
        media_bridge.index("static bool forward_ring_talkback_packet") :
        media_bridge.index("static void drain_ondemand_media_socket")
    ]
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
    assert "int external_media_active;" in header
    assert "char media_owner[32];" in header
    assert "char last_block_reason[64];" in header
    assert "c300x_media_bridge_status(video, status);" in video


def test_native_agent_blocks_ha_video_when_external_media_is_active() -> None:
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    activate_body = video[
        video.index("int c300x_video_activate") :
        video.index("void c300x_video_stop")
    ]
    event_body = video[
        video.index("void c300x_video_note_event") :
        video.index("void c300x_video_note_event") + 1200
    ]
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "external_media_active_locked(video)" in activate_body
    assert "C300X_EXTERNAL_MEDIA_GUARD_MAX_SECONDS" in video
    assert "external_media_guard_ttl_seconds" in video
    assert "external_event_expires_ms" in video
    assert "now >= video->external_event_expires_ms" in video
    assert "(void)ttl_seconds;" not in event_body
    assert "external_active_until" not in video
    assert "video->media_starting = 1;" in video
    assert "video->media_starting = 0;" in video
    assert video.index("video->media_starting = 1;") < video.index(
        "c300x_media_bridge_start(video->config, video)"
    )
    assert "c300x_video_ensure_running(video)" in activate_body
    assert activate_body.index("external_media_active_locked(video)") < activate_body.index(
        "c300x_video_ensure_running(video)"
    )
    assert "c300x_media_external_session_active" not in video
    assert '"external_session_active"' in activate_body
    assert 'strcmp(event_type, "doorbell.pressed") == 0' in event_body
    assert 'strcmp(event_type, "doorbell.view_requested") == 0' in event_body
    pressed_block = event_body[
        event_body.index('strcmp(event_type, "doorbell.pressed") == 0') :
        event_body.index('strcmp(event_type, "doorbell.view_requested") == 0')
    ]
    view_block = event_body[
        event_body.index('strcmp(event_type, "doorbell.view_requested") == 0') :
        event_body.index('strcmp(event_type, "doorbell.media.closed") == 0')
    ]
    assert "ring_call_active = c300x_media_ring_call_active(video) ? 1 : 0;" in event_body
    assert "if (!video->call_active && !ring_call_active)" in event_body
    assert "set_external_media_active_locked" not in pressed_block
    assert 'set_external_media_active_locked(video, "external_media", ttl_seconds)' in view_block
    assert 'set_external_media_active_locked(video, "external_media", ttl_seconds)' in event_body
    assert 'clear_external_media_active_locked(video)' in event_body
    assert "c300x_video_note_event(runtime->video, event_type, ttl_seconds)" in http
    assert "if (update_video_state && runtime->video != NULL)" in http
    assert (
        "dispatch_event_internal(config, runtime, event_type, data_json, ttl_seconds, 0, 1)"
        in http
    )
    assert (
        "dispatch_event_internal(runtime->config, runtime, event_type, data_json, ttl_seconds, 0, 0)"
        in http
    )
    assert 'http_status = strcmp(error, "external_session_active") == 0 ? 409 : 503' in http
    assert 'strcmp(request->path, "/ui/media-closed") == 0' in http
    assert 'dispatch_event(config, runtime, "doorbell.media.closed", "{}", 0)' in http
    assert 'ui_event_notify(runtime, "media.closed")' in http


def test_native_agent_ignores_transient_on_demand_media_closed_during_start() -> None:
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    media_starting_body = video[
        video.index("void c300x_video_bridge_media_starting") :
        video.index("void c300x_video_bridge_media_started")
    ]
    media_started_body = video[
        video.index("void c300x_video_bridge_media_started") :
        video.index("void c300x_video_bridge_ring_media_started")
    ]
    media_stopped_body = video[
        video.index("void c300x_video_bridge_media_stopped") :
        video.index("void c300x_video_bridge_set_error")
    ]
    ignore_body = video[video.index("int c300x_video_ignore_transient_media_closed") :]
    transient_filter_body = http[
        http.index("static int doorbell_media_closed_is_ondemand_start_transition") :
        http.index("static void handle_udp_event")
    ]

    assert "#define C300X_ONDEMAND_START_MEDIA_CLOSED_GRACE_MS 3500" in video
    assert "long long media_closed_grace_until_ms;" in video
    assert "void c300x_video_bridge_media_starting" in header
    assert "int c300x_video_ignore_transient_media_closed" in header
    assert "c300x_video_bridge_media_starting(bridge->video);" in media_bridge
    assert "video->media_starting = 1;" in media_starting_body
    assert "video->media_closed_grace_until_ms =" in media_starting_body
    assert "clear_external_media_active_locked(video);" in media_starting_body
    assert "video->media_starting = 0;" in media_started_body
    assert "video->media_closed_grace_until_ms =" in media_started_body
    assert "video->media_closed_grace_until_ms = 0;" in media_stopped_body
    assert "video->clients > 0" in ignore_body
    assert "video->call_active || video->media_starting" in ignore_body
    assert "now < video->media_closed_grace_until_ms" in ignore_body
    assert 'strncmp(msg, "*8*3#1#4*"' in transient_filter_body
    assert 'strncmp(msg, "*8*3#5#4*"' in transient_filter_body
    assert (
        "c300x_video_ignore_transient_media_closed(runtime->video)"
        in transient_filter_body
    )


def test_native_agent_reports_media_ownership_and_external_block_state() -> None:
    header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    assert "external_active_until" not in header
    assert "external_active_until" not in video
    assert "unsigned long long bt_media_start_attempts;" in header
    assert "unsigned long long bt_media_stop_attempts;" in header
    assert 'snprintf(status->media_owner, sizeof(status->media_owner), "%s", "agent")' in video
    assert 'snprintf(status->media_owner, sizeof(status->media_owner), "%s", "idle")' in video
    assert '\\"media_owner\\":%s' in http
    assert '\\"external_media_active\\":%s' in http
    assert '\\"external_active_until\\":%s' not in http
    assert '\\"last_block_reason\\":%s' in http
    assert '\\"bt_media_start_attempts\\":%llu' in http
    assert '\\"bt_media_stop_attempts\\":%llu' in http


def test_native_agent_external_detection_is_event_state_based() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )

    assert "/proc/net/tcp" not in media_bridge
    assert "/proc/net/udp" not in media_bridge
    assert "c300x_media_external_session_active" not in media_bridge
    external_active_body = video[
        video.index("static int external_media_active_locked") :
        video.index("static void set_external_media_active_locked")
    ]
    set_external_body = video[
        video.index("static void set_external_media_active_locked") :
        video.index("static void clear_external_media_active_locked")
    ]
    assert "time(NULL)" not in external_active_body
    assert "time(NULL)" not in set_external_body


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
    register_body = media_bridge[
        media_bridge.index("static bool register_rtsp_client_locked") :
        media_bridge.index("static rtsp_client_slot_t *rtsp_client_slot_locked")
    ]
    client_body = media_bridge[
        media_bridge.index("static void handle_rtsp_client") :
        media_bridge.index("static int create_rtsp_listener")
    ]

    assert "active_clients > 0 && !rtsp_client_sharing_allowed_locked(bridge)" in register_body
    assert "active_clients >= C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS" in register_body
    assert "bool accepted = register_rtsp_client_locked(&g_bridge, fd, &slot_index);" in client_body
    assert "send_rtsp_response(fd, 453" in client_body
    assert client_body.index("if (!accepted)") < client_body.index(
        "c300x_video_bridge_client_connected"
    )
    assert "bool shared_client = rtsp_client_count_locked(&g_bridge) > 1;" in client_body
    assert "ring_preview_sharing_allowed_locked(&g_bridge)" in client_body
    assert "ring_answer_stream_sharing_allowed_locked(&g_bridge)" in client_body
    assert "&& preview_path" in client_body
    assert "&& !wants_audio" in client_body
    assert "&& wants_audio" in client_body
    assert "&& !preview_path" in client_body
    assert "shutdown_ring_preview_clients_except_locked(&g_bridge, slot_index)" in client_body
    assert "if (!allow_shared_path)" in client_body


def test_native_agent_rtsp_listener_lifecycle_closes_stale_fds() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    thread_body = media_bridge[
        media_bridge.index("static void *rtsp_server_thread") :
        media_bridge.index("bool c300x_media_bridge_start")
    ]
    start_body = media_bridge[
        media_bridge.index("bool c300x_media_bridge_start") :
        media_bridge.index("void c300x_media_bridge_stop")
    ]
    stop_body = media_bridge[
        media_bridge.index("void c300x_media_bridge_stop") :
    ]

    assert "static void close_fd_if_open(int *fd)" in media_bridge
    assert start_body.index("close_fd_if_open(&g_bridge.listen_fd);") < start_body.index(
        "g_bridge.listen_fd = -1;"
    )
    assert start_body.index("close_all_rtsp_clients_locked(&g_bridge);") < start_body.index(
        "g_bridge.config = config;"
    )
    assert "bool should_close = true;" in thread_body
    assert "if (bridge->listen_fd == server_fd)" in thread_body
    assert "if (should_close)" in thread_body
    assert stop_body.index("g_bridge.listen_fd = -1;") < stop_body.index(
        "pthread_mutex_unlock(&g_bridge.mutex);"
    )
    assert stop_body.index("shutdown_all_rtsp_clients_locked(&g_bridge);") < stop_body.index(
        "pthread_mutex_unlock(&g_bridge.mutex);"
    )
    assert "while (g_bridge.rtsp_client_threads > 0)" in stop_body
    assert "pthread_cond_wait(&g_bridge.ready_cond, &g_bridge.mutex);" in stop_body


def test_native_agent_sip_uses_media_identity_from_local_flexisip() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    device_user = (ROOT / "native_agent" / "src" / "device_user.c").read_text(
        encoding="utf-8"
    )
    setup_body = media_bridge[
        media_bridge.index("static bool send_sip_setup") :
        media_bridge.index("static bool send_bt_av_media_command")
    ]

    assert 'FLEXISIP_USERS_FILE "/etc/flexisip/users/users.db.txt"' in device_user
    assert "media_identity_from_flexisip(" in setup_body
    assert "c300x_device_user_media_identity(domain_hint" in media_bridge
    assert "sip_local_endpoint_from_config(bridge->config" in setup_body
    assert "connect_sip_socket(bridge->config)" in setup_body
    assert '"Via: SIP/2.0/%s %s:%u' in setup_body
    assert '"s=Talk\\r\\n"' in setup_body
    assert '"m=audio %d RTP/SAVP 96 97 98 0 8 101 99 100\\r\\n"' in setup_body
    assert '"m=video %d RTP/SAVP 96 97 98 99\\r\\n"' in setup_body
    assert '"a=nortpproxy:yes\\r\\n"' in setup_body
    assert '"User-Agent: " MEDIA_SIP_USER_AGENT "\\r\\n"' in setup_body
    assert '"Contact: <sip:%s;transport=%s>' in setup_body
    assert "MEDIA_AUDIO_RTP_PORT 26986" in media_bridge
    assert "MEDIA_AUDIO_RTCP_PORT 26987" in media_bridge
    assert "MEDIA_VIDEO_RTP_PORT 28772" in media_bridge
    assert "MEDIA_VIDEO_RTCP_PORT 28773" in media_bridge
    assert "generate_sdes_key(audio_key_raw" in setup_body
    assert "memcpy(bridge->ondemand_audio_srtp_key, audio_key_raw" in setup_body
    assert "start_bt_av_media(bridge)" in media_bridge
    assert "MEDIA_RENEW_SECONDS" in media_bridge
    assert '"sip:webrtc@' not in media_bridge
    assert "dummykey" not in media_bridge
    assert '"sip:c300x@127.0.0.1"' not in media_bridge


def test_native_agent_device_user_uses_arm_stat64_syscalls() -> None:
    device_user = (ROOT / "native_agent" / "src" / "device_user.c").read_text(
        encoding="utf-8"
    )

    assert "SYS_stat64" in device_user
    assert "SYS_lstat64" in device_user
    assert "device_user_stat_path(path, &st)" in device_user
    assert "device_user_lstat_path(FLEXISIP_ROUTE_ACTIVE_FILE, &lst)" in device_user


def test_native_agent_app_stream_uses_authenticated_reverse_media() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    ondemand_media_body = media_bridge[
        media_bridge.index("static void *ondemand_media_thread") :
        media_bridge.index("static bool send_sip_setup")
    ]
    send_sip_setup_body = media_bridge[
        media_bridge.index("static bool send_sip_setup") :
        media_bridge.index("static bool send_bt_av_media_command")
    ]

    assert 'dlopen("libsrtp.so.1", RTLD_NOW | RTLD_LOCAL)' in media_bridge
    assert 'srtp_load_symbol(handle, "srtp_protect"' in media_bridge
    assert '"srtp_protect_rtcp"' in media_bridge
    assert '"srtp_unprotect"' in media_bridge
    assert '"srtp_unprotect_rtcp"' in media_bridge
    assert '"crypto_policy_set_rtp_default"' in media_bridge
    assert '"crypto_policy_set_rtcp_default"' in media_bridge
    assert "crypto_policy_set_aes_cm_128_hmac_sha1_80" not in media_bridge
    assert "policy.ssrc.type = 3" in media_bridge
    assert "MEDIA_AUDIO_PACKET_MS 20" in media_bridge
    assert "MEDIA_AUDIO_PAYLOAD_TYPE 98" in media_bridge
    assert "#define MEDIA_TALKBACK_SILENCE_GRACE_MS (MEDIA_AUDIO_PACKET_MS * 2)" in media_bridge
    assert 'parse_sdp_sdes_key(response, "\\r\\nm=audio ", answer_audio_key_raw' in send_sip_setup_body
    assert 'parse_sdp_sdes_key(response, "\\r\\nm=video ", answer_video_key_raw' in send_sip_setup_body
    assert "bridge->ondemand_audio_srtp_in_key" in send_sip_setup_body
    assert "bridge->ondemand_video_srtp_in_key" in send_sip_setup_body
    assert "media_srtp_init_inbound(&srtp, audio_in_key, video_in_key)" in ondemand_media_body
    assert "bridge->ondemand_srtp_state = &srtp;" in ondemand_media_body
    assert 'c300x_video_bridge_set_error(bridge->video, "ondemand_media_no_fds")' in ondemand_media_body
    assert ondemand_media_body.index("if (max_fd < 0)") < ondemand_media_body.index(
        "select(max_fd + 1"
    )
    assert "send_media_audio_silence(audio_rtp_fd, target_audio_port, &srtp)" in ondemand_media_body
    assert "drain_ondemand_media_socket(bridge, audio_rtp_fd, srtp.audio_in, false, true, NULL)" in ondemand_media_body
    assert "drain_ondemand_media_socket(bridge, audio_rtcp_fd, srtp.audio_in, true, true, NULL)" in ondemand_media_body
    assert "drain_ondemand_media_socket(bridge, video_rtp_fd, srtp.video_in, false, false, &video_ssrc)" in ondemand_media_body
    assert "ondemand_talkback_recent_locked(bridge, now)" in ondemand_media_body
    assert "forward_ondemand_talkback_packet" in media_bridge
    assert "bridge->ondemand_target_audio_port" in media_bridge[
        media_bridge.index("static bool forward_ondemand_talkback_packet") :
        media_bridge.index("static void drain_ondemand_media_socket")
    ]
    assert "bridge->ondemand_last_talkback_ms = monotonic_ms();" in media_bridge[
        media_bridge.index("static bool forward_ondemand_talkback_packet") :
        media_bridge.index("static void drain_ondemand_media_socket")
    ]
    assert "send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1, srtp.audio" in ondemand_media_body
    assert "send_srtcp_receiver_report(video_rtcp_fd, target_video_port + 1, srtp.video" in ondemand_media_body
    assert "send_srtcp_pli(video_rtcp_fd, target_video_port + 1, srtp.video" in ondemand_media_body
    assert "send_rtcp_receiver_report(" not in media_bridge
    assert "send_rtcp_pli(" not in media_bridge
