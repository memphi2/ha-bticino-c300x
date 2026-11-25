"""Authenticated picture dispatch through the real HTTP loop and bounded video worker."""

import json
import subprocess
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    api_request,
    free_tcp_ports,
    wait_for_health,
)

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
PICTURE = "/api/v1/video/picture"
STATUS = "/api/v1/video/doorbell/status"
GUI = "/ui/ringer/next?picture=1"


@pytest.fixture(scope="module")
def binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("picture-http")
    ldflags = ("-pthread -ldl -Wl,--wrap=c300x_video_status,--wrap=picture_source_execute,--wrap=resolve_device_firmware,"
               "--wrap=c300x_device_model,--wrap=picture_source_supported "
               f"{NATIVE}/test/picture_http_fixture.c")
    subprocess.run(["make", "-C", NATIVE, f"BUILD_DIR={build}", f"LDFLAGS={ldflags}", "-j4", "all"],
                   check=True, capture_output=True)
    return build / "host/c300x-agent-native"


@pytest.fixture
def station(binary, tmp_path):
    api, ui, rtsp = free_tcp_ports(3)
    config = {"device": {"model": "C300X", "firmware": "1.7.19"},
              "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui}, "api": {"token": TOKEN},
              "video": {"enabled": True, "rtsp": {"port": rtsp}}, "mdns": {"enabled": False},
              "mqtt": {"enabled": False}, "activations": {"autoDiscover": False},
              "events": {"udp": {"enabled": False}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    proc = subprocess.Popen([binary, "--config", path], cwd=tmp_path)
    try:
        wait_for_health(api)
        yield api, ui
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_shared_scope_follows_active_session_and_auth(station, tmp_path):
    api, _ = station
    calls = tmp_path / "source-calls"
    session = tmp_path / "session"
    for state in ("idle", "home", "external"):
        session.write_text(f"{state} 1")
        assert api_get(api, STATUS)["bridge"]["picture_controls_scope"] is None
        assert not api_get(api, "/api/v1/capabilities")["capabilities"]["camera_picture"]["supported"]
    assert not calls.exists()
    for generation, kind in enumerate(("agent", "ring"), start=1):
        session.write_text(f"{kind} {generation}")
        api_request(api, "POST", PICTURE, {"control": "brightness", "value": 70},
                    authorized=False, expected_status=401)
        api_request(api, "POST", PICTURE, {"control": "gain", "value": 70}, expected_status=400)
        before = calls.read_text().splitlines() if calls.exists() else []
        assert before == (["read", "read", "contrast"] * (generation - 1))
        bridge = api_get(api, STATUS)["bridge"]
        assert bridge["picture_controls_supported"] and bridge["picture_controls_scope"] == "ring_and_on_demand"
        assert api_get(api, "/api/v1/capabilities")["capabilities"]["camera_picture"]["supported"]
        assert api_get(api, PICTURE)["saturation"] == 40
        assert api_request(api, "POST", PICTURE, {"control": "contrast", "value": 60}) == {
            "ok": True, "brightness": 20, "contrast": 60, "saturation": 40,
        }
        assert calls.read_text().splitlines() == before + ["read", "read", "contrast"]


def test_failed_write_never_reaches_gui_and_cannot_cross_sessions(station, tmp_path):
    api, ui = station
    gui = HTTPConnection("127.0.0.1", ui, timeout=3)
    pending = HTTPConnection("127.0.0.1", api, timeout=3)
    try:
        gui.request("GET", GUI, headers={"X-C300X-GUI": "ringer-v1"})
        api_get(ui, "/ui/events/status", authorized=False)
        session = tmp_path / "session"
        session.write_text("ring 1")
        assert api_get(api, STATUS)["bridge"]["picture_controls_scope"] == "ring_and_on_demand"
        payload = {"control": "brightness", "value": 50}
        fault = tmp_path / "not-applied"
        fault.touch()
        assert api_request(api, "POST", PICTURE, payload, expected_status=409)["error"] == "picture_not_applied"
        fault.unlink()
        assert api_get(api, STATUS)["bridge"]["picture_controls_scope"] == "ring_and_on_demand"
        assert (tmp_path / "source-calls").read_text().splitlines() == ["read", "brightness", "read"]
        hold = tmp_path / "hold"
        hold.touch()
        pending.request("POST", PICTURE, body=json.dumps(payload), headers={"Authorization": "Bearer " + TOKEN})
        calls = tmp_path / "source-calls"
        deadline = time.monotonic() + 1
        while calls.read_text().splitlines().count("brightness") < 2:
            assert time.monotonic() < deadline
            time.sleep(.005)
        # Other clients stay responsive; no stale picture write is queued.
        assert api_request(api, "POST", PICTURE, payload, expected_status=409)["error"] == "media_busy"
        session.write_text("ring 2")
        hold.unlink()
        result = pending.getresponse()
        assert result.status == 409 and json.loads(result.read())["error"] == "picture_controls_unavailable"
        # Same waiting GUI receives only the next, independently routed legacy read.
        (tmp_path / "unavailable").touch()
        assert api_get(api, STATUS)["bridge"]["picture_controls_scope"] == "ring"
        pending.request("GET", PICTURE, headers={"Authorization": "Bearer " + TOKEN})
        command = json.loads(gui.getresponse().read())
        assert command["picture"] == "read"
    finally:
        gui.close()
        pending.close()


def test_configured_version_cannot_enable_another_firmware(station, tmp_path):
    api, _ = station
    (tmp_path / "other-firmware").touch()
    (tmp_path / "session").write_text("agent 1")
    assert not api_get(api, STATUS)["bridge"]["picture_controls_supported"]
    api_request(api, "POST", PICTURE, {"control": "saturation", "value": 50}, expected_status=409)
    assert not (tmp_path / "source-calls").exists()


def test_the_runtime_model_picks_the_profile_not_the_configured_one(station, tmp_path):
    api, _ = station
    # The installer writes model C300X into the config on every station.
    (tmp_path / "c100x-station").touch()
    (tmp_path / "session").write_text("agent 1")
    assert api_get(api, STATUS)["bridge"]["picture_controls_supported"]
    assert api_request(api, "POST", PICTURE, {"control": "brightness", "value": 60})["brightness"] == 60
    assert (tmp_path / "supported-calls").read_text().splitlines() == ["C100X 1.5.8"]
    assert set((tmp_path / "profiles").read_text().split()) == {"2"}


def test_a_c300x_keeps_its_profile(station, tmp_path):
    api, _ = station
    (tmp_path / "session").write_text("agent 1")
    assert api_get(api, STATUS)["bridge"]["picture_controls_supported"]
    assert (tmp_path / "supported-calls").read_text().splitlines() == ["C300X 1.7.19"]
    assert set((tmp_path / "profiles").read_text().split()) == {"1"}
