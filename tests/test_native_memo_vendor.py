"""Memo and video message writes go through bt_answering_machine.

The station keeps the stored entries in lists in memory, filled from disk only
when it starts. It deletes an entry only when it is in that list and answers
any other delete with a NACK. A text memo is saved by the station: the GUI
writes message.txt into the records directory and sends *8*87#4*##; the
station picks the number, writes msg_info.ini and moves the file in.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socketserver
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pytest
from native_build import default_host_agent

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    free_tcp_ports,
    free_udp_port,
    managed_tcp_server,
    read_frame,
    send_udp_event,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]
ACK = "*#*1##"
NACK = "*#*0##"
DIRECTORIES = {0: ("messages", "message"), 2: ("memos_voice", "memo"), 3: ("memos_text", "memo")}


class StationHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        station = self.server
        assert isinstance(station, Station)
        self.request.settimeout(10)
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
    def __init__(self, store: Path) -> None:
        super().__init__(("127.0.0.1", 0), StationHandler)
        self.store = store
        self.frames: list[str] = []
        self.known: dict[int, set[int]] = {0: set(), 2: set(), 3: set()}
        self.busy = False

    def answer(self, frame: str) -> str:
        if frame.startswith("*8*94#"):
            number, directory = (int(part) for part in frame[len("*8*94#"):-2].split("#"))
            if number not in self.known.get(directory, set()):
                return NACK
            folder, prefix = DIRECTORIES[directory]
            shutil.rmtree(self.store / folder / f"{prefix}_{number}")
            self.known[directory].discard(number)
            return ACK
        if frame == "*#8**100#3##":
            if not self.known[3]:
                return NACK
            return "*#8**100#3" + "".join(f"*{n}" for n in sorted(self.known[3])) + "##" + ACK
        if frame == "*8*87#4*##":
            return self.save_text_memo()
        if frame.startswith("*#8**#101#3#") and frame.endswith("*1##"):
            number = int(frame[len("*#8**#101#3#") : -len("*1##")])
            info = self.store / "memos_text" / f"memo_{number}" / "msg_info.ini"
            info.write_text(info.read_text().replace("Read=0", "Read=1"))
            return f"*#8**101#3#{number}*1##" + ACK
        return ACK

    def save_text_memo(self) -> str:
        staged = self.store / "records" / "message.txt"
        if self.busy or not staged.is_file():
            return NACK
        number = next(n for n in range(1, 100) if n not in self.known[3])
        entry = self.store / "memos_text" / f"memo_{number}"
        entry.mkdir()
        (entry / "msg_info.ini").write_text(
            "[Message Information]\nDate=Tue, 24 Nov 2026 14:35:51 +0100\nMediaType=3\n"
            "EuAddr=memo\ncause=2\nStatus=0\nUnixTime=1795527351\nRead=0\nDuration=00\n"
        )
        shutil.move(staged, entry / "message.txt")
        self.known[3].add(number)
        return ACK


@dataclass
class Lab:
    station: Station
    store: Path
    api_port: int
    udp_port: int = 0

    def bus(self, frame: str, *, call: bool) -> None:
        """Send a door entry frame and wait until the agent took it in."""
        send_udp_event(self.udp_port, frame)
        deadline = time.monotonic() + 5
        while self.in_call() is not call:
            assert time.monotonic() < deadline, frame
            time.sleep(0.05)

    def in_call(self) -> bool:
        status = api_get(self.api_port, "/api/v1/video/doorbell/status")
        return status["bridge"]["external_media_active"]

    def post(self, path: str, body: dict) -> tuple[int, dict, float]:
        conn = HTTPConnection("127.0.0.1", self.api_port, timeout=15)
        started = time.monotonic()
        conn.request("POST", path, body=json.dumps(body),
                     headers={"Authorization": "Bearer " + TOKEN})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        return response.status, payload, time.monotonic() - started


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return default_host_agent(tmp_path_factory)


def write_entry(store: Path, directory: int, number: int, text: str | None = None) -> Path:
    folder, prefix = DIRECTORIES[directory]
    entry = store / folder / f"{prefix}_{number}"
    entry.mkdir(parents=True)
    (entry / "msg_info.ini").write_text(
        "[Message Information]\nDate=Tue, 24 Nov 2026 13:49:12 +0100\nMediaType=3\n"
        "EuAddr=memo\ncause=2\nStatus=0\nUnixTime=1795524552\nRead=0\nDuration=00\n")
    if text is not None:
        (entry / "message.txt").write_text(text)
    return entry


@pytest.fixture
def lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    yield from run_lab(binary, tmp_path, video=False)


@pytest.fixture
def video_lab(binary: Path, tmp_path: Path) -> Iterator[Lab]:
    """The agent with door video and bus events, as on a station with media set up."""
    yield from run_lab(binary, tmp_path, video=True)


def run_lab(binary: Path, tmp_path: Path, *, video: bool) -> Iterator[Lab]:
    store = tmp_path / "store"
    for folder, _prefix in DIRECTORIES.values():
        (store / folder).mkdir(parents=True)
    (store / "records").mkdir()
    with managed_tcp_server(Station(store)) as station:
        api, ui, rtsp = free_tcp_ports(3)
        udp = free_udp_port() if video else 0
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": station.server_address[1], "timeoutMs": 9000},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": True, "group": "239.255.76.67", "port": udp}
                       if video else {"enabled": False}},
            "answeringMachine": {"messages": {"enabled": True, "root": str(store / "messages"),
                                              "watch": True}},
            "memos": {"enabled": True, "textRoot": str(store / "memos_text"),
                      "voiceRoot": str(store / "memos_voice"), "watch": True,
                      "recordsDir": str(store / "records")},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": True, "rtsp": {"port": rtsp, "rtpPortStart": 14000, "rtpPortCount": 4}}
            if video else {"enabled": False},
            "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            try:
                wait_for_health(api)
                yield Lab(station, store, api, udp)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize(
    ("path", "entry_id", "directory", "error"),
    [
        ("/api/v1/memos/actions/delete", "text/memo_2", 3, "memo_delete_refused"),
        ("/api/v1/memos/actions/delete", "voice/memo_2", 2, "memo_delete_refused"),
        ("/api/v1/answering-machine/messages/actions/delete", "message_2", 0,
         "video_message_delete_refused"),
    ],
)
def test_a_delete_the_station_refuses_fails_at_once(
    lab: Lab, path: str, entry_id: str, directory: int, error: str,
) -> None:
    entry = write_entry(lab.store, directory, 2, "memo\n")
    status, body, elapsed = lab.post(path, {"id": entry_id})
    assert (status, body) == (502, {"ok": False, "error": error})
    # No wait for an entry that the station said it does not remove.
    assert elapsed < 2
    assert entry.is_dir()
    assert lab.station.frames == [f"*8*94#2#{directory}##"]


def test_a_delete_the_station_acknowledges_removes_the_entry(lab: Lab) -> None:
    entry = write_entry(lab.store, 3, 1, "memo\n")
    lab.station.known[3].add(1)
    status, body, _elapsed = lab.post("/api/v1/memos/actions/delete", {"id": "text/memo_1"})
    assert (status, body["deleted"]) == (200, True)
    assert not entry.exists()


CREATE = "/api/v1/memos/text/actions/create"
LIST = "*#8**100#3##"
SAVE = "*8*87#4*##"


def create_body(text: str, *, read: bool = False) -> dict:
    return {"text_b64": base64.b64encode(text.encode()).decode("ascii"), "read": read}


def test_a_text_memo_is_saved_by_the_station_and_can_be_deleted(lab: Lab) -> None:
    write_entry(lab.store, 3, 1, "stock\n")
    lab.station.known[3].add(1)

    status, body, _elapsed = lab.post(CREATE, create_body("hello\r\nworld"))

    assert (status, body) == (201, {"ok": True, "created": True, "id": "text/memo_2",
                                    "kind": "text", "read": False})
    # The save is the GUI's, followed by its list request, which also reaches the display.
    assert lab.station.frames == [LIST, SAVE, LIST]
    entry = lab.store / "memos_text" / "memo_2"
    assert (entry / "message.txt").read_text() == "hello\nworld"
    assert "EuAddr=memo" in (entry / "msg_info.ini").read_text()
    staged = (entry / "message.txt").stat()
    assert (staged.st_mode & 0o777, staged.st_uid) == (0o644, os.getuid())
    assert list((lab.store / "records").iterdir()) == []

    status, body, _elapsed = lab.post("/api/v1/memos/actions/delete", {"id": "text/memo_2"})
    assert (status, body["deleted"]) == (200, True)
    assert not entry.exists()


def test_a_text_memo_saved_as_read_is_marked_by_the_station(lab: Lab) -> None:
    status, body, _elapsed = lab.post(CREATE, create_body("seen", read=True))

    assert (status, body["id"], body["read"]) == (201, "text/memo_1", True)
    assert lab.station.frames == [LIST, SAVE, LIST, "*#8**#101#3#1*1##"]
    assert "Read=1" in (lab.store / "memos_text/memo_1/msg_info.ini").read_text()


def test_a_save_the_station_refuses_leaves_nothing_behind(lab: Lab) -> None:
    lab.station.busy = True

    status, body, _elapsed = lab.post(CREATE, create_body("later"))

    assert (status, body) == (502, {"ok": False, "error": "memo_create_refused"})
    assert lab.station.frames == [LIST, SAVE]
    # A message.txt left there would go into the next recording the station saves.
    assert list((lab.store / "records").iterdir()) == []
    assert list((lab.store / "memos_text").iterdir()) == []


def memo_frames(lab: Lab) -> list[str]:
    """The memo exchange, without the state reads an agent with video sends."""
    return [frame for frame in lab.station.frames if frame in (LIST, SAVE)]


def test_a_save_refused_during_a_call_says_the_station_is_busy(video_lab: Lab) -> None:
    lab = video_lab
    lab.station.busy = True

    # A ring answered on the station's display: bt_answering_machine only
    # saves a memo in its idle state and answers the save with a plain NACK.
    lab.bus("*8*2#1#4*21##", call=True)
    status, body, elapsed = lab.post(CREATE, create_body("during the call"))

    assert (status, body) == (409, {"ok": False, "error": "station_busy"})
    assert elapsed < 2
    # The station was asked and refused; the agent did not decide for it.
    assert memo_frames(lab) == [LIST, SAVE]
    assert list((lab.store / "records").iterdir()) == []
    assert list((lab.store / "memos_text").iterdir()) == []

    # The call ended: a refusal now has another reason and keeps its own error.
    lab.bus("*8*3#1#4*21##", call=False)
    status, body, _elapsed = lab.post(CREATE, create_body("after the call"))
    assert (status, body) == (502, {"ok": False, "error": "memo_create_refused"})

    lab.station.busy = False
    status, body, _elapsed = lab.post(CREATE, create_body("after the call"))
    assert (status, body["id"]) == (201, "text/memo_1")


def test_a_memo_the_station_saves_during_a_call_is_created(video_lab: Lab) -> None:
    # The agent's view of a call can outlast the call; the station decides.
    video_lab.bus("*8*2#1#4*21##", call=True)

    status, body, _elapsed = video_lab.post(CREATE, create_body("saved"))

    assert (status, body["id"]) == (201, "text/memo_1")
    assert memo_frames(video_lab) == [LIST, SAVE, LIST]


def test_a_name_planted_in_the_records_directory_is_not_followed(lab: Lab, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (lab.store / "records" / "message.txt").symlink_to(target)

    status, _body, _elapsed = lab.post(CREATE, create_body("memo"))

    assert status == 201
    assert target.read_text() == "keep"
    assert (lab.store / "memos_text/memo_1/message.txt").read_text() == "memo"
