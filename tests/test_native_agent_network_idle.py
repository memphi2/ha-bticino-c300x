from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_body(text: str, return_type: str, name: str) -> str:
    return text.rsplit(f"{return_type} {name}", maxsplit=1)[1].split(
        "\n}\n",
        maxsplit=1,
    )[0]


def _c300x_run_loop_body(text: str) -> str:
    run_body = text.rsplit("int c300x_run", maxsplit=1)[1]
    return run_body.split("while (!shutdown_requested) {", maxsplit=1)[1].split(
        "int poll_result = poll(poll_fds",
        maxsplit=1,
    )[0]


def test_agent_skips_callback_io_without_local_network() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = _function_body(text, "void", "dispatch_event_internal")
    bridge_body = _function_body(text, "int", "forward_to_homeassistant")

    assert dispatch_body.index("runtime_network_online(runtime, time(NULL))") < (
        dispatch_body.index("post_callback")
    )
    assert bridge_body.index("runtime_network_online(runtime, time(NULL))") < (
        bridge_body.index("parse_http_url")
    )
    assert bridge_body.index("runtime_network_online(runtime, time(NULL))") < (
        bridge_body.index("getaddrinfo")
    )


def test_agent_network_check_is_local_and_cached() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    network_body = _function_body(text, "int", "local_network_online")
    runtime_body = _function_body(text, "int", "runtime_network_online")

    assert "getifaddrs(&ifaddr)" in network_body
    assert "IFF_LOOPBACK" in network_body
    assert "0xa9fe0000U" in network_body
    assert "C300X_NETWORK_ONLINE_RECHECK_SECONDS" in runtime_body
    assert "C300X_NETWORK_OFFLINE_RECHECK_SECONDS" in runtime_body


def test_mdns_is_disabled_while_network_is_offline() -> None:
    text = (ROOT / "native_agent" / "src" / "mdns.c").read_text(encoding="utf-8")
    body = _function_body(text, "void", "c300x_mdns_open_if_needed")

    assert "!config->mdns_enabled || home_assistant_connected || !network_online" in body
    assert body.index("!network_online") < body.index("mdns_open_socket")


def test_mdns_advertises_home_assistant_zeroconf_shape() -> None:
    text = (ROOT / "native_agent" / "src" / "mdns.c").read_text(encoding="utf-8")
    build_body = _function_body(text, "static int", "mdns_build_response")
    header_body = _function_body(text, "static int", "mdns_put_record_header")
    socket_body = _function_body(text, "static int", "mdns_open_socket")
    ipv4_body = _function_body(text, "static struct in_addr", "mdns_local_ipv4")

    assert 'C300X_MDNS_ENUMERATION "_services._dns-sd._udp.local"' in text
    assert 'C300X_MDNS_SERVICE "_bticino-c300x-agent._tcp.local"' in text
    assert '"BTicino C300X"' in text
    assert "c300x_mdns_device_id(device_id, sizeof(device_id))" in build_body
    http_text = (ROOT / "native_agent" / "src" / "http.c").read_text(
        encoding="utf-8"
    )
    capabilities_body = _function_body(http_text, "static void", "api_capabilities")
    assert "c300x_mdns_device_id(device_id, sizeof(device_id))" in capabilities_body
    assert (
        '\\"device\\":{\\"id\\":\\"%s\\",\\"model\\":\\"%s\\",\\"firmware\\":\\"%s\\"}'
        in capabilities_body
    )
    assert '"id=%s"' in build_body
    assert '"name=%s"' in build_body
    assert "/sys/class/net" in text
    assert 'c300x_join_suffix(out, out_len, "c300x-", suffix)' in text
    assert "mdns_put_u16(buffer, buffer_len, &offset, 2)" in build_body
    assert "3 + (has_ipv6 ? 1 : 0)" in build_body
    assert "C300X_MDNS_CLASS_IN" in build_body
    assert "C300X_MDNS_CLASS_FLUSH_IN" in build_body
    assert "host_name,\n                28" in build_body
    assert "record_class" in header_body
    assert "mdns_set_fd_cloexec(fd)" in socket_body
    assert "membership.imr_interface = local_address" in socket_body
    assert "membership.imr_interface.s_addr = htonl(INADDR_ANY)" not in socket_body
    assert "0xa9fe0000U" in ipv4_body


def test_mdns_avoids_link_local_ipv6_advertisements() -> None:
    text = (ROOT / "native_agent" / "src" / "mdns.c").read_text(encoding="utf-8")
    body = _function_body(text, "static int", "mdns_local_ipv6")

    assert "IN6_IS_ADDR_LINKLOCAL" in body
    assert "IN6_IS_ADDR_LOOPBACK" in body
    assert "IN6_IS_ADDR_MULTICAST" in body


def test_main_loop_passes_cached_network_state_to_mdns() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    loop_body = _c300x_run_loop_body(text)

    assert "int network_online = runtime_network_online(runtime, now);" in loop_body
    assert "network_online,\n            now" in loop_body


def test_video_poll_timeout_preserves_existing_poll_deadlines() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    video_poll_body = text.split(
        "video_poll_count = c300x_video_pollfds",
        maxsplit=1,
    )[1].split(
        "if (system_metrics_watch_active",
        maxsplit=1,
    )[0]

    assert "poll_timeout_ms = min_timeout_ms(" in video_poll_body
    assert "c300x_video_poll_timeout_ms(video)" in video_poll_body
    assert "poll_timeout_ms = c300x_video_poll_timeout_ms(video)" not in video_poll_body


def test_agent_listener_sockets_cannot_leak_into_gui_reload_children() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    util_text = (ROOT / "native_agent" / "src" / "http_util.c").read_text(
        encoding="utf-8"
    )
    mqtt_text = (ROOT / "native_agent" / "src" / "mqtt_bridge.c").read_text(
        encoding="utf-8"
    )
    reuse_body = _function_body(util_text, "void", "allow_socket_reuse")
    listener_body = _function_body(text, "int", "make_listener")
    udp_body = _function_body(text, "int", "create_udp_event_socket")
    detached_body = _function_body(text, "static int", "run_detached_command")
    cleanup_body = _function_body(text, "static void", "close_extra_fds_for_exec")
    mqtt_connect_body = _function_body(mqtt_text, "static int", "socket_connect_timeout")

    assert "SO_REUSEPORT" not in reuse_body
    assert listener_body.index("set_fd_cloexec(fd)") < listener_body.index(
        "allow_socket_reuse(fd)"
    )
    assert udp_body.index("set_fd_cloexec(fd)") < udp_body.index(
        "allow_socket_reuse(fd)"
    )
    accept_body = text.split("int client_fd = accept", maxsplit=1)[1].split(
        "handle_client(client_fd",
        maxsplit=1,
    )[0]
    assert "set_fd_cloexec(client_fd)" in accept_body
    assert "close_extra_fds_for_exec()" in detached_body
    assert "close((int)fd)" in cleanup_body
    assert mqtt_connect_body.index("set_fd_cloexec(fd)") < mqtt_connect_body.index(
        "(void)set_nonblocking(fd)"
    )


def test_ui_event_long_poll_closes_when_client_disconnects() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    loop_body = _c300x_run_loop_body(text)
    post_poll_body = text.split("if (voice_memos_poll_index >= 0)", maxsplit=1)[
        1
    ].split(
        "if (video != NULL && video_poll_index >= 0",
        maxsplit=1,
    )[0]

    assert "int ui_event_poll_index = -1;" in loop_body
    assert "poll_fds[poll_count].fd = runtime->ui_event_wait_fd;" in loop_body
    assert "poll_fds[poll_count].events = POLLIN | POLLRDHUP;" in loop_body
    assert "C300X_SOCKET_CLOSED_REVENTS" in post_poll_body
    assert "ui_event_close_wait(runtime, 0)" in post_poll_body


def test_native_http_client_sockets_are_explicitly_shutdown_before_close() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    util = (ROOT / "native_agent" / "src" / "http_util.c").read_text(
        encoding="utf-8"
    )
    header = (ROOT / "native_agent" / "src" / "http_util.h").read_text(
        encoding="utf-8"
    )
    helper_body = _function_body(util, "void", "close_agent_socket")
    client_body = _function_body(text, "static void", "handle_client")
    ui_wait_body = _function_body(text, "static void", "ui_event_close_wait")

    assert "#define C300X_SOCKET_CLOSED_REVENTS" in header
    assert "shutdown(fd, SHUT_RDWR)" in helper_body
    assert "close(fd)" in helper_body
    assert "close_agent_socket(client_fd)" in client_body
    assert "close(client_fd)" not in client_body
    assert "close_agent_socket(fd)" in ui_wait_body
    assert "close(fd)" not in ui_wait_body


def test_mqtt_poll_handles_peer_half_close_events() -> None:
    text = (ROOT / "native_agent" / "src" / "mqtt_bridge.c").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = _function_body(text, "void", "c300x_mqtt_handle_poll")
    loop_body = _c300x_run_loop_body(http)

    assert '#include "http_util.h"' in text
    assert "POLLRDHUP" in http
    assert "revents & C300X_SOCKET_CLOSED_REVENTS" in body
    assert "poll_fds[poll_count].events = POLLIN | POLLRDHUP;" in loop_body


def test_native_base64_decoder_bounds_unsigned_accumulator() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = _function_body(text, "static int", "base64_decode_bytes")

    assert "unsigned int value = 0;" in body
    assert "& 0x00ffffffU" in body
    assert "value = (value << 6) | sextet;" not in body


def test_mdns_uses_current_runtime_connection_not_persisted_subscriptions() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = _function_body(text, "static int", "agent_has_home_assistant_connection")
    subscription_body = _function_body(text, "static void", "handle_subscriptions_post")
    display_body = _function_body(text, "static void", "handle_display_bridge_post")
    dispatch_body = _function_body(text, "static void", "dispatch_event_internal")

    assert "runtime->home_assistant_connected_this_run" in body
    assert "runtime->home_assistant_last_seen_at" not in body
    assert "C300X_HOME_ASSISTANT_CONNECTED_SECONDS" not in text
    assert "runtime->subscription_count > 0" not in body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" in subscription_body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" not in display_body
    assert "if (subscription->last_ok)" in dispatch_body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" in dispatch_body


def test_subscription_snapshots_are_marked_as_non_live_events() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = _function_body(text, "static void", "dispatch_event_internal")
    voicemail_body = _function_body(text, "static void", "voicemail_event_dispatch_snapshot")
    memos_body = _function_body(text, "static void", "memos_event_dispatch_snapshot")

    assert '\\"snapshot\\":%s' in dispatch_body
    assert "snapshot ? \"true\" : \"false\"" in dispatch_body
    assert "dispatch_event_snapshot(config, runtime, \"answering_machine.messages_changed\"" in voicemail_body
    assert "dispatch_event_snapshot(config, runtime, \"memos.changed\"" in memos_body


def test_agent_event_subscriptions_are_runtime_only() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    post_body = _function_body(text, "static void", "handle_subscriptions_post")

    assert "load_subscriptions(" not in text
    assert "save_subscriptions(" not in text
    assert "subscriptions_loaded_deduplicated" not in text
    assert "record_agent_write(config, runtime, \"subscription\"" not in text
    assert "runtime->subscriptions[0] = subscription" in post_body
    assert "runtime->subscription_count = 1" in post_body


def test_display_bridge_callback_is_runtime_only() -> None:
    http_text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    config_text = (ROOT / "native_agent" / "src" / "config.c").read_text(
        encoding="utf-8"
    )
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    active_body = _function_body(http_text, "static int", "display_bridge_active")
    webhook_body = _function_body(
        http_text,
        "static const char",
        "*display_bridge_webhook_url",
    )
    secret_body = _function_body(
        http_text,
        "static const char",
        "*display_bridge_shared_secret",
    )
    status_body = _function_body(http_text, "static void", "handle_display_bridge_status")

    assert "return display_bridge_runtime_active(runtime)" in active_body
    assert "config->display_bridge_enabled" not in active_body
    assert "config->home_assistant_webhook_url" not in webhook_body
    assert "config->home_assistant_shared_secret" not in secret_body
    assert "config->display_bridge_enabled && !display_bridge_runtime_disabled(runtime)" in status_body
    assert "\"webhookUrl\"" not in config_text
    assert "\"sharedSecret\"" not in config_text
    assert "home_assistant_shared_secret" not in media_bridge


def test_ring_forwarding_state_does_not_poll_openwebnet_in_media_bridge() -> None:
    media_bridge = (ROOT / "native_agent" / "src" / "media_bridge.c").read_text(
        encoding="utf-8"
    )
    http = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    ring_thread_body = media_bridge[
        media_bridge.index("static void *ring_receiver_thread") :
        media_bridge.index("static void *sip_monitor_thread")
    ]

    assert "*#8**37##" not in media_bridge
    assert "RING_FORWARDING_CHECK_SECONDS" not in media_bridge
    assert "next_forwarding_check" not in media_bridge
    assert "ring_wait_for_forwarding_enabled" not in ring_thread_body
    assert "c300x_openwebnet_send(config, \"*#8**37##\"" in http
    assert "refresh_smartphone_forwarding_mode(config, runtime)" in http
