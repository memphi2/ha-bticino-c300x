"""Picture settings go through the station's own bus frames, as its own menu does.

The stand-in plays both vendor programs: bt_av_media applies *#7**#5/6/7*v##
to the running video and answers *#7**20## with all of its values, and only
while a video runs; bt_answering_machine keeps every change for the unit of
the running call (tvcc_settings.ini, section "TVCC <unit>"), which the
station applies again to every later video of that unit.
"""

from __future__ import annotations

import json
import socketserver
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    api_request,
    free_tcp_ports,
    managed_tcp_server,
    read_frame,
    wait_for_health,
)

NATIVE = Path(__file__).resolve().parents[1] / "native_agent"
PICTURE = "/api/v1/video/picture"
STATUS = "/api/v1/video/doorbell/status"
CAPABILITIES = "/api/v1/capabilities"
ACK = "*#*1##"
NACK = "*#*0##"
READ = "*#7**20##"
DIMENSIONS = {5: 0, 6: 1, 7: 2}


class StationHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        station = self.server
        assert isinstance(station, Station)
        self.request.settimeout(5)
        try:
            self.request.sendall(ACK.encode())
            if read_frame(self.request) != "*99*0##":
                return
            self.request.sendall(ACK.encode())
            while frame := read_frame(self.request):
                station.frames.append(frame)
                self.request.sendall(station.answer(frame).encode())
        except OSError:
            return


class Station(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), StationHandler)
        self.frames: list[str] = []
        # The unit whose video runs, or None; its values come from the store.
        self.unit: str | None = None
        self.store: dict[str, list[int]] = {}
        self.values = [40, 50, 60, 75, 50]
        self.ignore_writes = False
        self.refuse_writes = False
        self.status_override: str | None = None

    def start_video(self, unit: str) -> None:
        """A ring or a camera view: the station applies the unit's stored values."""
        self.unit = unit
        self.values = list(self.store.setdefault(unit, [40, 50, 60, 75, 50]))

    def end_video(self) -> None:
        self.unit = None

    def answer(self, frame: str) -> str:
        if frame == READ:
            if self.unit is None:
                return NACK
            if self.status_override is not None:
                return self.status_override + ACK
            return "*#7**20*" + "*".join(str(v) for v in self.values) + "##" + ACK
        if frame.startswith("*#7**#") and frame.endswith("##"):
            dimension, value = (int(part) for part in frame[6:-2].split("*"))
            if self.unit is None or self.refuse_writes or dimension not in DIMENSIONS:
                return NACK
            if not self.ignore_writes:
                self.values[DIMENSIONS[dimension]] = value
                self.store[self.unit][DIMENSIONS[dimension]] = value
            return ACK
        return NACK


@dataclass
class Lab:
    station: Station
    api: int
    workdir: Path

    def set_station(self, model: str, firmware: str) -> None:
        (self.workdir / "station").write_text(f"{model} {firmware}")

    def frames(self) -> list[str]:
        """The picture frames since the last call; the agent's own startup reads aside."""
        frames, self.station.frames[:] = list(self.station.frames), []
        return [frame for frame in frames if frame.startswith("*#7*")]


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("picture-http")
    ldflags = ("-pthread -ldl -Wl,--wrap=resolve_device_firmware,--wrap=c300x_device_model "
               f"{NATIVE}/test/picture_station_fixture.c")
    subprocess.run(["make", "-C", NATIVE, f"BUILD_DIR={build}", f"LDFLAGS={ldflags}", "-j4", "all"],
                   check=True, capture_output=True)
    return build / "host/c300x-agent-native"


@pytest.fixture
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    with managed_tcp_server(Station()) as station:
        api, ui, rtsp = free_tcp_ports(3)
        config = {"device": {"model": "C300X", "firmware": "1.7.19"},
                  "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui}, "api": {"token": TOKEN},
                  "openwebnet": {"host": "127.0.0.1", "port": station.server_address[1], "timeoutMs": 300},
                  "video": {"enabled": True, "rtsp": {"port": rtsp}}, "mdns": {"enabled": False},
                  "mqtt": {"enabled": False}, "activations": {"autoDiscover": False},
                  "events": {"udp": {"enabled": False}}}
        (tmp_path / "config.json").write_text(json.dumps(config))
        (tmp_path / "station").write_text("C300X 1.7.19")
        proc = subprocess.Popen([binary, "--config", tmp_path / "config.json"], cwd=tmp_path)
        try:
            wait_for_health(api)
            yield Lab(station, api, tmp_path)
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def picture(lab: Lab, control: str | None = None, value: int | None = None, status: int = 200) -> dict:
    if control is None:
        return api_request(lab.api, "GET", PICTURE, None, expected_status=status)
    return api_request(lab.api, "POST", PICTURE, {"control": control, "value": value}, expected_status=status)


def test_change_goes_through_the_station_frames_and_is_kept_per_unit(lab: Lab) -> None:
    lab.station.start_video("20")
    assert picture(lab) == {"ok": True, "brightness": 40, "contrast": 50, "saturation": 60}
    assert lab.frames() == [READ]
    assert picture(lab, "contrast", 70) == {"ok": True, "brightness": 40, "contrast": 70, "saturation": 60}
    # Read first (a video runs), one value only, then the station's own answer.
    assert lab.frames() == [READ, "*#7**#6*70##", READ]
    lab.station.end_video()

    # The next video of the same unit starts with the kept value; another unit keeps its own.
    lab.station.start_video("21")
    assert picture(lab)["contrast"] == 50
    assert picture(lab, "brightness", 0)["brightness"] == 0
    lab.station.end_video()
    lab.station.start_video("20")
    assert picture(lab) == {"ok": True, "brightness": 40, "contrast": 70, "saturation": 60}
    assert picture(lab, "saturation", 100)["saturation"] == 100
    assert lab.frames()[-2:] == ["*#7**#7*100##", READ]
    assert lab.station.store == {"20": [40, 70, 100, 75, 50], "21": [0, 50, 60, 75, 50]}


def test_nothing_is_written_without_a_running_video(lab: Lab) -> None:
    assert picture(lab, status=409) == {"error": "picture_controls_unavailable"}
    assert picture(lab, "brightness", 50, status=409) == {"error": "picture_controls_unavailable"}
    assert lab.frames() == [READ, READ]
    assert lab.station.store == {}


@pytest.mark.parametrize("fault", ["ignore_writes", "refuse_writes"])
def test_a_change_the_station_does_not_confirm_is_not_applied(lab: Lab, fault: str) -> None:
    lab.station.start_video("20")
    setattr(lab.station, fault, True)
    assert picture(lab, "brightness", 90, status=409) == {"error": "picture_not_applied"}
    assert lab.frames() == [READ, "*#7**#5*90##", READ]
    assert lab.station.store["20"][0] == 40


@pytest.mark.parametrize("status", [
    "*#7**20*40*50*60*75##", "*#7**20*40*50*101*75*50##", "*#7**20*40*-1*60*75*50##",
    "*#7**20*40*50*60*75*50*1##", "*#7**5*40##",
])
def test_an_unexpected_station_answer_reads_as_unavailable(lab: Lab, status: str) -> None:
    lab.station.start_video("20")
    lab.station.status_override = status
    assert picture(lab, status=409) == {"error": "picture_controls_unavailable"}
    assert picture(lab, "brightness", 50, status=409) == {"error": "picture_controls_unavailable"}
    assert "*#7**#5*50##" not in lab.frames()


def test_requests_are_validated_and_authorized_before_any_frame(lab: Lab) -> None:
    lab.station.start_video("20")
    api_request(lab.api, "POST", PICTURE, {"control": "brightness", "value": 70},
                authorized=False, expected_status=401)
    for body in ({"control": "gain", "value": 70}, {"control": "brightness", "value": 75},
                 {"control": "brightness", "value": 110}, {"control": "brightness"}):
        assert api_request(lab.api, "POST", PICTURE, body, expected_status=400) == {
            "error": "invalid_picture_control"}
    assert api_request(lab.api, "DELETE", PICTURE, None, expected_status=405) == {"error": "method_not_allowed"}
    assert lab.frames() == []


@pytest.mark.parametrize(("model", "firmware", "supported"), [
    ("C300X", "1.7.19", True), ("C300X", "2.0.2", True), ("C300X", "3.0.6", True),
    ("C100X", "1.5.8", True), ("C300X", "9.9.9", False), ("C100X", "1.7.19", False),
])
def test_support_follows_the_station_not_the_media(lab: Lab, model: str, firmware: str, supported: bool) -> None:
    lab.set_station(model, firmware)
    bridge = api_get(lab.api, STATUS)["bridge"]
    assert bridge["picture_controls_supported"] is supported
    assert bridge["picture_controls_scope"] == ("ring_and_on_demand" if supported else None)
    assert api_get(lab.api, CAPABILITIES)["capabilities"]["camera_picture"]["supported"] is supported
    lab.station.start_video("20")
    if supported:
        assert picture(lab, "contrast", 30)["contrast"] == 30
    else:
        assert picture(lab, "contrast", 30, status=409) == {"error": "picture_controls_unavailable"}
        assert lab.frames() == []
