from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_media_bridge() -> str:
    return (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )


def test_native_agent_ring_receiver_matches_captured_sip_media_flow() -> None:
    media_bridge = _read_media_bridge()
    ring_invite_body = media_bridge[
        media_bridge.index("static void handle_ring_invite") :
        media_bridge.index("static bool ring_sleep_seconds")
    ]
    ring_thread_body = media_bridge[
        media_bridge.index("static void *ring_receiver_thread") :
        media_bridge.index("static void *sip_monitor_thread")
    ]
    ring_media_loop_body = media_bridge[
        media_bridge.index("static void ring_media_loop") :
        media_bridge.index("static void handle_ring_invite")
    ]

    assert "#define RING_AUDIO_RTP_PORT 17030" in media_bridge
    assert "#define RING_AUDIO_RTCP_PORT 17031" in media_bridge
    assert "#define RING_VIDEO_RTP_PORT 16718" in media_bridge
    assert "#define RING_VIDEO_RTCP_PORT 16719" in media_bridge
    assert "#define RING_AUDIO_PAYLOAD_TYPE 96" in media_bridge
    assert "#define RING_TALKBACK_SILENCE_GRACE_MS (APP_AUDIO_PACKET_MS * 2)" in media_bridge
    assert "#define RING_UNANSWERED_MEDIA_IDLE_TIMEOUT_MS 300000" in media_bridge
    assert "#define RING_ANSWERED_MEDIA_IDLE_TIMEOUT_MS 30000" in media_bridge
    assert "#define RTSP_AUDIO_PAYLOAD_TYPE 110" in media_bridge
    assert "strstr(message, \"sip:alluser@\")" in ring_thread_body
    assert ring_invite_body.index('100, "Trying"') < ring_invite_body.index(
        '180, "Ringing"'
    )
    assert ring_invite_body.index('180, "Ringing"') < ring_invite_body.index(
        '183, "Session progress"'
    )
    assert ring_invite_body.index('183, "Session progress"') < ring_invite_body.index(
        "ring_media_loop("
    )
    assert ring_invite_body.index("bridge->ring_call_active = true;") < (
        ring_invite_body.index('100, "Trying"')
    )
    assert ring_invite_body.index("bridge->ring_media_active = false;") < (
        ring_invite_body.index('183, "Session progress"')
    )
    assert ring_invite_body.index('183, "Session progress"') < (
        ring_invite_body.index("bridge->ring_media_active = true;")
    )
    assert "build_ring_sdp(sdp_early" in ring_invite_body
    assert "build_ring_sdp(sdp_answer" in ring_invite_body
    assert "bridge->ring_srtp_state = srtp_ready ? &srtp : NULL;" in ring_invite_body
    assert "start_talkback_proxy(bridge)" in ring_invite_body
    assert '"m=audio %d RTP/SAVP 96 101\\r\\n"' in media_bridge
    assert '"a=rtpmap:96 speex/8000\\r\\n"' in media_bridge
    assert '"a=inactive\\r\\n"' in media_bridge
    assert '"m=video %d RTP/SAVP 96\\r\\n"' in media_bridge
    assert '"a=recvonly\\r\\n"' in media_bridge
    assert "parse_sdp_sdes_key(invite, \"\\r\\nm=audio \"" in ring_invite_body
    assert "parse_sdp_sdes_key(invite, \"\\r\\nm=video \"" in ring_invite_body
    assert "app_srtp_init_inbound(&srtp" in ring_invite_body
    assert "srtp_unprotect" in media_bridge
    assert "forward_rtsp_packet(bridge, packet, packet_len, audio)" in media_bridge
    assert (
        "packet[1] = (unsigned char)((packet[1] & 0x80) | RTSP_AUDIO_PAYLOAD_TYPE);"
        in media_bridge
    )
    assert "if (answer_requested && !answered)" in ring_media_loop_body
    assert 'send_ring_response(bridge, sip_fd, invite, 200, "Ok"' in ring_media_loop_body
    assert "bridge->ring_audio_active = true;" in ring_media_loop_body
    assert "c300x_video_bridge_ring_media_started(bridge->video, 1)" in ring_media_loop_body
    assert "long long last_inbound_activity = started_at;" in ring_media_loop_body
    assert ring_media_loop_body.count("last_inbound_activity = monotonic_ms();") >= 5
    assert "RING_ANSWERED_MEDIA_IDLE_TIMEOUT_MS" in ring_media_loop_body
    assert "RING_UNANSWERED_MEDIA_IDLE_TIMEOUT_MS" in ring_media_loop_body
    assert ring_media_loop_body.index("now - last_inbound_activity") < (
        ring_media_loop_body.index("if (now >= next_sip_keepalive)")
    )
    assert "send_app_audio_silence_payload_type(" in ring_media_loop_body
    assert (
        "bridge->ring_srtp_state == srtp && !ring_talkback_recent_locked(bridge, now)"
        in ring_media_loop_body
    )
    assert "RING_AUDIO_PAYLOAD_TYPE" in ring_media_loop_body
    assert "bridge->ring_last_talkback_ms = 0;" in ring_invite_body
    assert "bridge->ring_last_talkback_ms = monotonic_ms();" in media_bridge[
        media_bridge.index("static bool forward_ring_talkback_packet") :
        media_bridge.index("static void drain_app_media_socket")
    ]


def test_native_agent_ring_mode_is_separate_from_on_demand_streaming() -> None:
    media_bridge = _read_media_bridge()
    setup_body = media_bridge[
        media_bridge.index("static bool send_sip_setup") :
        media_bridge.index("static bool send_bt_av_media_command")
    ]
    start_pos = media_bridge.index(
        "static bool start_media_session(media_bridge_t *bridge) {"
    )
    start_body = media_bridge[
        start_pos : media_bridge.index("static void stop_media_session", start_pos)
    ]
    rtsp_body = media_bridge[
        media_bridge.index("static void handle_rtsp_client") :
        media_bridge.index("static int create_rtsp_listener")
    ]

    assert "RING_APP_INSTANCE_UUID" not in media_bridge
    assert re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        media_bridge,
    ) is None
    assert '"ha-bticino-c300x:sip-instance:"' in media_bridge
    assert "c300x_sha256_strings3(APP_INSTANCE_UUID_NAMESPACE, mode, seed, digest)" in media_bridge
    assert 'bridge_instance_uuid(bridge, bridge->app_instance_uuid, "ondemand"' in media_bridge
    assert 'bridge_instance_uuid(bridge, bridge->ring_app_instance_uuid, "ring"' in media_bridge
    assert 'bridge_instance_uuid(bridge, bridge->home_call_app_instance_uuid, "home_call"' in media_bridge
    assert "ring_forwarding_allows_registration" not in setup_body
    assert "ring_forwarding_allows_registration" not in start_body
    assert "bridge_instance_uuid(bridge, bridge->app_instance_uuid" in setup_body
    assert '"m=audio %d RTP/SAVP 96 97 98 0 8 101 99 100\\r\\n"' in setup_body
    assert '"m=video %d RTP/SAVP 96 97 98 99\\r\\n"' in setup_body
    assert '"a=rtpmap:96 AV1/90000\\r\\n"' in setup_body
    assert "start_bt_av_media(bridge)" in media_bridge
    assert "request_ring_answer_if_active" not in start_body
    assert "sdp_audio_video" in rtsp_body
    assert "sdp_ring_audio_video" in rtsp_body
    assert "sdp_home_call_audio" in rtsp_body
    assert '"m=audio 0 RTP/AVP 110\\r\\n"' in rtsp_body
    assert '"a=fmtp:110 vbr=on\\r\\n"' in rtsp_body
    assert rtsp_body.count('"a=fmtp:96 profile-level-id=42801F\\r\\n"') >= 3
    assert rtsp_body.count('"a=rtcp-fb:* trr-int 5000\\r\\n"') >= 3
    assert rtsp_body.count('"a=rtcp-fb:* ccm tmmbr\\r\\n"') >= 3
    assert rtsp_body.count('"a=rtcp-fb:96 nack pli\\r\\n"') >= 3
    assert rtsp_body.count('"a=rtcp-fb:96 ccm fir\\r\\n"') >= 3
    assert '"m=audio 0 RTP/AVP 96\\r\\n"' not in rtsp_body
    assert "bool home_call_audio = home_call_active_locked(&g_bridge);" in rtsp_body
    assert "sdp = home_call_audio" in rtsp_body
    assert "request_home_call_media_if_active" in rtsp_body
    assert "!ring_session && !home_call_session && !start_media_session" in rtsp_body
    assert "return bridge->ring_call_active && !bridge->ring_call_stop;" in media_bridge
    assert "return (bridge->home_call_started || bridge->home_call_active) && !bridge->home_call_stop;" in media_bridge
    assert "ring_session_active(&g_bridge)" in rtsp_body
    assert "request_ring_answer_if_active(&g_bridge, g_bridge.rtsp_audio_enabled)" not in rtsp_body
    answer_request_body = media_bridge[
        media_bridge.index("static bool request_ring_answer_if_active") :
        media_bridge.index("static bool stop_ring_call_if_active")
    ]
    assert "active = ring_call_active_locked(bridge);" in answer_request_body
    assert "active && !bridge->ring_answered" in answer_request_body
    assert "bridge->ring_answer_requested = true;" in media_bridge
    assert rtsp_body.index("request_home_call_media_if_active") < rtsp_body.index(
        "ring_session_active"
    )
    assert rtsp_body.index("ring_session_active") < rtsp_body.index(
        "if (!ring_session && !home_call_session && !start_media_session(&g_bridge))"
    )
    assert (
        "if (!ring_session && !home_call_session && !start_media_session(&g_bridge))"
        in rtsp_body
    )
    assert "media_started = !ring_session && !home_call_session" in rtsp_body


def test_native_agent_ring_receiver_follows_smartphone_forwarding_state() -> None:
    media_bridge = _read_media_bridge()
    media_bridge_header = (ROOT / "native_agent" / "src" / "media_bridge.h").read_text(
        encoding="utf-8"
    )
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    video_header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    ring_thread_body = media_bridge[
        media_bridge.index("static void *ring_receiver_thread") :
        media_bridge.index("static void *sip_monitor_thread")
    ]

    assert "RING_FORWARDING_CHECK_SECONDS" not in media_bridge
    assert 'c300x_openwebnet_send(config, "*#8**37##"' not in media_bridge
    assert "next_forwarding_check" not in media_bridge
    assert "ring_forwarding_known" not in media_bridge
    assert "ring_forwarding_enabled" not in media_bridge
    assert "ring_wait_for_forwarding_enabled" not in media_bridge
    assert "c300x_media_ring_forwarding_update" not in media_bridge
    assert "c300x_media_ring_forwarding_update" not in media_bridge_header
    assert "c300x_video_set_ring_forwarding_enabled" not in video_header
    assert "c300x_video_set_ring_forwarding_enabled" not in video
    assert "void c300x_video_set_ring_receiver_enabled" in video_header
    assert "c300x_video_set_ring_receiver_enabled(" in video
    assert "static void sync_ring_receiver_for_forwarding" in http
    assert "runtime->smartphone_forwarding_mode_code == 0" in http
    assert "c300x_video_set_ring_receiver_enabled(" in http
    assert "remember_smartphone_forwarding_mode(runtime, code)" in http
    assert "refresh_smartphone_forwarding_mode(config, runtime)" in http
    assert "int changed = note_smartphone_forwarding_changed(runtime, code);" in http
    assert "sync_ring_receiver_for_forwarding(runtime);" in http
    assert (
        "send_ring_registration(bridge, fd, domain, from_aor, cseq, 0)"
        in media_bridge
    )
    assert "send_ring_unregister(bridge, fd, domain, from_aor, register_cseq++)" in (
        ring_thread_body
    )


def test_native_agent_home_call_tracks_flexisip_rtp_proxy_without_video_mode() -> None:
    media_bridge = _read_media_bridge()
    home_call_body = media_bridge[
        media_bridge.index("static bool build_home_call_sdp") :
        media_bridge.index("static void *rtp_relay_thread")
    ]
    home_call_thread = media_bridge[
        media_bridge.index("static void *home_call_thread_func") :
        media_bridge.index("static void *rtp_relay_thread")
    ]
    home_call_talkback_body = media_bridge[
        media_bridge.index("static bool forward_home_call_talkback_packet") :
        media_bridge.index("static void drain_app_media_socket")
    ]
    drain_home_call_body = media_bridge[
        media_bridge.index("static void drain_home_call_srtp_socket") :
        media_bridge.index("static void dispatch_home_call_state_event")
    ]
    rtsp_body = media_bridge[
        media_bridge.index("static void handle_rtsp_client") :
        media_bridge.index("static int create_rtsp_listener")
    ]
    rtsp_home_call_sdp = rtsp_body[
        rtsp_body.index("const char *sdp_home_call_audio") :
        rtsp_body.index("const char *sdp_video")
    ]

    assert "#define HOME_CALL_AUDIO_RTP_PORT 45544" in media_bridge
    assert "#define HOME_CALL_AUDIO_RTCP_PORT 45545" in media_bridge
    assert "#define HOME_CALL_TALKBACK_SILENCE_GRACE_MS (APP_AUDIO_PACKET_MS * 2)" in media_bridge
    assert "HOME_CALL_APP_INSTANCE_UUID" not in media_bridge
    assert "bridge->home_call_app_instance_uuid" in media_bridge
    assert "INVITE sip:%s SIP/2.0\\r\\n" in media_bridge
    assert '"m=audio %d RTP/SAVP 96 97 98 0 8 101 99 100\\r\\n"' in home_call_body
    assert '"m=video' not in home_call_body
    assert '"s=BTicino Home Call\\r\\n"' in rtsp_home_call_sdp
    assert '"m=audio 0 RTP/AVP 110\\r\\n"' in rtsp_home_call_sdp
    assert '"m=video' not in rtsp_home_call_sdp
    assert '"Session: %s\\r\\nRTP-Info: url=%s/streamid=%d;seq=0;rtptime=0\\r\\n"' in rtsp_body
    assert "home_call_session ? 0 : 1" in rtsp_body
    assert (
        'target_audio_port = parse_sdp_media_port(message, "\\r\\nm=audio ", 7078);'
        in home_call_body
    )
    assert "bridge->home_call_rtp_proxy = target_audio_port != 7078;" in home_call_body
    assert "send_app_audio_silence(audio_fd, target_audio_port" in home_call_body
    assert "send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1" in home_call_body
    assert "start_bt_av_media" not in home_call_body
    assert "bridge->home_call_srtp_state = &srtp;" in home_call_thread
    assert "start_talkback_proxy(bridge)" in home_call_thread
    assert "home_call_talkback_recent_locked(bridge, now)" in home_call_thread
    assert "forward_rtsp_packet(bridge, packet, packet_len, true)" in drain_home_call_body
    assert (
        "packet[1] = (unsigned char)((packet[1] & 0x80) | RTSP_AUDIO_PAYLOAD_TYPE);"
        in drain_home_call_body
    )
    assert "APP_AUDIO_PAYLOAD_TYPE" in home_call_talkback_body
    assert "bridge->home_call_target_audio_port" in home_call_talkback_body
    assert "bridge->home_call_last_talkback_ms = monotonic_ms();" in home_call_talkback_body


def test_native_agent_home_call_stop_matches_app_cancel_before_answer() -> None:
    media_bridge = _read_media_bridge()
    invite_body = media_bridge[
        media_bridge.index("static bool send_home_call_invite") :
        media_bridge.index("static void send_home_call_cancel")
    ]
    cancel_body = media_bridge[
        media_bridge.index("static void send_home_call_cancel") :
        media_bridge.index("static void *home_call_thread_func")
    ]
    home_call_thread = media_bridge[
        media_bridge.index("static void *home_call_thread_func") :
        media_bridge.index("static void *rtp_relay_thread")
    ]
    ringing_loop = home_call_thread[
        home_call_thread.index("while (!answered") :
        home_call_thread.index("if (!answered)")
    ]
    answered_loop = home_call_thread[
        home_call_thread.index("while (true)") :
        home_call_thread.index("cleanup:")
    ]

    assert "branch=%s;rport" in invite_body
    assert "invite_branch" in invite_body
    assert '"CANCEL sip:%s SIP/2.0\\r\\n"' in cancel_body
    assert '"Via: SIP/2.0/%s %s:%u;branch=%s;rport\\r\\n"' in cancel_body
    assert '"To: <sip:%s>\\r\\n"' in cancel_body
    assert '"From: <sip:%s>;tag=%s\\r\\n"' in cancel_body
    assert '"CSeq: 21 CANCEL\\r\\n"' in cancel_body
    assert '"User-Agent: " APP_USER_AGENT' not in cancel_body
    assert "drain_home_call_stop_responses(fd, \"CANCEL\", true)" in ringing_loop
    assert "send_home_call_cancel(" in ringing_loop
    assert "send_sip_bye(" not in ringing_loop
    assert "send_sip_bye(" in answered_loop
    assert "drain_home_call_stop_responses(fd, \"BYE\", false)" in answered_loop
    assert "send_home_call_cancel(" not in answered_loop


def test_native_agent_home_call_ack_and_bye_match_app_headers() -> None:
    media_bridge = _read_media_bridge()
    ack_body = media_bridge[
        media_bridge.index("static void send_sip_ack") :
        media_bridge.index("static void send_sip_ok_response")
    ]
    bye_body = media_bridge[
        media_bridge.index("static void send_sip_bye") :
        media_bridge.index("static void close_home_call_fds_locked")
    ]
    stop_drain_body = media_bridge[
        media_bridge.index("static void drain_home_call_stop_responses") :
        media_bridge.index("static void *home_call_thread_func")
    ]

    assert '"CSeq: %d ACK\\r\\n"' in ack_body
    assert '"User-Agent: " APP_USER_AGENT "\\r\\n"' in ack_body
    assert ack_body.index('"CSeq: %d ACK\\r\\n"') < ack_body.index(
        '"User-Agent: " APP_USER_AGENT "\\r\\n"'
    )

    assert '"BYE %s SIP/2.0\\r\\n"' in bye_body
    assert '"CSeq: 22 BYE\\r\\n"' in bye_body
    assert '"User-Agent: " APP_USER_AGENT "\\r\\n"' in bye_body
    assert bye_body.index('"CSeq: 22 BYE\\r\\n"') < bye_body.index(
        '"User-Agent: " APP_USER_AGENT "\\r\\n"'
    )

    assert 'strcmp(cseq_method, stop_method) == 0' in stop_drain_body
    assert 'wait_invite_final && strcmp(cseq_method, "INVITE") == 0' in stop_drain_body
    assert "stop_response_seen && invite_final_seen" in stop_drain_body


def test_native_agent_home_call_emits_authoritative_state_events() -> None:
    media_bridge = _read_media_bridge()
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    video_header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    home_call_thread = media_bridge[
        media_bridge.index("static void *home_call_thread_func") :
        media_bridge.index("static void *rtp_relay_thread")
    ]

    assert (
        'dispatch_home_call_state_event(bridge, "home_call.started")'
        in home_call_thread
    )
    assert (
        'dispatch_home_call_state_event(bridge, "home_call.answered")'
        in home_call_thread
    )
    assert "dispatch_home_call_ended_event(bridge)" in home_call_thread
    assert (
        'c300x_video_dispatch_event(video, "home_call.ended", data, 30)'
        in media_bridge
    )
    assert "strncmp(message, \"BYE \", 4) == 0" in home_call_thread
    assert "send_sip_ok_response(fd, message)" in home_call_thread
    assert "typedef void (*c300x_video_event_callback)" in video_header
    assert "int event_read_fd;" in video
    assert "struct c300x_video_event pending_events" in video
    assert (
        "c300x_video_set_event_callback(video, dispatch_video_event, runtime);"
        in http
    )
    assert (
        "dispatch_event(runtime->config, runtime, event_type, data_json, ttl_seconds);"
        in http
    )


def test_native_agent_ring_lifecycle_status_and_stop_paths_are_explicit() -> None:
    media_bridge = _read_media_bridge()
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    video_header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    session_stop_body = media_bridge[
        media_bridge.index("void c300x_media_session_stop") :
        media_bridge.index("bool c300x_media_session_keepalive")
    ]
    bridge_stop_body = media_bridge[media_bridge.index("void c300x_media_bridge_stop") :]

    create_body = video[
        video.index("struct c300x_video *c300x_video_create") :
        video.index("void c300x_video_destroy")
    ]
    ring_receiver_body = video[
        video.index("void c300x_video_set_ring_receiver_enabled") :
        video.index("int c300x_video_activate")
    ]
    assert "(void)c300x_video_ensure_running(video);" in create_body
    assert "c300x_media_ring_receiver_start" not in create_body
    assert "(void)c300x_media_ring_receiver_start(video->config, video);" in ring_receiver_body
    assert "c300x_media_ring_receiver_stop(video);" in ring_receiver_body
    assert "c300x_media_ring_receiver_stop(video);" in video
    activate_video_body = video[
        video.index("int c300x_video_activate") : video.index("void c300x_video_stop")
    ]
    assert activate_video_body.index("c300x_media_ring_call_active(video)") < (
        activate_video_body.index("external_media_active_locked(video)")
    )
    stop_body = video[
        video.index("void c300x_video_stop") :
        video.index("int c300x_video_home_call_start")
    ]
    assert "c300x_media_session_stop(video);" in stop_body
    assert "c300x_media_bridge_stop(video);" not in stop_body
    assert "video->running = 0;" not in stop_body
    assert "stop_ring_call_if_active(true, true)" in session_stop_body
    assert "dispatch_closed = g_bridge.video == video && !home_call_active_locked(&g_bridge);" in session_stop_body
    assert session_stop_body.index("stop_ring_call_if_active") < session_stop_body.index(
        "stop_media_session(true)"
    )
    assert session_stop_body.count(
        'c300x_video_dispatch_event(video, "doorbell.media.closed", "{}", 0);'
    ) == 2
    assert "ring_sleep_seconds(bridge, RING_RETRY_SECONDS)" in media_bridge
    assert "pthread_join(ring_thread, NULL)" in media_bridge
    assert (
        "if (!g_bridge.ring_started && !g_bridge.home_call_started && !g_bridge.home_call_active)"
        in bridge_stop_body
    )
    for field in (
        "ring_receiver_running",
        "ring_registered",
        "ring_call_active",
        "ring_media_active",
        "ring_audio_active",
        "ring_answer_requested",
        "ring_answered",
        "home_call_running",
        "home_call_active",
        "home_call_answered",
        "home_call_rtp_proxy",
    ):
        assert f"int {field};" in video_header
        assert f'\\"{field}\\":%s' in http
    for field, marker in (
        ("home_call_target_audio_port", "%d"),
        ("home_call_rtp_packets", "%llu"),
            ("home_call_rtcp_packets", "%llu"),
    ):
        assert f"int {field};" in video_header or f"unsigned long long {field};" in video_header
        assert f'\\"{field}\\":{marker}' in http
    assert "int window_available = 0;" in http
    assert "ring_call_active" in http
    assert "ring_media_active" in http
    assert "!home_call_running" in http
    assert "!home_call_active" in http
    assert "&& (bridge_media_active || call_active)" in http
    assert '"\\"window_available\\":%s,"' in http
    activate_body = http[
        http.index("static void handle_doorbell_video_activate") :
        http.index("static void handle_doorbell_video_stop")
    ]
    assert activate_body.index("status.ring_call_active || status.ring_media_active") < (
        activate_body.index("c300x_video_activate(runtime->video, audio)")
    )
    assert '\\"ring_active\\":true' in activate_body
    assert 'snprintf(status->media_owner, sizeof(status->media_owner), "%s", "ring")' in video
    assert 'snprintf(status->media_owner, sizeof(status->media_owner), "%s", "home_call")' in video


def test_native_agent_exposes_explicit_doorbell_call_api_without_new_sip_path() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    video = (ROOT / "native_agent" / "src" / "video_rtsp.c").read_text(
        encoding="utf-8"
    )
    video_header = (ROOT / "native_agent" / "src" / "video_rtsp.h").read_text(
        encoding="utf-8"
    )
    media_header = (ROOT / "native_agent" / "src" / "media_bridge.h").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")

    answer_bridge_body = media_bridge[
        media_bridge.index("bool c300x_media_ring_call_answer") :
        media_bridge.index("void c300x_media_ring_call_hangup")
    ]
    hangup_bridge_body = media_bridge[
        media_bridge.index("void c300x_media_ring_call_hangup") :
        media_bridge.index("bool c300x_media_talkback_running")
    ]
    answer_video_body = video[
        video.index("int c300x_video_doorbell_call_answer") :
        video.index("void c300x_video_doorbell_call_hangup")
    ]
    hangup_video_body = video[
        video.index("void c300x_video_doorbell_call_hangup") :
        video.index("int c300x_video_home_call_start")
    ]
    answer_http_body = http[
        http.index("static void handle_doorbell_call_answer") :
        http.index("static void handle_doorbell_call_hangup")
    ]
    hangup_http_body = http[
        http.index("static void handle_doorbell_call_hangup") :
        http.index("static void handle_doorbell_call_capture")
    ]
    router_body = http[
        http.index('"/api/v1/video/doorbell/actions/stop"') :
        http.index('"/api/v1/calls/home"', http.index('"/api/v1/video/doorbell/actions/stop"'))
    ]

    assert "int ring_answer_requested;" in video_header
    assert "int ring_answered;" in video_header
    assert "bool c300x_media_ring_call_answer(struct c300x_video *video, bool audio);" in media_header
    assert "void c300x_media_ring_call_hangup(struct c300x_video *video);" in media_header
    assert "int c300x_video_doorbell_call_answer(struct c300x_video *video, int include_audio);" in video_header
    assert "void c300x_video_doorbell_call_hangup(struct c300x_video *video);" in video_header
    assert "request_ring_answer_if_active(&g_bridge, audio)" in answer_bridge_body
    assert "send_ring_response" not in answer_bridge_body
    assert "build_ring_sdp" not in answer_bridge_body
    assert "c300x_media_session_stop(video);" in hangup_bridge_body
    assert "stop_ring_call_if_active" not in hangup_bridge_body
    assert "c300x_media_ring_call_answer(video, include_audio != 0)" in answer_video_body
    assert "c300x_media_ring_call_hangup(video);" in hangup_video_body
    assert "c300x_video_doorbell_call_answer(runtime->video, audio)" in answer_http_body
    assert '\\"ring_call_not_active\\"' in answer_http_body
    assert "c300x_video_doorbell_call_hangup(runtime->video);" in hangup_http_body
    for path in (
        "/api/v1/calls/doorbell/status",
        "/api/v1/calls/doorbell/actions/answer",
        "/api/v1/calls/doorbell/actions/hangup",
        "/api/v1/calls/doorbell/actions/capture",
    ):
        assert path in router_body
    assert '\\"capture_supported\\":false' in http
    assert '\\"capture_not_supported\\"' in http
    assert '\\"doorbell_call\\":{\\"supported\\":%s,\\"answer\\":true,\\"hangup\\":true,\\"status\\":true,\\"capture\\":false}' in http


def test_native_agent_doorbell_events_include_device_media_state() -> None:
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    state_body = http[
        http.index("static int doorbell_event_needs_video_status") :
        http.index("static void dispatch_event_internal")
    ]
    dispatch_body = http[
        http.index("static void dispatch_event_internal") :
        http.index("static void dispatch_event(", http.index("static void dispatch_event_internal"))
    ]

    assert 'strcmp(event_type, "doorbell.pressed") == 0' in state_body
    assert 'strcmp(event_type, "doorbell.view_requested") == 0' in state_body
    assert 'strcmp(event_type, "doorbell.media.closed") == 0' in state_body
    assert "status.ring_call_active" in state_body
    assert "status.ring_media_active" in state_body
    assert "status.bridge_media_active" in state_body
    assert "status.call_active" in state_body
    assert "external_media_active = status.external_media_active && !available;" in state_body
    for field in (
        "available",
        "window_available",
        "stream_path",
        "external_media_active",
    ):
        assert f'\\"{field}\\":' in state_body
    assert '\\"doorbell\\":%s' in state_body
    assert 'doorbell_state_for_event(event_type)' in state_body
    assert "size_t used = 0;" in state_body
    assert "build_doorbell_event_state_json" in state_body
    assert "has_video = runtime != NULL" in state_body
    assert 'snprintf(out, out_len, "\\"doorbell\\":%s", doorbell_state_json)' in state_body
    assert dispatch_body.index(
        "c300x_video_note_event(runtime->video, event_type, ttl_seconds)"
    ) < dispatch_body.index("build_event_data_json(")
    assert "c300x_mqtt_publish_event(&runtime->mqtt, config, event_type, event_json, merged_json)" in dispatch_body


def test_native_agent_doorbell_stop_does_not_match_home_call_resources() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    stop_body = media_bridge[
        media_bridge.index("void c300x_media_session_stop") :
        media_bridge.index("bool c300x_media_session_keepalive")
    ]

    assert "home_call_active_locked(&g_bridge)" in stop_body
    assert "g_bridge.client_fd >= 0" not in stop_body
    assert "g_bridge.home_call_sip_fd" not in stop_body
    assert "g_bridge.home_call_audio_rtp_fd" not in stop_body
