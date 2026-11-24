"""Memo and video message writes go through bt_answering_machine.

The station keeps the stored entries in lists in memory, filled from disk only
when it starts. It deletes an entry only when it is in that list and answers
any other delete with a NACK.
"""

from __future__ import annotations

import json
import shutil
import socketserver
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    free_tcp_ports,
    managed_tcp_server,
    read_frame,
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

    def answer(self, frame: str) -> str:
        if frame.startswith("*8*94#"):
            number, directory = (int(part) for part in frame[len("*8*94#"):-2].split("#"))
            if number not in self.known.get(directory, set()):
                return NACK
            folder, prefix = DIRECTORIES[directory]
            shutil.rmtree(self.store / folder / f"{prefix}_{number}")
            self.known[directory].discard(number)
            return ACK
        return ACK


@dataclass
class Lab:
    station: Station
    store: Path
    api_port: int

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
    directory = tmp_path_factory.mktemp("memo-vendor-build")
    subprocess.run(["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={directory}",
                    "-j2", "all"], check=True, capture_output=True, text=True)
    return directory / "host/c300x-agent-native"


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
    store = tmp_path / "store"
    for folder, _prefix in DIRECTORIES.values():
        (store / folder).mkdir(parents=True)
    (store / "records").mkdir()
    with managed_tcp_server(Station(store)) as station:
        api, ui = free_tcp_ports(2)
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
            "api": {"token": TOKEN},
            "openwebnet": {"host": "127.0.0.1", "port": station.server_address[1], "timeoutMs": 9000},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": False}},
            "answeringMachine": {"messages": {"enabled": True, "root": str(store / "messages"),
                                              "watch": True}},
            "memos": {"enabled": True, "textRoot": str(store / "memos_text"),
                      "voiceRoot": str(store / "memos_voice"), "watch": True},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": False}, "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False}, "mdns": {"enabled": False},
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with (tmp_path / "agent.log").open("w") as log:
            process = subprocess.Popen([str(binary), "--config", str(config_path)],
                                       stdout=log, stderr=log, cwd=tmp_path)
            try:
                wait_for_health(api)
                yield Lab(station, store, api)
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
