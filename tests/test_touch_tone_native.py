"""Exercise the actual authenticated HTTP/GUI confirmation protocol locally."""

import http.client
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_native_ui_preferences import (
    AUTH_HEADERS,
    HEADER,
    file_state,
    request,
)
from test_native_ui_preferences import (
    lab as lab,
)
from test_native_ui_preferences import (
    native_preferences_binary as native_preferences_binary,
)

API = "/api/v1/display/touch-tone"
NEXT = "/ui/touch-tone/next"
STATE = "/ui/touch-tone/state"


def status(lab):
    return request(lab.api, headers=AUTH_HEADERS, path=API)[1]


def connect(lab, enabled=True, completed=None):
    connection = http.client.HTTPConnection("127.0.0.1", lab.ui, timeout=8)
    lab.sequence = getattr(lab, "sequence", 0) + 1
    query = f"?enabled={int(enabled)}&session={'b' * 32}&revision={lab.sequence}"
    if completed is not None:
        query += "&completed=" + completed
    connection.request("GET", NEXT + query, headers=HEADER)
    return connection


def wait_available(lab, enabled=True):
    for _ in range(100):
        data = status(lab)
        if data == {"ok": True, "available": True, "enabled": enabled}:
            return
        time.sleep(0.01)
    pytest.fail(f"GUI state was not published: {data}")


def report_body(lab, enabled):
    lab.sequence = getattr(lab, "sequence", 0) + 1
    return json.dumps({"enabled": enabled, "session": "b" * 32, "revision": lab.sequence})


def set_tone(lab, enabled):
    connection = http.client.HTTPConnection("127.0.0.1", lab.api, timeout=8)
    try:
        connection.request("POST", API, json.dumps({"enabled": enabled}), AUTH_HEADERS)
        response = connection.getresponse()
        return response.status, json.loads(response.read()), dict(response.getheaders())
    finally:
        connection.close()


def test_touch_tone_requires_gui_and_auth(lab):
    assert request(lab.api, path=API)[0] == 401
    assert request(lab.api, "POST", '{"enabled":false}', path=API)[0] == 401
    assert status(lab) == {"ok": True, "available": False, "enabled": None}
    assert set_tone(lab, False)[0] == 503


@pytest.mark.parametrize("enabled", [False, True])
def test_touch_tone_waits_for_matching_gui_ack_and_does_not_write_config(lab, enabled):
    before = file_state(lab.path)
    gui = connect(lab, not enabled)
    ack = None
    try:
        wait_available(lab, not enabled)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, enabled)
            command = json.loads(gui.getresponse().read())
            assert command["enabled"] is enabled
            assert command["expires"] > time.time() * 1000
            assert not response.done(), "do not report success before GUI readback"
            ack = connect(lab, enabled, command["id"])
            assert response.result(timeout=2)[:2] == (200, {"ok": True, "available": True, "enabled": enabled})
        assert status(lab)["enabled"] is enabled
        assert file_state(lab.path) == before
    finally:
        gui.close()
        if ack:
            ack.close()


def test_touch_tone_rejects_wrong_readback_and_accepts_later_command(lab):
    gui = connect(lab)
    ack = None
    try:
        wait_available(lab)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, False)
            command = json.loads(gui.getresponse().read())
            ack = connect(lab, True, command["id"])
            assert response.result(timeout=2)[0] == 409
            assert status(lab)["enabled"] is True
    finally:
        gui.close()
        if ack:
            ack.close()


def test_touch_tone_physical_changes_are_published_without_file_writes(lab):
    gui = connect(lab)
    try:
        wait_available(lab)
        before = file_state(lab.path)
        assert request(lab.ui, "POST", report_body(lab, False), HEADER, path=STATE)[0] == 200
        assert status(lab)["enabled"] is False
        assert file_state(lab.path) == before
        duplicate = connect(lab)
        try:
            assert duplicate.getresponse().status == 409
        finally:
            duplicate.close()
        assert status(lab)["enabled"] is False
    finally:
        gui.close()
    for _ in range(100):
        if status(lab)["available"] is False:
            break
        time.sleep(0.01)
    assert status(lab)["available"] is False


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://example.invalid", **HEADER}])
@pytest.mark.parametrize("path,method,body", [(NEXT + "?enabled=1", "GET", None),
                                             (STATE, "POST", '{"enabled":true}')])
def test_touch_tone_gui_routes_reject_browser_requests(lab, headers, path, method, body):
    assert request(lab.ui, method, body, headers, path=path)[0] == 403


@pytest.mark.parametrize("query", ["", "?enabled=true", "?enabled=0&completed=abc",
                                   "?enabled=1&completed=" + "a" * 32])
def test_touch_tone_rejects_invalid_and_stale_ack(lab, query):
    assert request(lab.ui, headers=HEADER, path=NEXT + query)[0] in (400, 409)
    assert status(lab)["available"] is False


@pytest.mark.parametrize("body", ['{}', '{"enabled":1}', '{"enabled":"false"}',
                                  '{"enabled":false} trailing', '[]'])
def test_touch_tone_requires_strict_boolean(lab, body):
    assert request(lab.api, "POST", body, AUTH_HEADERS, path=API)[0] == 400
    assert request(lab.ui, "POST", body, HEADER, path=STATE)[0] == 400


def test_touch_tone_missing_ack_times_out_and_late_ack_is_rejected(lab):
    gui = connect(lab)
    try:
        wait_available(lab)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, False)
            command = json.loads(gui.getresponse().read())
            assert response.result(timeout=7)[0] == 504
        late = connect(lab, False, command["id"])
        try:
            assert late.getresponse().status == 409
        finally:
            late.close()
        assert status(lab)["available"] is False
    finally:
        gui.close()


def test_touch_tone_busy_command_and_wrong_methods(lab):
    gui = connect(lab)
    ack = None
    try:
        wait_available(lab)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, False)
            command = json.loads(gui.getresponse().read())
            assert set_tone(lab, True)[0] == 409
            duplicate = connect(lab)
            try:
                assert duplicate.getresponse().status == 409
            finally:
                duplicate.close()
            ack = connect(lab, False, command["id"])
            assert response.result(timeout=2)[0] == 200
        assert request(lab.api, "PUT", headers=AUTH_HEADERS, path=API)[0] == 405
        assert request(lab.ui, "POST", '{}', HEADER, path=NEXT)[0] == 405
        assert request(lab.ui, headers=HEADER, path=STATE)[0] == 405
    finally:
        gui.close()
        if ack:
            ack.close()


def test_delayed_physical_report_cannot_replace_newer_command_ack(lab):
    gui = connect(lab)
    ack = None
    try:
        wait_available(lab)
        delayed = report_body(lab, True)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, False)
            command = json.loads(gui.getresponse().read())
            ack = connect(lab, False, command["id"])
            assert response.result(timeout=2)[0] == 200
        assert request(lab.ui, "POST", delayed, HEADER, path=STATE)[0] == 200
        assert status(lab)["enabled"] is False
        old_session = json.dumps({"enabled": True, "session": "c" * 32, "revision": 99})
        assert request(lab.ui, "POST", old_session, HEADER, path=STATE)[0] == 409
        assert status(lab)["enabled"] is False
    finally:
        gui.close()
        if ack:
            ack.close()


@pytest.mark.parametrize("newer", [False, True])
def test_newer_report_before_command_ack_keeps_latest_state(lab, newer):
    gui = connect(lab)
    ack = None
    try:
        wait_available(lab)
        with ThreadPoolExecutor() as executor:
            response = executor.submit(set_tone, lab, False)
            command = json.loads(gui.getresponse().read())
            lab.sequence = 3
            assert request(lab.ui, "POST", report_body(lab, newer), HEADER, path=STATE)[0] == 200
            lab.sequence = 1
            ack = connect(lab, False, command["id"])
            assert response.result(timeout=2)[0] == (409 if newer else 200)
        assert status(lab)["enabled"] is newer
    finally:
        gui.close()
        if ack:
            ack.close()
