"""RAM-only alert transport, using the existing isolated native HTTP fixture."""

import fcntl
import http.client
import json
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest
from test_native_ui_preferences import AUTH_HEADERS, file_state, request
from test_native_ui_preferences import lab as lab
from test_native_ui_preferences import (
    native_preferences_binary as native_preferences_binary,
)

API = "/api/v1/display/alert"
NEXT = "/ui/alerts/next"
GUI_HEADERS = {"X-C300X-GUI": "alerts-v1"}
BEARER_HEADERS = {"Authorization": AUTH_HEADERS["Authorization"]}
ROOT = Path(__file__).resolve().parents[1]


def payload(**updates):
    return {"id": "a" * 32, "notification_id": "notice_1-test", "revision": "b" * 32,
            "severity": "info", "title": "Title", "message": "Message",
            "wake_duration": 30, "sound_duration": 0, "expires_in": 3600, **updates}


def post(lab, data=None, headers=BEARER_HEADERS):
    return request(lab.api, "POST", json.dumps(payload() if data is None else data), headers, API)


def connect(lab):
    gui = http.client.HTTPConnection("127.0.0.1", lab.ui, timeout=2)
    gui.request("GET", NEXT, headers=GUI_HEADERS)
    assert request(lab.ui, path="/health")[0] == 200
    return gui


def test_auth_capability_and_no_listener(lab):
    assert post(lab, headers={})[0] == 401
    assert post(lab, headers={"Authorization": "Bearer wrong"})[0] == 401
    assert post(lab, headers={"X-Bticino-C300X-Maintenance-Token": "test-admin"})[0] == 401
    assert post(lab, headers={**BEARER_HEADERS, "X-Bticino-C300X-Maintenance-Token": "wrong"})[0] == 503
    assert post(lab)[:2] == (503, {"ok": False, "error": "display_alerts_gui_unavailable"})
    caps = request(lab.api, headers=AUTH_HEADERS, path="/api/v1/capabilities")[1]
    assert caps["capabilities"]["display_alerts"] is True
    assert request(lab.api, headers={**GUI_HEADERS, **AUTH_HEADERS}, path=NEXT)[0] == 501
    assert request(lab.ui, "POST", json.dumps(payload()), AUTH_HEADERS, API)[0] == 405


@pytest.mark.parametrize("severity", ["info", "warning", "error"])
@pytest.mark.parametrize("duration", [0, 300])
def test_delivery_is_transport_acceptance_with_explicit_bounds(lab, severity, duration):
    before = file_state(lab.path)
    gui = connect(lab)
    data = payload(severity=severity, wake_duration=duration, sound_duration=duration,
                   title="\U0001f4a1" * 80, message="\U0001f4a1" * 500)
    start = time.time() * 1000
    try:
        assert post(lab, data)[:2] == (200, {"ok": True, "accepted": True})
        response = gui.getresponse()
        assert response.status == 200
        assert response.getheader("Cache-Control") == "no-store"
        command = json.loads(response.read())
        assert {key: command[key] for key in data} == data
        assert command["remaining_ms"] == 5000
        assert int(start) + 5000 <= command["expires"] <= time.time() * 1000 + 5000
        assert command["message_expires"] - command["expires"] == 3595000
        assert post(lab, payload(id="c" * 32))[0] == 503
        assert file_state(lab.path) == before
        assert sorted(p.name for p in lab.path.parent.iterdir()) == ["agent.log", "config.json"]
    finally:
        gui.close()


INVALID = [(key, value) for key in ("wake_duration", "sound_duration")
           for value in (-1, 301, True, False, 1.0, "30", None)] + [
    ("expires_in", value) for value in (0, 604801, True, 1.0, "3600", None)
] + [("id", "A" * 32), ("id", "a" * 31), ("revision", "g" * 32),
     ("notification_id", "Upper"), ("notification_id", ""), ("notification_id", "a" * 65),
     ("notification_id", "has.dot"), ("severity", "critical"), ("severity", "INFO"),
     ("title", "\U0001f4a1" * 81), ("message", "\U0001f4a1" * 501),
     ("title", None), ("message", {}), ("unexpected", 1)]


@pytest.mark.parametrize("key,value", INVALID)
def test_strict_fields(lab, key, value):
    assert post(lab, payload(**{key: value}))[0] == 400


@pytest.mark.parametrize("key", list(payload()))
def test_all_fields_required(lab, key):
    data = payload()
    del data[key]
    assert post(lab, data)[0] == 400


@pytest.mark.parametrize("body", ["", "[]", "null", "{", "{} trailing",
    json.dumps(payload())[:-1] + ',"wake_duration":30}',
    json.dumps(payload())[:-1] + ',"\\u0069d":"' + "a" * 32 + '"}',
    json.dumps(payload(title="\ud800")), json.dumps(payload(title="\u0000")),
    json.dumps(payload()).replace('"Title"', '"\ufffd"').encode().replace(b"\xef\xbf\xbd", b"\xff"),
])
def test_malformed_json_and_duplicate_keys(lab, body):
    assert request(lab.api, "POST", body, AUTH_HEADERS, API)[0] == 400


def test_oversize_and_wrong_methods_leave_waiter_intact(lab):
    gui = connect(lab)
    try:
        assert request(lab.api, "POST", json.dumps(payload()) + " " * 7680, AUTH_HEADERS, API)[0] == 413
        body = json.dumps(payload()).ljust(7681)
        assert request(lab.api, "POST", body, AUTH_HEADERS, API)[:2] == (
            413, {"ok": False, "error": "display_alert_too_large"})
        assert request(lab.api, "GET", headers=AUTH_HEADERS, path=API)[0] == 405
        assert request(lab.api, "POST", json.dumps(payload()), AUTH_HEADERS, API + "?x=1")[0] == 400
        assert post(lab)[0] == 200
        assert json.loads(gui.getresponse().read())["id"] == "a" * 32
    finally:
        gui.close()


@pytest.mark.parametrize("headers", [{}, {"X-C300X-UI": "1"}, {"X-C300X-GUI": "alerts-v1x"},
                                      {**GUI_HEADERS, "Origin": "null"}, {**GUI_HEADERS, "Origin": ""}])
def test_gui_guards(lab, headers):
    assert request(lab.ui, headers=headers, path=NEXT)[0] == 403


def test_gui_rejects_nonloopback_source(lab):
    address = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _, name in socket.if_nameindex():
            if name == "lo":
                continue
            try:
                result = fcntl.ioctl(probe, 0x8915, struct.pack("256s", name.encode()[:15]))
                address = socket.inet_ntoa(result[20:24])
                break
            except OSError:
                continue
    if address is None:
        pytest.skip("No local non-loopback IPv4 interface")
    assert request(lab.ui, headers=GUI_HEADERS, path=NEXT, source=(address, 0))[0] == 403


@pytest.mark.parametrize("ttl", [1, 604800])
def test_message_expiry_separate_from_effect_delivery_deadline(lab, ttl):
    gui = connect(lab)
    try:
        assert post(lab, payload(expires_in=ttl, title="", message=""))[0] == 200
        command = json.loads(gui.getresponse().read())
        assert command["remaining_ms"] == min(ttl * 1000, 5000)
        assert command["message_expires"] - command["expires"] == ttl * 1000 - command["remaining_ms"]
    finally:
        gui.close()


@pytest.mark.parametrize("character,ascii_only", [("\u0001", True), ("\U0001f4a1", False)])
def test_worst_case_escaping_and_raw_utf8(lab, character, ascii_only):
    data = payload(title=character * 80, message=character * 500)
    gui = connect(lab)
    try:
        body = json.dumps(data, ensure_ascii=ascii_only).encode("utf-8")
        assert request(lab.api, "POST", body, AUTH_HEADERS, API)[0] == 200
        command = json.loads(gui.getresponse().read())
        assert {key: command[key] for key in data} == data
    finally:
        gui.close()


def test_poll_validation_busy_hangup_and_reconnect(lab):
    assert request(lab.ui, "POST", "{}", GUI_HEADERS, NEXT)[0] == 405
    assert request(lab.ui, headers=GUI_HEADERS, path=NEXT + "?ack=1")[0] == 400
    assert request(lab.ui, "GET", "{}", GUI_HEADERS, NEXT)[0] == 400
    gui = connect(lab)
    try:
        assert request(lab.ui, headers=GUI_HEADERS, path=NEXT)[0] == 409
        gui.sock.shutdown(socket.SHUT_RDWR)
        gui.close()
        assert post(lab)[0] == 503
        gui = connect(lab)
        assert post(lab)[0] == 200
        assert json.loads(gui.getresponse().read())["id"] == "a" * 32
    finally:
        gui.close()


def test_duplicate_never_replays_after_gui_restart(lab):
    gui = connect(lab)
    try:
        assert post(lab)[0] == 200
        gui.getresponse().read()
    finally:
        gui.close()
    assert post(lab)[:2] == (200, {"ok": True, "accepted": True})
    gui = connect(lab)
    try:
        data = payload()
        equivalent = json.dumps(dict(reversed(list(data.items()))), indent=2)
        assert request(lab.api, "POST", equivalent, AUTH_HEADERS, API)[0] == 200
        assert post(lab, payload(message="Changed"))[0] == 409
        assert post(lab, payload(id="c" * 32))[0] == 200
        assert json.loads(gui.getresponse().read())["id"] == "c" * 32
    finally:
        gui.close()


def test_idle_poll_and_shutdown_cleanup(lab):
    gui = connect(lab)
    try:
        # No periodic empty response, including beyond the delivery window.
        gui.sock.settimeout(5.2)
        with pytest.raises(TimeoutError):
            gui.sock.recv(1, socket.MSG_PEEK)
        lab.restart()
        assert gui.sock.recv(1) == b""
        assert post(lab)[0] == 503
    finally:
        gui.close()


@pytest.mark.parametrize("sanitized", [False, True], ids=["host", "asan-ubsan"])
def test_receipt_expiry_capacity_and_fd_ownership(tmp_path, sanitized):
    binary = tmp_path / "alerts-test"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"] if sanitized else []
    result = subprocess.run([
        "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-D_DEFAULT_SOURCE",
        "-D_POSIX_C_SOURCE=200809L", *flags, str(ROOT / "native_agent/test/display_alerts_test.c"),
        *(str(ROOT / f"native_agent/src/{name}.c") for name in
          ("display_alerts", "json_util", "json_parse", "sha256")), "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
