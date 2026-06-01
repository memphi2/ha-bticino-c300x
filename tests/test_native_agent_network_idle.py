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
    return run_body.split("for (;;) {", maxsplit=1)[1].split(
        "if (poll(poll_fds",
        maxsplit=1,
    )[0]


def test_agent_skips_callback_io_without_local_network() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    dispatch_body = _function_body(text, "void", "dispatch_event")
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
    assert 'snprintf(out, out_len, "c300x-%s", suffix)' in text
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
    reuse_body = _function_body(text, "void", "allow_socket_reuse")
    listener_body = _function_body(text, "int", "make_listener")
    udp_body = _function_body(text, "int", "create_udp_event_socket")

    assert "SO_REUSEPORT" not in reuse_body
    assert listener_body.index("set_fd_cloexec(fd)") < listener_body.index(
        "allow_socket_reuse(fd)"
    )
    assert udp_body.index("set_fd_cloexec(fd)") < udp_body.index(
        "allow_socket_reuse(fd)"
    )


def test_mdns_uses_current_runtime_connection_not_persisted_subscriptions() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    body = _function_body(text, "static int", "agent_has_home_assistant_connection")
    subscription_body = _function_body(text, "static void", "handle_subscriptions_post")
    display_body = _function_body(text, "static void", "handle_display_bridge_post")
    dispatch_body = _function_body(text, "static void", "dispatch_event")

    assert "runtime->home_assistant_connected_this_run" in body
    assert "runtime->home_assistant_last_seen_at" in body
    assert "C300X_HOME_ASSISTANT_CONNECTED_SECONDS" in body
    assert "runtime->subscription_count > 0" not in body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" not in subscription_body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" not in display_body
    assert "if (subscription->last_ok)" in dispatch_body
    assert "mark_home_assistant_callback_seen(runtime, time(NULL))" in dispatch_body


def test_agent_keeps_only_one_loaded_subscription_and_cleans_store_lazily() -> None:
    text = (ROOT / "native_agent" / "src" / "http.c").read_text(encoding="utf-8")
    load_body = _function_body(text, "static void", "load_subscriptions")
    post_body = _function_body(text, "static void", "handle_subscriptions_post")

    assert "runtime->subscriptions[0] = subscription" in load_body
    assert "runtime->subscription_count = 1" in load_body
    assert "runtime->subscriptions_loaded_deduplicated = 1" in load_body
    assert "runtime->subscriptions_loaded_deduplicated" in post_body
    assert '"deduplicated"' in post_body
