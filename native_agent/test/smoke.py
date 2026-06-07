#!/usr/bin/env python3
"""Local behavioral smoke test for the native C300X agent."""

from __future__ import annotations

import base64
import contextlib
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TOKEN = "local-test-token"


class OpenWebNetServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), OpenWebNetHandler)
        self.frames: list[str] = []
        self.delete_paths: dict[str, Path] = {}
        self.smartphone_forwarding_code = 2


class OpenWebNetHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        server = self.server
        assert isinstance(server, OpenWebNetServer)
        self.request.sendall(b"*#*1##")
        if read_frame(self.request) != "*99*0##":
            return
        self.request.sendall(b"*#*1##")
        while True:
            frame = read_frame(self.request)
            if not frame:
                return
            server.frames.append(frame)
            if path := server.delete_paths.get(frame):
                shutil.rmtree(path, ignore_errors=True)
            self.request.sendall(reply_for_openwebnet_frame(server, frame).encode())


class CallbackServer(http.server.ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), CallbackHandler)
        self.requests: list[dict[str, Any]] = []


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body.decode())
        server = self.server
        assert isinstance(server, CallbackServer)
        server.requests.append(
            {
                "token": self.headers.get("X-Bticino-C300X-Event-Token"),
                "secret": self.headers.get("X-Bticino-C300X-Secret"),
                "body": payload,
            }
        )
        if self.path == "/display":
            if payload.get("type") == "dashboard":
                response = {
                    "data": {"pages": [{"title": "Smoke", "buttons": []}]},
                    "preventReturnToHomepage": True,
                }
            else:
                response = {
                    "device_ui_enabled": True,
                    "alarm_configured": True,
                    "dashboard_available": True,
                    "alarm": {"entity_id": "alarm_control_panel.test", "state": "disarmed"},
                }
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: smoke.py <native-agent-binary>\n")
        return 2
    binary = Path(sys.argv[1]).resolve()
    if not binary.exists():
        sys.stderr.write(f"missing native agent binary: {binary}\n")
        return 2
    assert_video_timer_preserves_existing_poll_timeout(binary)
    assert_rtsp_udp_preserves_ipv4_mapped_peers(binary)
    assert_overlong_activation_id_is_rejected(binary)
    assert_graceful_shutdown_signal_is_handled(binary)

    with (
        managed_tcp_server(OpenWebNetServer()) as openwebnet,
        managed_tcp_server(CallbackServer()) as callback,
    ):
        return run_smoke(binary, openwebnet, callback)


def assert_video_timer_preserves_existing_poll_timeout(binary: Path) -> None:
    """Guard the main loop against video overwriting mDNS/metrics timers."""

    source = binary.parents[2] / "src" / "http.c"
    if not source.exists():
        return
    content = source.read_text(encoding="utf-8")
    wanted = (
        "poll_timeout_ms = min_timeout_ms(\n"
        "                poll_timeout_ms,\n"
        "                c300x_video_poll_timeout_ms(video)\n"
        "            );"
    )
    if wanted not in content:
        raise AssertionError("video poll timeout must be combined with existing timers")


def assert_rtsp_udp_preserves_ipv4_mapped_peers(binary: Path) -> None:
    """Guard IPv4 UDP clients accepted through the dual-stack RTSP listener."""

    source = binary.parents[2] / "src" / "media_bridge.c"
    if not source.exists():
        return
    content = source.read_text(encoding="utf-8")
    required = (
        "rtsp_peer_ipv4_address",
        "IN6_IS_ADDR_V4MAPPED",
        "peer6->sin6_addr.s6_addr[12]",
        "rtsp_peer_ipv4_address(peer, &g_bridge.udp_client.sin_addr)",
    )
    if any(item not in content for item in required):
        raise AssertionError("RTSP UDP peer handling must preserve IPv4-mapped IPv6 clients")


def assert_overlong_activation_id_is_rejected(binary: Path) -> None:
    """Guard against silently truncating configured activation IDs."""

    with tempfile.TemporaryDirectory(prefix="c300x-activation-id-smoke-") as temp_dir:
        config_path = Path(temp_dir) / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "api": {"token": "", "noAuth": True},
                    "activations": {
                        "enabled": True,
                        "items": [
                            {
                                "id": ("a" * 32) + "/",
                                "name": "Overlong",
                                "type": "unknown",
                            }
                        ],
                    },
                    "events": {"udp": {"enabled": False}},
                    "answeringMachine": {"messages": {"enabled": False}},
                    "memos": {"enabled": False},
                    "systemMetrics": {"enabled": False},
                    "video": {"enabled": False},
                    "displayBridge": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(binary), "--config", str(config_path), "--check-config"],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode == 0:
        raise AssertionError("overlong activation id with invalid suffix was accepted")
    if "activations item id must be a safe string" not in result.stderr:
        raise AssertionError(f"unexpected activation id validation error: {result.stderr!r}")


def assert_graceful_shutdown_signal_is_handled(binary: Path) -> None:
    """Guard update restarts so SIGTERM runs the native cleanup path."""

    source_root = binary.parents[2] / "src"
    http = source_root / "http.c"
    video = source_root / "video_rtsp.c"
    if not http.exists() or not video.exists():
        return
    http_content = http.read_text(encoding="utf-8")
    video_content = video.read_text(encoding="utf-8")
    required_http = (
        "static volatile sig_atomic_t shutdown_requested",
        "signal(SIGTERM, handle_shutdown_signal)",
        "while (!shutdown_requested)",
        "if (shutdown_requested && result == 1)",
        "c300x_video_destroy(video);",
    )
    if any(item not in http_content for item in required_http):
        raise AssertionError("native agent must handle SIGTERM through cleanup")
    destroy_body = video_content[
        video_content.index("void c300x_video_destroy") :
        video_content.index("int c300x_video_activate")
    ]
    if "if (video->enabled)" not in destroy_body:
        raise AssertionError("video destroy must not depend on the running flag for cleanup")
    for cleanup_call in (
        "c300x_media_bridge_stop(video);",
        "c300x_media_home_call_stop(video);",
        "c300x_media_ring_receiver_stop(video);",
    ):
        if cleanup_call not in destroy_body:
            raise AssertionError("video destroy must stop all media subsystems")


def run_smoke(
    binary: Path,
    openwebnet: OpenWebNetServer,
    callback: CallbackServer,
) -> int:
    assert_runtime_bridge_binds_ui_when_disabled(binary, openwebnet, callback)
    assert_sigterm_shutdown_exits_cleanly(binary, openwebnet)
    api_port = free_tcp_port()
    ui_port = free_tcp_port()
    rtsp_port = free_tcp_port()
    udp_port = free_udp_port()
    with tempfile.TemporaryDirectory(prefix="c300x-native-smoke-") as temp_dir:
        temp_path = Path(temp_dir)
        messages_root = temp_path / "messages"
        text_memos_root = temp_path / "memos_text"
        voice_memos_root = temp_path / "memos_voice"
        activation_root = temp_path / "device_activations"
        qml_patch_script = temp_path / "qml_patch.sh"
        qml_patch_log = temp_path / "qml_patch_actions.txt"
        remove_agent_script = temp_path / "remove_agent.sh"
        remove_agent_log = temp_path / "remove_agent_actions.txt"
        firewall_path = temp_path / "iptables"
        firewall_backup_path = temp_path / "backup" / "iptables"
        ipv6_firewall_path = temp_path / "iptables6"
        ipv6_firewall_backup_path = temp_path / "backup" / "iptables6"
        config_path = temp_path / "config.json"
        text_memos_root.mkdir()
        voice_memos_root.mkdir()
        activation_root.mkdir()
        (activation_root / "quick_actions.json").write_text(
            json.dumps(
                {
                    "actions": [
                        {
                            "name": "Garden gate",
                            "command": "*8*19*40##",
                            "release": "*8*20*40##",
                        },
                        {
                            "label": "Path light",
                            "openwebnet": "*8*21*42##",
                        },
                        {
                            "name": "Unsafe delete must not be imported",
                            "openwebnet": "*8*94#1#0##",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        firewall_path.write_text("#!/bin/sh\n# stock firewall\n", encoding="utf-8")
        ipv6_firewall_path.write_text(
            "#!/bin/sh\n# stock ipv6 firewall\n",
            encoding="utf-8",
        )
        qml_patch_script.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"echo \"$1\" >> {qml_patch_log}",
                    "case \"$1\" in",
                    "  status) echo '{\"ok\":true,\"available\":true,\"state\":\"original\",\"patched\":false,\"core_state\":\"original\",\"core_patched\":false,\"backup_available\":false,\"core_backup_available\":false}' ;;",
                    "  apply) echo '{\"ok\":true,\"available\":true,\"state\":\"patched\",\"patched\":true,\"core_state\":\"patched\",\"core_patched\":true,\"backup_available\":true,\"core_backup_available\":true,\"changed_files\":1}' ;;",
                    "  core-apply) echo '{\"ok\":true,\"available\":true,\"state\":\"original\",\"patched\":false,\"core_state\":\"patched\",\"core_patched\":true,\"backup_available\":false,\"core_backup_available\":true,\"changed_files\":1}' ;;",
                    "  core-restore) echo '{\"ok\":true,\"available\":true,\"state\":\"original\",\"patched\":false,\"core_state\":\"original\",\"core_patched\":false,\"backup_available\":false,\"core_backup_available\":true,\"changed_files\":1}' ;;",
                    "  restore) echo '{\"ok\":true,\"available\":true,\"state\":\"original\",\"patched\":false,\"core_state\":\"patched\",\"core_patched\":true,\"backup_available\":true,\"core_backup_available\":true,\"changed_files\":1}' ;;",
                    "  reload) echo '{\"ok\":true,\"action\":\"reload_gui\",\"gui_running\":true}' ;;",
                    "  *) exit 2 ;;",
                    "esac",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        qml_patch_script.chmod(0o700)
        remove_agent_script.write_text(
            "\n".join(
                [
                    "#!/bin/sh",
                    f"echo \"$1\" >> {remove_agent_log}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        remove_agent_script.chmod(0o700)
        config_path.write_text(
            json.dumps(
                {
                    "listen": {
                        "host": "127.0.0.1",
                        "apiPort": api_port,
                        "uiPort": ui_port,
                        "allowLan": False,
                    },
                    "api": {"token": "", "noAuth": False},
                    "openwebnet": {
                        "host": "127.0.0.1",
                        "port": openwebnet.server_address[1],
                        "timeoutMs": 1000,
                    },
                    "device": {
                        "model": "C300X",
                        "firmware": "1.7.19",
                        "stairLightDefaultAddress": "10",
                    },
                    "locks": {
                        "releaseDelayMs": 1,
                        "items": {"default": {"name": 'Main "door"', "address": "20"}},
                    },
                    "activations": {
                        "enabled": True,
                        "autoDiscover": True,
                        "discoveryRoots": [str(activation_root)],
                        "items": [
                            {
                                "id": "front_gate",
                                "name": "Front gate",
                                "type": "lock",
                                "addressMode": "manual",
                                "address": "30",
                            },
                            {
                                "id": "activation_id_0123456789abcdef01",
                                "name": "Long id lock",
                                "type": "lock",
                                "addressMode": "manual",
                                "address": "31",
                            },
                            {
                                "id": "unknown_only",
                                "name": "Unknown only",
                                "type": "unknown",
                                "addressMode": "auto",
                            },
                        ],
                    },
                    "maintenance": {
                        "enabled": True,
                        "adminToken": "maintenance-token",
                        "sshStart": {"enabled": False},
                        "reboot": {"enabled": False},
                        "agentRemove": {
                            "enabled": True,
                            "script": str(remove_agent_script),
                        },
                        "guiReload": {
                            "enabled": True,
                            "script": str(qml_patch_script),
                        },
                        "qmlPatch": {
                            "enabled": True,
                            "script": str(qml_patch_script),
                        },
                        "firewall": {
                            "enabled": True,
                            "path": str(firewall_path),
                            "backupPath": str(firewall_backup_path),
                        },
                        "ipv6Firewall": {
                            "enabled": True,
                            "path": str(ipv6_firewall_path),
                            "backupPath": str(ipv6_firewall_backup_path),
                        },
                    },
                    "events": {
                        "callbackTimeoutMs": 1000,
                        "udp": {
                            "enabled": True,
                            "group": "239.255.76.67",
                            "port": udp_port,
                        },
                    },
                    "video": {
                        "enabled": True,
                        "rtsp": {
                            "port": rtsp_port,
                            "rtpPortStart": 10000,
                            "rtpPortCount": 4,
                            "videoPath": "/doorbell-video",
                        },
                    },
                    "answeringMachine": {
                        "messages": {
                            "enabled": True,
                            "root": str(messages_root),
                            "watch": True,
                            "maxMessages": 16,
                        }
                    },
                    "memos": {
                        "enabled": True,
                        "textRoot": str(text_memos_root),
                        "voiceRoot": str(voice_memos_root),
                        "watch": True,
                        "maxMemos": 16,
                    },
                    "systemMetrics": {
                        "enabled": True,
                        "watch": True,
                        "sampleIntervalSeconds": 5,
                        "heartbeatSeconds": 5,
                        "changePercent": 5,
                    },
                    "displayBridge": {
                        "enabled": True,
                        "homeAssistant": {
                            "webhookUrl": display_callback_url(callback),
                            "sharedSecret": "config-display-secret",
                            "requestTimeoutMs": 1000,
                        },
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["C300X_AGENT_TOKEN"] = TOKEN
        process = subprocess.Popen(
            [str(binary), "--config", str(config_path)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_health(api_port)
            expected_agent_writes = 0
            disabled_setup = api_request(
                api_port,
                "GET",
                "/setup",
                None,
                authorized=False,
                expected_status=404,
            )
            assert_json_field(disabled_setup, "error", "setup_disabled")
            auth_status = maintenance_get(api_port, "/api/v1/maintenance/auth")
            assert_json_field(auth_status, "noAuth", False)
            assert_json_field(auth_status, "api_token_configured", True)
            assert_absent(auth_status, "api_token")
            assert_absent(auth_status, "maintenance_token")
            assert_json_field(
                auth_status,
                "api_token_fingerprint",
                "fnv1a64:28fd96f48ba0b9b5",
            )
            assert_json_field(
                auth_status,
                "maintenance_token_fingerprint",
                "fnv1a64:7b9eb57f33954dd2",
            )
            assert_json_field(auth_status, "api_listen_host", "127.0.0.1")
            assert_json_field(auth_status, "ui_listen_host", "127.0.0.1")
            auth_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/auth",
                {"noAuth": True},
            )
            expected_agent_writes += 1
            assert_json_field(auth_status, "noAuth", True)
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/auth",
                    {"noAuth": True},
                ),
                "noAuth",
                True,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_wake_reason", "api")
            assert_int_field_at_least(diagnostics, "loop_iterations", 1)
            assert_int_field_at_least(diagnostics, "poll_wakeups", 1)
            assert_int_field_at_least(diagnostics, "accepted_clients", 1)
            assert_int_field_at_least(diagnostics, "open_fd_count", 1)
            assert_int_field_at_least(diagnostics, "video_bridge_open_fds", 0)
            assert_int_field_at_least(diagnostics, "video_bridge_active_threads", 0)
            assert_aborted_clients_do_not_leak_fds(process.pid, api_port, ui_port)
            read_only_actions = (
                ("health", lambda: api_get(api_port, "/api/v1/health", authorized=False)),
                ("capabilities", lambda: api_get(api_port, "/api/v1/capabilities")),
                ("diagnostics", lambda: api_get(api_port, "/api/v1/diagnostics")),
                ("auth status", lambda: maintenance_get(api_port, "/api/v1/maintenance/auth")),
                ("mqtt status", lambda: maintenance_get(api_port, "/api/v1/maintenance/mqtt")),
                ("legacy mqtt status", lambda: maintenance_get(api_port, "/api/v1/maintenance/legacy-mqtt")),
                ("subscriptions", lambda: api_get(api_port, "/api/v1/events/subscriptions")),
                ("activations", lambda: api_get(api_port, "/api/v1/activations")),
                ("system metrics", lambda: api_get(api_port, "/api/v1/system/metrics")),
                (
                    "same auth config",
                    lambda: maintenance_post(
                        api_port,
                        "/api/v1/maintenance/auth",
                        {"noAuth": True},
                    ),
                ),
                (
                    "same mqtt config",
                    lambda: maintenance_post(
                        api_port,
                        "/api/v1/maintenance/mqtt",
                        {"enabled": False},
                    ),
                ),
            )
            for label, action in read_only_actions:
                action()
                diagnostics = api_get(api_port, "/api/v1/diagnostics")
                if diagnostics.get("agent_write_count") != expected_agent_writes:
                    raise AssertionError(f"{label} changed agent_write_count")
            setup_page = api_text(api_port, "/setup", authorized=False)
            if "C300X Agent Setup" not in setup_page:
                raise AssertionError("setup page was not served")
            for expected_text in (
                "API token for requests",
                "Maintenance token for requests",
                "enter token if configured",
                "d.api_token_configured",
                "overflow-wrap:anywhere",
                "JSON.stringify(JSON.parse(t),null,2)",
                "API listen host",
                "Save config",
                "Saving this option does not change firewall rules",
                "Allows temporary setup without Bearer auth",
                "Media starts only when requested",
                "Publishes CPU, memory, load, and temperature only when HA subscribes",
                "Internal UI port",
                "127.0.0.1 only",
                "GET /api/v1/maintenance/auth",
                "POST /api/v1/maintenance/firewall/actions/apply",
                "GET /api/v1/maintenance/ipv6-firewall",
                "POST /api/v1/maintenance/ipv6-firewall/actions/apply",
                "POST /api/v1/maintenance/qml-patch/actions/apply",
                "DELETE /api/v1/events/subscriptions/{id}",
                "GET /api/v1/memos/voice/{id}/audio",
            ):
                if expected_text not in setup_page:
                    raise AssertionError(f"setup page missing {expected_text!r}")
            unauthenticated_capabilities = api_get(
                api_port,
                "/api/v1/capabilities",
                authorized=False,
            )
            assert_json_field(unauthenticated_capabilities, "api_version", "1")
            no_auth_read = api_request(
                api_port,
                "GET",
                "/api/v1/maintenance/auth",
                None,
                authorized=False,
            )
            assert_json_field(no_auth_read, "noAuth", True)
            assert_absent(no_auth_read, "api_token")
            assert_absent(no_auth_read, "maintenance_token")
            assert_json_field(no_auth_read, "api_token_configured", True)
            assert_json_field(no_auth_read, "maintenance_token_configured", True)
            no_auth_firewall_status = api_request(
                api_port,
                "GET",
                "/api/v1/maintenance/firewall",
                None,
                authorized=False,
                expected_status=403,
            )
            assert_json_field(no_auth_firewall_status, "error", "maintenance_unauthorized")
            no_auth_config_update = api_request(
                api_port,
                "POST",
                "/api/v1/maintenance/auth",
                {"noAuth": False},
                authorized=False,
                expected_status=403,
            )
            assert_json_field(no_auth_config_update, "error", "maintenance_unauthorized")
            auth_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/auth",
                {"noAuth": False},
            )
            expected_agent_writes += 1
            assert_json_field(auth_status, "noAuth", False)
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/auth",
                    {"noAuth": False},
                ),
                "noAuth",
                False,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            disabled_setup = api_request(
                api_port,
                "GET",
                "/setup",
                None,
                authorized=False,
                expected_status=404,
            )
            assert_json_field(disabled_setup, "error", "setup_disabled")
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))
            if saved_config.get("api", {}).get("noAuth") is not False:
                raise AssertionError("noAuth config update was not persisted")
            if saved_config.get("api", {}).get("token") != "":
                raise AssertionError("env supplied API token was persisted to config")
            auth_status = api_request(
                api_port,
                "GET",
                "/api/v1/maintenance/auth",
                None,
                authorized=False,
                maintenance=True,
            )
            assert_json_field(auth_status, "noAuth", False)
            assert_json_field(auth_status, "api_token_configured", True)
            capabilities = api_get(api_port, "/api/v1/capabilities")
            assert_json_field(capabilities, "api_version", "1")
            assert_json_field(capabilities["device"], "model", "C300X")
            assert_json_field(capabilities["device"], "firmware", "1.7.19")
            assert_json_field(
                capabilities["capabilities"]["locks"]["locks"][0],
                "name",
                'Main "door"',
            )
            assert_json_field(
                capabilities["capabilities"]["answering_machine"]["messages"],
                "supported",
                True,
            )
            assert_json_field(
                capabilities["capabilities"]["answering_machine"]["messages"],
                "media",
                True,
            )
            assert_json_field(
                capabilities["capabilities"]["answering_machine"]["messages"],
                "delete",
                True,
            )
            assert_json_field(capabilities["capabilities"]["memos"], "supported", True)
            assert_json_field(capabilities["capabilities"]["memos"], "delete", True)
            assert_json_field(capabilities["capabilities"]["activations"], "supported", True)
            assert_json_field(capabilities["capabilities"]["activations"], "count", 5)
            assert_json_field(capabilities["capabilities"]["maintenance"], "qml_status", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "qml_patch", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "qml_core_patch", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "qml_core_restore", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "qml_restore", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "firewall_status", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "firewall_apply", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "firewall_restore", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "agent_remove", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "agent_restart", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "ipv6_firewall_status", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "ipv6_firewall_apply", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "ipv6_firewall_restore", True)
            assert_json_field(capabilities["capabilities"]["maintenance"], "gui_reload", True)
            assert_json_field(capabilities["capabilities"]["display_bridge"], "supported", True)
            assert_json_field(capabilities["capabilities"]["display_bridge"], "configurable", True)
            assert_json_field(capabilities["capabilities"]["diagnostics"], "supported", True)
            assert_json_field(capabilities["capabilities"]["diagnostics"], "runtime", True)
            assert_json_field(capabilities["capabilities"]["auth"], "configurable", True)
            remove_agent_result = api_request(
                api_port,
                "POST",
                "/api/v1/maintenance/agent/actions/remove",
                {"confirm": "remove_agent"},
                authorized=True,
                maintenance=True,
                expected_status=202,
            )
            assert_json_field(remove_agent_result, "action", "remove_agent")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if remove_agent_log.exists() and "remove" in remove_agent_log.read_text(
                    encoding="utf-8"
                ):
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("remove-agent maintenance script was not scheduled")
            auth_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/auth",
                {"videoEnabled": False},
            )
            expected_agent_writes += 1
            assert_json_field(auth_status, "restart_required", True)
            saved_config = json.loads(config_path.read_text(encoding="utf-8"))
            if saved_config.get("video", {}).get("enabled") is not False:
                raise AssertionError("restart-scoped video config was not persisted")
            if saved_config.get("api", {}).get("token") != "":
                raise AssertionError("env supplied API token leaked after unrelated config save")
            capabilities_after_pending_restart = api_get(api_port, "/api/v1/capabilities")
            assert_json_field(
                capabilities_after_pending_restart["capabilities"]["doorbell_video"],
                "supported",
                True,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            idle_bridge = api_get(api_port, "/api/v1/display-bridge")
            assert_json_field(idle_bridge, "enabled", True)
            assert_json_field(idle_bridge, "configured", False)
            assert_json_field(idle_bridge, "source", "none")
            disabled_bridge = api_post(
                api_port,
                "/api/v1/display-bridge",
                {"enabled": False},
            )
            assert_json_field(disabled_bridge, "configured", False)
            assert_json_field(disabled_bridge, "source", "runtime")
            ipv6_bridge = api_post(
                api_port,
                "/api/v1/display-bridge",
                {
                    "enabled": True,
                    "webhook_url": f"http://[::1]:{callback.server_address[1]}/display",
                    "shared_secret": "ipv6-display-secret",
                },
            )
            assert_json_field(ipv6_bridge, "configured", True)
            assert_json_field(ipv6_bridge, "source", "runtime")
            display_bridge = api_post(
                api_port,
                "/api/v1/display-bridge",
                {
                    "enabled": True,
                    "webhook_url": display_callback_url(callback),
                    "shared_secret": "display-secret",
                },
            )
            assert_json_field(display_bridge, "configured", True)
            assert_json_field(display_bridge, "source", "runtime")
            if not str(display_bridge.get("callback_hash", "")).startswith("fnv1a64:"):
                raise AssertionError("display bridge did not expose a callback hash")
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/display-bridge",
                    {
                        "enabled": True,
                        "webhook_url": display_callback_url(callback),
                        "shared_secret": "display-secret",
                    },
                ),
                "configured",
                True,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            ui_state = ui_get_json(ui_port, "/ui/state")
            assert_json_field(ui_state, "alarm_configured", True)
            if callback.requests[-1].get("secret") != "display-secret":
                raise AssertionError("display bridge secret was not forwarded")
            callback_seen = len(callback.requests)
            ui_action = ui_get_json(ui_port, "/ui/action?id=scene%3Aleave")
            assert_json_field(ui_action, "device_ui_enabled", True)
            action_callback = wait_for_callback_type(callback, "action", callback_seen)
            if action_callback["body"].get("action_id") != "scene:leave":
                raise AssertionError("encoded UI action id was not decoded")
            assert_json_field(api_get(api_port, "/api/v1/ringer"), "muted", False)
            assert_json_field(
                api_get(api_port, "/api/v1/smartphone-forwarding"),
                "mode",
                "blocked",
            )
            video = api_get(api_port, "/api/v1/video/doorbell/status")
            assert_json_field(video["bridge"], "ring_receiver_running", False)
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/smartphone-forwarding",
                    {"mode": "enabled"},
                ),
                "mode",
                "enabled",
            )
            assert_json_field(api_get(api_port, "/api/v1/answering-machine"), "enabled", False)
            qml_status = maintenance_get(api_port, "/api/v1/maintenance/qml-patch")
            assert_json_field(qml_status, "state", "original")
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/qml-patch/actions/apply-core",
                    {"confirm": "apply_qml_core_patch"},
                ),
                "core_state",
                "patched",
            )
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/qml-patch/actions/restore-core",
                    {"confirm": "restore_qml_core_patch"},
                ),
                "core_state",
                "original",
            )
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/qml-patch/actions/apply",
                    {"confirm": "apply_qml_patch"},
                ),
                "state",
                "patched",
            )
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/qml-patch/actions/restore",
                    {"confirm": "restore_qml_patch"},
                ),
                "state",
                "original",
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            expected_agent_writes += 4
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "qml_patch")
            assert_json_field(diagnostics, "qml_patch_last_action", "restore")
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/gui/actions/reload",
                    {"confirm": "reload_gui"},
                ),
                "action",
                "reload_gui",
            )
            firewall_status = maintenance_get(api_port, "/api/v1/maintenance/firewall")
            assert_json_field(firewall_status, "state", "original")
            firewall_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/firewall/actions/apply",
                {"confirm": "apply_firewall"},
            )
            expected_agent_writes += 1
            assert_json_field(firewall_status, "state", "patched")
            expected_firewall_content = (
                "#!/bin/sh\n"
                "# stock firewall\n"
                "\n"
                "# c300x-native-agent firewall begin\n"
                "# Managed by c300x-native-agent. Opens only the configured API port.\n"
                "if command -v iptables >/dev/null 2>&1; then\n"
                f"    if ! iptables -C INPUT -p tcp --dport {api_port} -j ACCEPT 2>/dev/null; then\n"
                f"        iptables -A INPUT -p tcp --dport {api_port} -j ACCEPT\n"
                "    fi\n"
                "fi\n"
                "# c300x-native-agent firewall end\n"
            )
            firewall_content = firewall_path.read_text(encoding="utf-8")
            if firewall_content != expected_firewall_content:
                raise AssertionError(
                    "firewall apply did not write the expected managed block:\n"
                    f"{firewall_content}"
                )
            if not firewall_backup_path.exists():
                raise AssertionError("firewall apply did not create one original backup")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "firewall")
            assert_json_field(diagnostics, "last_write_reason", "apply")
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/firewall/actions/apply",
                    {"confirm": "apply_firewall"},
                ),
                "changed_files",
                0,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            firewall_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/firewall/actions/restore",
                {"confirm": "restore_firewall"},
            )
            expected_agent_writes += 1
            assert_json_field(firewall_status, "state", "original")
            if "c300x-native-agent firewall begin" in firewall_path.read_text(
                encoding="utf-8"
            ):
                raise AssertionError("firewall restore left managed block behind")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "firewall")
            assert_json_field(diagnostics, "last_write_reason", "restore")
            ipv6_firewall_status = maintenance_get(
                api_port,
                "/api/v1/maintenance/ipv6-firewall",
            )
            assert_json_field(ipv6_firewall_status, "state", "original")
            assert_json_field(ipv6_firewall_status, "family", "ipv6")
            ipv6_firewall_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/ipv6-firewall/actions/apply",
                {"confirm": "apply_ipv6_firewall"},
            )
            expected_agent_writes += 1
            assert_json_field(ipv6_firewall_status, "state", "patched")
            assert_json_field(ipv6_firewall_status, "family", "ipv6")
            expected_ipv6_firewall_content = (
                "#!/bin/sh\n"
                "# stock ipv6 firewall\n"
                "\n"
                "# c300x-native-agent ipv6 firewall begin\n"
                "# Managed by c300x-native-agent. Opens IPv6 ICMP and the configured API port.\n"
                "if command -v ip6tables >/dev/null 2>&1; then\n"
                "    if ! ip6tables -C INPUT -p ipv6-icmp -j ACCEPT 2>/dev/null; then\n"
                "        ip6tables -I INPUT 1 -p ipv6-icmp -j ACCEPT\n"
                "    fi\n"
                f"    if ! ip6tables -C INPUT -p tcp --dport {api_port} -j ACCEPT 2>/dev/null; then\n"
                f"        ip6tables -I INPUT 1 -p tcp --dport {api_port} -j ACCEPT\n"
                "    fi\n"
                f"    if ! ip6tables -C INPUT -p tcp --sport {api_port} -j ACCEPT 2>/dev/null; then\n"
                f"        ip6tables -I INPUT 1 -p tcp --sport {api_port} -j ACCEPT\n"
                "    fi\n"
                "fi\n"
                "# c300x-native-agent ipv6 firewall end\n"
            )
            ipv6_firewall_content = ipv6_firewall_path.read_text(encoding="utf-8")
            if ipv6_firewall_content != expected_ipv6_firewall_content:
                raise AssertionError(
                    "IPv6 firewall apply did not write the expected managed block:\n"
                    f"{ipv6_firewall_content}"
                )
            if not ipv6_firewall_backup_path.exists():
                raise AssertionError("IPv6 firewall apply did not create one original backup")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "ipv6_firewall")
            assert_json_field(diagnostics, "last_write_reason", "apply")
            assert_json_field(
                maintenance_post(
                    api_port,
                    "/api/v1/maintenance/ipv6-firewall/actions/apply",
                    {"confirm": "apply_ipv6_firewall"},
                ),
                "changed_files",
                0,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            ipv6_firewall_status = maintenance_post(
                api_port,
                "/api/v1/maintenance/ipv6-firewall/actions/restore",
                {"confirm": "restore_ipv6_firewall"},
            )
            expected_agent_writes += 1
            assert_json_field(ipv6_firewall_status, "state", "original")
            if "c300x-native-agent ipv6 firewall begin" in ipv6_firewall_path.read_text(
                encoding="utf-8"
            ):
                raise AssertionError("IPv6 firewall restore left managed block behind")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "ipv6_firewall")
            assert_json_field(diagnostics, "last_write_reason", "restore")
            video = api_get(api_port, "/api/v1/video/doorbell/status")
            assert_json_field(video, "available", True)
            assert_json_field(video["bridge"], "running", True)
            assert_json_field(video["bridge"], "call_active", False)
            assert_json_field(video["bridge"], "media_active", False)
            assert_json_field(video["bridge"], "ring_receiver_running", True)
            assert_json_field(video["bridge"], "ring_registered", False)
            assert_json_field(video["bridge"], "last_error", None)
            rtsp_describe(rtsp_port, "/doorbell-video")
            assert_json_field(
                api_post(api_port, "/api/v1/video/doorbell/actions/activate", {}),
                "ok",
                True,
            )
            video = api_get(api_port, "/api/v1/video/doorbell/status")
            assert_json_field(video["bridge"], "running", True)
            assert_json_field(video["bridge"], "call_active", False)
            rtsp_describe(rtsp_port, "/doorbell-video")
            assert_json_field(
                api_post(api_port, "/api/v1/video/doorbell/actions/stop", {}),
                "ok",
                True,
            )
            video = api_get(api_port, "/api/v1/video/doorbell/status")
            assert_json_field(video["bridge"], "running", True)
            assert_json_field(video["bridge"], "call_active", False)
            assert_json_field(video["bridge"], "media_active", False)
            rtsp_describe(rtsp_port, "/doorbell-video")
            assert_json_field(video["bridge"], "rtp_packets", 0)
            assert_json_field(video["bridge"], "last_error", None)
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/smartphone-forwarding",
                    {"mode": "blocked"},
                ),
                "mode",
                "blocked",
            )
            video = api_get(api_port, "/api/v1/video/doorbell/status")
            assert_json_field(video["bridge"], "ring_receiver_running", False)
            metrics = api_get(api_port, "/api/v1/system/metrics")
            if int(metrics.get("cpu_count") or 0) < 1:
                raise AssertionError("system metrics did not expose cpu_count")
            cpu_usage = metrics.get("cpu_usage_percent")
            if cpu_usage is not None and (
                not isinstance(cpu_usage, (int, float)) or cpu_usage < 0
            ):
                raise AssertionError("system metrics cpu_usage_percent is not usable")
            for key in ("load_1m_percent", "load_5m_percent", "load_15m_percent"):
                value = metrics.get(key)
                if not isinstance(value, (int, float)) or value < 0:
                    raise AssertionError(f"system metrics {key} is not usable")
            memory_usage = metrics.get("memory_usage_percent")
            if memory_usage is not None and (
                not isinstance(memory_usage, (int, float)) or memory_usage < 0
            ):
                raise AssertionError("system metrics memory_usage_percent is not usable")
            if memory_usage is not None and int(metrics.get("memory_total_kb") or 0) <= 0:
                raise AssertionError("system metrics memory_total_kb is not usable")
            voicemail = api_get(api_port, "/api/v1/answering-machine/messages")
            assert_json_field(voicemail, "available", False)
            assert_json_field(voicemail, "total", 0)
            assert_json_field(voicemail, "unread", 0)
            memos = api_get(api_port, "/api/v1/memos")
            assert_json_field(memos, "total", 0)
            assert_json_field(
                api_post(api_port, "/api/v1/stair-light/actions/activate", {}),
                "address",
                "10",
            )
            assert_json_field(
                api_post(api_port, "/api/v1/locks/default/actions/unlock", {}),
                "name",
                'Main "door"',
            )
            activations = api_get(api_port, "/api/v1/activations")
            assert_json_field(activations, "supported", True)
            if len(activations.get("items", [])) != 5:
                raise AssertionError("activation discovery did not return configured and device items")
            assert_json_field(activations["items"][0], "id", "front_gate")
            assert_json_field(activations["items"][0], "addressMode", "manual")
            assert_json_field(activations["items"][0], "executable", True)
            assert_json_field(activations["items"][1], "id", "activation_id_0123456789abcdef01")
            assert_json_field(activations["items"][1], "addressMode", "manual")
            assert_json_field(activations["items"][1], "executable", True)
            assert_json_field(activations["items"][2], "id", "unknown_only")
            assert_json_field(activations["items"][2], "addressMode", "auto")
            assert_json_field(activations["items"][2], "executable", False)
            assert_json_field(activations["items"][3], "id", "device_lock_40")
            assert_json_field(activations["items"][3], "name", "Garden gate")
            assert_json_field(activations["items"][3], "source", "device")
            assert_json_field(activations["items"][3], "executable", True)
            assert_json_field(activations["items"][4], "id", "device_stair_42")
            assert_json_field(activations["items"][4], "name", "Path light")
            assert_json_field(activations["items"][4], "source", "device")
            assert_json_field(activations["items"][4], "executable", True)
            if any(
                item.get("name") == "Unsafe delete must not be imported"
                for item in activations.get("items", [])
            ):
                raise AssertionError("unsafe discovered OpenWebNet frame was imported")
            callback_seen = len(callback.requests)
            subscription = api_post(
                api_port,
                "/api/v1/events/subscriptions",
                {
                    "callback_url": callback_url(callback),
                    "token": "event-token",
                    "events": [
                        "agent.diagnostics_changed",
                        "stair_light.activated",
                        "activation.executed",
                        "doorbell.pressed",
                        "answering_machine.messages_changed",
                        "memos.changed",
                        "system.metrics_changed",
                    ],
                },
                expected_status=201,
            )
            if not subscription.get("subscription", {}).get("id"):
                raise AssertionError("subscription id missing")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            callback_seen = len(callback.requests)
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/activations/front_gate/actions/run",
                    {},
                ),
                "id",
                "front_gate",
            )
            activation_event = wait_for_callback_type(
                callback,
                "activation.executed",
                callback_seen,
            )
            assert_json_field(
                activation_event["body"].get("data", {}),
                "id",
                "front_gate",
            )
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/activations/activation_id_0123456789abcdef01/actions/run",
                    {},
                ),
                "id",
                "activation_id_0123456789abcdef01",
            )
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/activations/device_lock_40/actions/run",
                    {},
                ),
                "id",
                "device_lock_40",
            )
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/activations/device_stair_42/actions/run",
                    {},
                ),
                "id",
                "device_stair_42",
            )
            callback_seen = len(callback.requests)
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/events/subscriptions",
                    {
                        "callback_url": callback_url(callback),
                        "token": "event-token",
                        "events": [
                            "agent.diagnostics_changed",
                            "stair_light.activated",
                            "activation.executed",
                            "doorbell.pressed",
                            "answering_machine.messages_changed",
                            "memos.changed",
                            "system.metrics_changed",
                        ],
                    },
                ),
                "ok",
                True,
            )
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            replacement = api_post(
                api_port,
                "/api/v1/events/subscriptions",
                {
                    "callback_url": f"http://127.0.0.1:{callback.server_address[1]}/callback-after-ip-change",
                    "token": "event-token",
                    "events": [
                        "agent.diagnostics_changed",
                        "stair_light.activated",
                        "activation.executed",
                        "doorbell.pressed",
                        "answering_machine.messages_changed",
                        "memos.changed",
                        "system.metrics_changed",
                    ],
                },
                expected_status=201,
            )
            assert_json_field(replacement, "ok", True)
            subscriptions = api_get(api_port, "/api/v1/events/subscriptions")
            if len(subscriptions.get("subscriptions", [])) != 1:
                raise AssertionError("agent kept more than one event subscription")
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            metrics_event = wait_for_callback_type(
                callback,
                "system.metrics_changed",
                len(callback.requests),
                timeout=8,
            )
            metrics_payload = metrics_event["body"].get("data", {}).get("system_metrics")
            if not isinstance(metrics_payload, dict):
                raise AssertionError("system metrics event payload missing")
            for key in ("cpu_usage_percent", "memory_usage_percent"):
                if key not in metrics_payload:
                    raise AssertionError(f"system metrics event did not include {key}")
            callback_seen = len(callback.requests)
            send_udp_event(udp_port, "*8*21*10##")
            callback_event = wait_for_callback_type(
                callback,
                "stair_light.activated",
                callback_seen,
            )
            if callback_event["token"] != "event-token":
                raise AssertionError("callback token was not forwarded")
            if callback_event["body"].get("data", {}).get("address") != "10":
                raise AssertionError("stair light event address was not parsed cleanly")
            callback_seen = len(callback.requests)
            voicemail_ui_wait = start_ui_event_wait(ui_port, ui_revision(ui_port))
            write_voicemail_message(messages_root, "message_1", read=False, unix_time=1710000000)
            assert_ui_event_topic(voicemail_ui_wait, "answering_machine.messages")
            voicemail_created_event = wait_for_callback_type(
                callback,
                "answering_machine.messages_changed",
                callback_seen,
            )
            if voicemail_created_event["token"] != "event-token":
                raise AssertionError("voicemail callback token was not forwarded")
            voicemail = api_get(api_port, "/api/v1/answering-machine/messages")
            assert_json_field(voicemail, "available", True)
            assert_json_field(voicemail, "total", 1)
            assert_json_field(voicemail, "unread", 1)
            if not voicemail["messages"][0].get("has_video"):
                raise AssertionError("video message was not detected")
            if voicemail["messages"][0].get("media_mime_type") != "video/x-msvideo":
                raise AssertionError("video message media type was not exposed")
            video_body, video_content_type = api_get_raw(
                api_port,
                "/api/v1/answering-machine/messages/message_1/video",
            )
            if video_body != b"C300XTESTVIDEO" or video_content_type != "video/x-msvideo":
                raise AssertionError("video message media endpoint returned unexpected content")
            callback_seen = len(callback.requests)
            write_voicemail_message(messages_root, "message_1", read=True, unix_time=1710000000)
            voicemail_event = wait_for_callback_type(
                callback,
                "answering_machine.messages_changed",
                callback_seen,
                timeout=8,
            )
            if voicemail_event["token"] != "event-token":
                raise AssertionError("voicemail callback token was not forwarded")
            voicemail = api_get(api_port, "/api/v1/answering-machine/messages")
            assert_json_field(voicemail, "unread", 0)
            assert_json_field(voicemail, "read", 1)
            recent = api_get(api_port, "/api/v1/events/recent")
            if not any(event.get("type") == "stair_light.activated" for event in recent["events"]):
                raise AssertionError("recent events did not record stair light event")
            if not any(
                event.get("type") == "answering_machine.messages_changed"
                for event in recent["events"]
            ):
                raise AssertionError("recent events did not record voicemail change event")
            callback_seen = len(callback.requests)
            openwebnet.delete_paths["*8*94#1#0##"] = messages_root / "message_1"
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/answering-machine/messages/actions/delete",
                    {"id": "message_1"},
                ),
                "id",
                "message_1",
            )
            wait_for_callback_type(
                callback,
                "answering_machine.messages_changed",
                callback_seen,
            )
            if (messages_root / "message_1").exists():
                raise AssertionError("video message directory was not deleted")
            voicemail = api_get(api_port, "/api/v1/answering-machine/messages")
            assert_json_field(voicemail, "total", 0)
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            expected_agent_writes += 1
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "memo_delete")
            assert_json_field(diagnostics, "last_write_reason", "video_message")
            if "*8*21*10##" not in openwebnet.frames:
                raise AssertionError("stair light command was not sent")
            if "*8*19*20##" not in openwebnet.frames or "*8*20*20##" not in openwebnet.frames:
                raise AssertionError("door unlock command sequence was not sent")
            if "*8*19*30##" not in openwebnet.frames or "*8*20*30##" not in openwebnet.frames:
                raise AssertionError("device activation command sequence was not sent")
            if "*8*19*31##" not in openwebnet.frames or "*8*20*31##" not in openwebnet.frames:
                raise AssertionError("long-id activation command sequence was not sent")
            if "*8*19*40##" not in openwebnet.frames or "*8*20*40##" not in openwebnet.frames:
                raise AssertionError("discovered lock activation command sequence was not sent")
            if "*8*21*42##" not in openwebnet.frames:
                raise AssertionError("discovered stair-light activation command was not sent")
            if "*8*94#1#0##" not in openwebnet.frames:
                raise AssertionError("video message delete command was not sent")
            callback_seen = len(callback.requests)
            memo_ui_wait = start_ui_event_wait(ui_port, ui_revision(ui_port))
            created_memo = api_post(
                api_port,
                "/api/v1/memos/text/actions/create",
                {
                    "text_b64": base64.b64encode(
                        b'local "memo"\nsecond'
                    ).decode("ascii"),
                    "read": False,
                },
                expected_status=201,
            )
            assert_json_field(created_memo, "id", "text/memo_1")
            assert_ui_event_topic(memo_ui_wait, "memos")
            memo_event = wait_for_callback_type(callback, "memos.changed", callback_seen)
            if memo_event["token"] != "event-token":
                raise AssertionError("memo callback token was not forwarded")
            expected_agent_writes += 1
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_class", "memo_create")
            assert_json_field(diagnostics, "last_write_reason", "text")
            callback_seen = len(callback.requests)
            memo_ui_wait = start_ui_event_wait(ui_port, ui_revision(ui_port))
            write_memo(voice_memos_root, "memo_1", kind="voice", read=False, unix_time=1710000122)
            assert_ui_event_topic(memo_ui_wait, "memos")
            memo_event = wait_for_callback_type(callback, "memos.changed", callback_seen)
            if memo_event["token"] != "event-token":
                raise AssertionError("memo callback token was not forwarded")
            assert_process_cpu_below(process.pid, 50.0, "memo watch after create")
            memos = api_get(api_port, "/api/v1/memos")
            assert_json_field(memos, "total", 2)
            assert_json_field(memos, "text_total", 1)
            assert_json_field(memos, "voice_total", 1)
            ui_memos = ui_get(ui_port, "/ui/memos")
            assert_json_field(ui_memos, "text_total", 1)
            text_memos = [
                memo
                for memo in memos.get("memos", [])
                if isinstance(memo, dict) and memo.get("kind") == "text"
            ]
            if not text_memos or text_memos[0].get("text") != 'local "memo"\nsecond':
                raise AssertionError("text memo content was not exposed")
            callback_seen = len(callback.requests)
            memo_delete_ui_wait = start_ui_event_wait(ui_port, ui_revision(ui_port))
            openwebnet.delete_paths["*8*94#1#3##"] = text_memos_root / "memo_1"
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/memos/actions/delete",
                    {"id": text_memos[0]["id"]},
                ),
                "id",
                "text/memo_1",
            )
            assert_ui_event_topic(memo_delete_ui_wait, "memos")
            wait_for_callback_type(callback, "memos.changed", callback_seen)
            wait_for_callback_type(callback, "system.metrics_changed", callback_seen)
            assert_process_cpu_below(process.pid, 50.0, "memo watch after text delete")
            if (text_memos_root / "memo_1").exists():
                raise AssertionError("text memo directory was not deleted")
            if "*8*94#1#3##" not in openwebnet.frames:
                raise AssertionError("text memo delete command was not sent")
            if "*8*94#1#2##" in openwebnet.frames:
                raise AssertionError("voice memo delete command was sent for a text memo")
            memos = api_get(api_port, "/api/v1/memos")
            assert_json_field(memos, "total", 1)
            assert_json_field(memos, "text_total", 0)
            assert_json_field(memos, "voice_total", 1)
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            expected_agent_writes += 1
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_reason", "text")
            voice_memos = [
                memo
                for memo in memos.get("memos", [])
                if isinstance(memo, dict) and memo.get("kind") == "voice"
            ]
            if not voice_memos:
                raise AssertionError("voice memo was not exposed")
            if voice_memos[0].get("audio_mime_type") != "audio/wav":
                raise AssertionError("voice memo audio MIME type was not exposed")
            if voice_memos[0].get("audio_size") != 12:
                raise AssertionError("voice memo audio size was not exposed")
            audio_content, audio_type = api_get_raw(
                api_port,
                "/api/v1/memos/voice/memo_1/audio",
            )
            if audio_content != b"RIFF\x00\x00\x00\x00WAVE" or audio_type != "audio/wav":
                raise AssertionError("voice memo audio endpoint returned unexpected content")
            callback_seen = len(callback.requests)
            openwebnet.delete_paths["*8*94#1#2##"] = voice_memos_root / "memo_1"
            assert_json_field(
                api_post(
                    api_port,
                    "/api/v1/memos/actions/delete",
                    {"id": voice_memos[0]["id"]},
                ),
                "id",
                "voice/memo_1",
            )
            wait_for_callback_type(callback, "memos.changed", callback_seen)
            wait_for_callback_type(callback, "system.metrics_changed", callback_seen)
            assert_process_cpu_below(process.pid, 50.0, "memo watch after voice delete")
            if (voice_memos_root / "memo_1").exists():
                raise AssertionError("voice memo directory was not deleted")
            if "*8*94#1#2##" not in openwebnet.frames:
                raise AssertionError("voice memo delete command was not sent")
            memos = api_get(api_port, "/api/v1/memos")
            assert_json_field(memos, "total", 0)
            assert_json_field(memos, "voice_total", 0)
            diagnostics = api_get(api_port, "/api/v1/diagnostics")
            expected_agent_writes += 1
            assert_json_field(diagnostics, "agent_write_count", expected_agent_writes)
            assert_json_field(diagnostics, "last_write_reason", "voice")
            sys.stdout.write("native agent smoke passed\n")
            return 0
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)


def assert_sigterm_shutdown_exits_cleanly(
    binary: Path,
    openwebnet: OpenWebNetServer,
) -> None:
    api_port = free_tcp_port()
    ui_port = free_tcp_port()
    rtsp_port = free_tcp_port()
    config = {
        "listen": {
            "host": "127.0.0.1",
            "apiPort": api_port,
            "uiPort": ui_port,
            "allowLan": False,
        },
        "api": {"token": "", "noAuth": True},
        "openwebnet": {
            "host": "127.0.0.1",
            "port": openwebnet.server_address[1],
            "timeoutMs": 1000,
        },
        "maintenance": {"enabled": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False},
        "systemMetrics": {"enabled": False},
        "displayBridge": {"enabled": False},
        "video": {
            "enabled": True,
            "rtsp": {"port": rtsp_port, "rtpPortStart": 12000, "rtpPortCount": 4},
        },
    }
    with tempfile.TemporaryDirectory(prefix="c300x-sigterm-smoke-") as temp_dir:
        config_path = Path(temp_dir) / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        process = subprocess.Popen(
            [str(binary), "--config", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_health(api_port)
            process.terminate()
            process.wait(timeout=5)
            if process.returncode != 0:
                raise AssertionError(
                    f"SIGTERM shutdown did not exit cleanly: {process.returncode}"
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)


def assert_runtime_bridge_binds_ui_when_disabled(
    binary: Path,
    openwebnet: OpenWebNetServer,
    callback: CallbackServer,
) -> None:
    api_port = free_tcp_port()
    ui_port = free_tcp_port()
    config = {
        "listen": {
            "host": "127.0.0.1",
            "apiPort": api_port,
            "uiPort": ui_port,
            "allowLan": False,
        },
        "api": {"token": "", "noAuth": True},
        "openwebnet": {
            "host": "127.0.0.1",
            "port": openwebnet.server_address[1],
            "timeoutMs": 1000,
        },
        "maintenance": {"enabled": False},
        "events": {"udp": {"enabled": False}},
        "answeringMachine": {"messages": {"enabled": False}},
        "memos": {"enabled": False},
        "systemMetrics": {"enabled": False},
        "video": {"enabled": False},
        "displayBridge": {"enabled": False},
    }
    with tempfile.TemporaryDirectory(prefix="c300x-runtime-bridge-smoke-") as temp_dir:
        config_path = Path(temp_dir) / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        process = subprocess.Popen(
            [str(binary), "--config", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_health(api_port)
            bridge = api_request(
                api_port,
                "POST",
                "/api/v1/display-bridge",
                {
                    "enabled": True,
                    "webhook_url": display_callback_url(callback),
                    "shared_secret": "runtime-display-secret",
                },
                authorized=False,
            )
            assert_json_field(bridge, "configured", True)
            ui_state = ui_get_json(ui_port, "/ui/state")
            assert_json_field(ui_state, "device_ui_enabled", True)
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)


def reply_for_openwebnet_frame(server: OpenWebNetServer, frame: str) -> str:
    if frame == "*#8**33##":
        return "*#8**33*1##"
    if frame == "*#8**37##":
        return f"*#8**37*{server.smartphone_forwarding_code}##"
    for code in (0, 1, 2):
        if frame in (f"*#8**#37*{code}##", f"*#8**37*{code}##"):
            server.smartphone_forwarding_code = code
            return f"*#8**37*{code}##"
    if frame == "*#8**40##":
        return "*#8**40*0*1##"
    return "*#*1##"


def read_frame(sock: socket.socket) -> str:
    data = bytearray()
    while len(data) < 256:
        chunk = sock.recv(1)
        if not chunk:
            break
        data.extend(chunk)
        if data.endswith(b"##"):
            break
    return data.decode()


@contextlib.contextmanager
def managed_tcp_server(server: socketserver.BaseServer):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(api_port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            api_get(api_port, "/api/v1/health", authorized=False)
            return
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise AssertionError("native agent health endpoint did not become ready")


def api_get(api_port: int, path: str, *, authorized: bool = True) -> dict[str, Any]:
    return api_request(api_port, "GET", path, None, authorized=authorized)


def api_text(api_port: int, path: str, *, authorized: bool = True) -> str:
    headers = {}
    if authorized:
        headers["Authorization"] = "Bearer " + TOKEN
    request = urllib.request.Request(
        f"http://127.0.0.1:{api_port}{path}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read().decode()


def ui_get(ui_port: int, path: str, *, timeout: float = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{ui_port}{path}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def ui_revision(ui_port: int) -> int:
    revision = ui_get(ui_port, "/ui/events/status").get("revision")
    if not isinstance(revision, int):
        raise AssertionError("UI event revision missing")
    return revision


def start_ui_event_wait(ui_port: int, revision: int) -> tuple[threading.Thread, dict[str, Any]]:
    result: dict[str, Any] = {}

    def wait() -> None:
        try:
            result["event"] = ui_get(ui_port, f"/ui/events/next?since={revision}", timeout=8)
        except BaseException as exc:  # noqa: BLE001 - test helper preserves the failure.
            result["error"] = exc

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    return thread, result


def assert_ui_event_topic(waiter: tuple[threading.Thread, dict[str, Any]], topic: str) -> None:
    thread, result = waiter
    thread.join(timeout=8)
    if thread.is_alive():
        raise AssertionError(f"UI event {topic!r} was not received")
    if "error" in result:
        raise AssertionError(f"UI event wait failed: {result['error']!r}")
    event = result.get("event")
    if not isinstance(event, dict):
        raise AssertionError("UI event response missing")
    assert_json_field(event, "changed", True)
    assert_json_field(event, "topic", topic)


def assert_aborted_clients_do_not_leak_fds(
    pid: int,
    api_port: int,
    ui_port: int,
) -> None:
    baseline = process_fd_count(pid)
    if baseline is None:
        return
    for _ in range(3):
        raw_http_request_and_close(
            api_port,
            "GET /api/v1/diagnostics HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Authorization: " + "Bearer " + TOKEN + "\r\n"
            "Connection: close\r\n"
            "\r\n",
        )

    ui_socket = socket.create_connection(("127.0.0.1", ui_port), timeout=3)
    try:
        ui_socket.sendall(
            b"GET /ui/events/next?since=999999 HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )
        time.sleep(0.1)
    finally:
        ui_socket.close()

    deadline = time.monotonic() + 2.0
    current = process_fd_count(pid)
    while current is not None and current > baseline and time.monotonic() < deadline:
        time.sleep(0.05)
        current = process_fd_count(pid)
    if current is not None and current > baseline:
        raise AssertionError(f"aborted clients leaked fds: before={baseline} after={current}")


def raw_http_request_and_close(port: int, request: str) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
        sock.sendall(request.encode())


def process_fd_count(pid: int) -> int | None:
    fd_path = Path(f"/proc/{pid}/fd")
    if not fd_path.exists():
        return None
    try:
        return len(list(fd_path.iterdir()))
    except OSError:
        return None


def api_get_raw(
    api_port: int,
    path: str,
    *,
    authorized: bool = True,
) -> tuple[bytes, str]:
    headers = {}
    if authorized:
        headers["Authorization"] = "Bearer " + TOKEN
    request = urllib.request.Request(
        f"http://127.0.0.1:{api_port}{path}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read(), response.headers.get_content_type()


def api_post(
    api_port: int,
    path: str,
    payload: dict[str, Any],
    *,
    expected_status: int = 200,
) -> dict[str, Any]:
    return api_request(
        api_port,
        "POST",
        path,
        payload,
        authorized=True,
        expected_status=expected_status,
    )


def maintenance_get(api_port: int, path: str) -> dict[str, Any]:
    return api_request(
        api_port,
        "GET",
        path,
        None,
        authorized=True,
        maintenance=True,
    )


def maintenance_post(
    api_port: int,
    path: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return api_request(
        api_port,
        "POST",
        path,
        payload,
        authorized=True,
        maintenance=True,
    )


def api_request(
    api_port: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    authorized: bool = True,
    maintenance: bool = False,
    expected_status: int = 200,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if authorized:
        headers["Authorization"] = "Bearer " + TOKEN
    if maintenance:
        headers["X-Bticino-C300X-Maintenance-Token"] = "maintenance-token"
    data = json.dumps(payload or {}).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{api_port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        response_ctx = urllib.request.urlopen(request, timeout=3)
    except urllib.error.HTTPError as err:
        if err.code != expected_status:
            raise
        return json.loads(err.read().decode())
    with response_ctx as response:
        if response.status != expected_status:
            raise AssertionError(f"{path} returned HTTP {response.status}")
        return json.loads(response.read().decode())


def assert_json_field(payload: dict[str, Any], field: str, expected: Any) -> None:
    if payload.get(field) != expected:
        raise AssertionError(f"{field}={payload.get(field)!r}, expected {expected!r}")


def assert_int_field_at_least(payload: dict[str, Any], field: str, minimum: int) -> None:
    value = payload.get(field)
    if not isinstance(value, int) or value < minimum:
        raise AssertionError(f"{field}={value!r}, expected integer >= {minimum}")


def assert_absent(payload: dict[str, Any], field: str) -> None:
    if field in payload:
        raise AssertionError(f"{field} must not be present")


def callback_url(callback: CallbackServer) -> str:
    return f"http://127.0.0.1:{callback.server_address[1]}/callback"


def display_callback_url(callback: CallbackServer) -> str:
    return f"http://127.0.0.1:{callback.server_address[1]}/display"


def ui_get_json(ui_port: int, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"http://127.0.0.1:{ui_port}{path}", timeout=3) as response:
        return json.loads(response.read().decode())


def send_udp_event(udp_port: int, frame: str) -> None:
    payload = b"\0" * 8 + b"OPEN\0" + b"\0" * 12 + frame.encode() + b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, ("127.0.0.1", udp_port))


def rtsp_describe(rtsp_port: int, path: str) -> None:
    request = (
        f"DESCRIBE rtsp://127.0.0.1:{rtsp_port}{path} RTSP/1.0\r\n"
        "CSeq: 1\r\n"
        "Accept: application/sdp\r\n"
        "\r\n"
    ).encode()
    with socket.create_connection(("127.0.0.1", rtsp_port), timeout=3) as sock:
        sock.sendall(request)
        response = sock.recv(4096)
    if b"RTSP/1.0 200" not in response:
        raise AssertionError("RTSP DESCRIBE did not return 200 OK")


def wait_for_callback(callback: CallbackServer) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if callback.requests:
            return callback.requests[-1]
        time.sleep(0.05)
    raise AssertionError("callback event was not received")


def assert_process_cpu_below(pid: int, max_percent: float, label: str) -> None:
    cpu_percent = process_cpu_percent(pid, seconds=1.0)
    if cpu_percent is not None and cpu_percent > max_percent:
        raise AssertionError(f"{label} used {cpu_percent:.1f}% CPU")


def process_cpu_percent(pid: int, seconds: float) -> float | None:
    stat_path = Path("/proc/stat")
    proc_path = Path(f"/proc/{pid}/stat")
    if not stat_path.exists() or not proc_path.exists():
        return None
    cpu_count = os.cpu_count() or 1
    before_total = read_total_jiffies(stat_path)
    before_process = read_process_jiffies(proc_path)
    if before_total is None or before_process is None:
        return None
    time.sleep(seconds)
    after_total = read_total_jiffies(stat_path)
    after_process = read_process_jiffies(proc_path)
    if after_total is None or after_process is None or after_total <= before_total:
        return None
    return ((after_process - before_process) / (after_total - before_total)) * cpu_count * 100.0


def read_total_jiffies(path: Path) -> int | None:
    try:
        fields = path.read_text(encoding="utf-8").splitlines()[0].split()[1:]
        return sum(int(field) for field in fields)
    except (OSError, ValueError, IndexError):
        return None


def read_process_jiffies(path: Path) -> int | None:
    try:
        fields = path.read_text(encoding="utf-8").split()
        return int(fields[13]) + int(fields[14])
    except (OSError, ValueError, IndexError):
        return None


def wait_for_callback_type(
    callback: CallbackServer,
    event_type: str,
    start_index: int = 0,
    timeout: float = 5,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for request in callback.requests[start_index:]:
            body = request.get("body", {})
            if isinstance(body, dict) and body.get("type") == event_type:
                return request
        time.sleep(0.05)
    raise AssertionError(f"callback event {event_type!r} was not received")


def write_voicemail_message(
    messages_root: Path,
    message_id: str,
    *,
    read: bool,
    unix_time: int,
) -> None:
    message_dir = messages_root / message_id
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "msg_info.ini").write_text(
        "\n".join(
            [
                "[Message Information]",
                f"Read={'1' if read else '0'}",
                "Date=09/03/2024 16:02",
                f"UnixTime={unix_time}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (message_dir / "aswm.avi").write_bytes(b"C300XTESTVIDEO")


def write_memo(
    memos_root: Path,
    memo_id: str,
    *,
    kind: str,
    read: bool,
    unix_time: int,
) -> None:
    memo_dir = memos_root / memo_id
    memo_dir.mkdir(parents=True, exist_ok=True)
    if kind == "text":
        (memo_dir / "message.txt").write_text('local "memo"\nsecond\n', encoding="utf-8")
    elif kind == "voice":
        (memo_dir / "audio.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    (memo_dir / "msg_info.ini").write_text(
        "\n".join(
            [
                "[Message Information]",
                f"Read={'1' if read else '0'}",
                "Date=09/03/2024 16:02",
                f"UnixTime={unix_time}",
                "MediaType=1",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
