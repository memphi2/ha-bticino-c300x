"""Distinguish local collection availability from confirmed content changes."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    CallbackServer,
    api_get,
    api_post,
    assert_no_callback_type,
    callback_url,
    free_tcp_ports,
    managed_tcp_server,
    wait_for_callback_type,
    wait_for_health,
    write_memo,
    write_voicemail_message,
)

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("answering_machine.messages_changed", "memos.changed")


@pytest.fixture(scope="module")
def collection_binary(tmp_path_factory):
    build = tmp_path_factory.mktemp("collection-native-build")
    subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all"],
        check=True, capture_output=True, text=True,
    )
    return build / "host" / "c300x-agent-native"


@dataclass
class CollectionLab:
    api: int
    callback: CallbackServer
    roots: dict[str, Path]

    def subscribe(self, *, renewal=False):
        api_post(
            self.api, "/api/v1/events/subscriptions",
            {"callback_url": callback_url(self.callback), "token": "collection-test",
             "events": list(EVENTS)},
            expected_status=200 if renewal else 201,
        )

    def event(self, kind, start):
        event_type = EVENTS[0] if kind == "voicemail" else EVENTS[1]
        return wait_for_callback_type(self.callback, event_type, start)["body"]

    def write(self, kind, entry="item_1", *, read=False):
        # Publish complete entries atomically so assertions do not depend on
        # inotify coalescing several fixture-file writes into a single event.
        with tempfile.TemporaryDirectory(dir=self.roots[kind].parent) as directory:
            staging = Path(directory)
            if kind == "voicemail":
                write_voicemail_message(staging, entry, read=read, unix_time=1710000000)
            else:
                write_memo(staging, entry, kind=kind, read=read, unix_time=1710000000)
            (staging / entry).rename(self.roots[kind] / entry)

    def assert_quiet(self, start):
        for event_type in EVENTS:
            assert_no_callback_type(self.callback, event_type, start)


@pytest.fixture
def collection_lab(collection_binary, tmp_path, request):
    missing = getattr(request, "param", None)
    roots = {kind: tmp_path / kind for kind in ("voicemail", "text", "voice")}
    with managed_tcp_server(CallbackServer()) as callback:
        api, ui = free_tcp_ports(2)
        lab = CollectionLab(api, callback, roots)
        for kind, root in roots.items():
            if kind != missing:
                root.mkdir()
                lab.write(kind)
        config = {
            "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
            "api": {"token": TOKEN},
            "maintenance": {"enabled": False},
            "activations": {"enabled": False, "autoDiscover": False},
            "events": {"udp": {"enabled": False}},
            "answeringMachine": {"messages": {
                "enabled": True, "root": str(roots["voicemail"]), "watch": True,
            }},
            "memos": {"enabled": True, "textRoot": str(roots["text"]),
                      "voiceRoot": str(roots["voice"]), "watch": True},
            "systemMetrics": {"enabled": False},
            "video": {"enabled": False},
            "displayBridge": {"enabled": False},
            "mqtt": {"enabled": False},
            "mdns": {"enabled": False},
        }
        config_path = tmp_path / "agent.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with (tmp_path / "agent.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(collection_binary), "--config", str(config_path)],
                cwd=tmp_path, stdout=log, stderr=log,
            )
            try:
                wait_for_health(api)
                # Inotify must compare against the correctly parsed startup
                # baseline even before registration forces a fresh snapshot.
                for root in roots.values():
                    if root.exists():
                        (root / "item_1" / "msg_info.ini").touch()
                time.sleep(0.1)
                recent = api_get(api, "/api/v1/events/recent")
                assert not [event for event in recent["events"] if event["type"] in EVENTS]
                lab.subscribe()
                assert lab.event("voicemail", 0)["snapshot"] is True
                assert lab.event("text", 0)["snapshot"] is True
                lab.assert_quiet(2)
                yield lab
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def collection_data(event, kind):
    return event["data"]["voicemail" if kind == "voicemail" else "memos"]


@pytest.mark.parametrize("kind", ["voicemail", "text", "voice"])
def test_unavailable_and_unchanged_recovery_are_snapshots(collection_lab, kind):
    lab = collection_lab
    root = lab.roots[kind]
    saved = root.with_name(root.name + "-offline")
    start = len(lab.callback.requests)
    root.rename(saved)
    unavailable = lab.event(kind, start)
    assert unavailable["snapshot"] is True
    data = collection_data(unavailable, kind)
    assert data["available"] is (kind != "voicemail")
    assert data["total" if kind == "voicemail" else f"{kind}_total"] == 0
    # Registration while unavailable must not discard the last valid content.
    start = len(lab.callback.requests)
    lab.subscribe(renewal=True)
    assert lab.event("voicemail", start)["snapshot"] is True
    assert lab.event("text", start)["snapshot"] is True
    start = len(lab.callback.requests)
    saved.rename(root)
    recovered = lab.event(kind, start)
    assert recovered["snapshot"] is True
    assert collection_data(recovered, kind)["total" if kind == "voicemail" else f"{kind}_total"] == 1
    lab.assert_quiet(len(lab.callback.requests))


@pytest.mark.parametrize("kind", ["voicemail", "text", "voice"])
def test_actual_add_read_and_delete_remain_live(collection_lab, kind):
    lab = collection_lab
    start = len(lab.callback.requests)
    lab.write(kind, "item_2")
    assert lab.event(kind, start)["snapshot"] is False
    lab.assert_quiet(len(lab.callback.requests))
    start = len(lab.callback.requests)
    info = lab.roots[kind] / "item_2" / "msg_info.ini"
    info.write_text(info.read_text(encoding="utf-8").replace("Read=0", "Read=1"), encoding="utf-8")
    read_event = lab.event(kind, start)
    assert read_event["snapshot"] is False
    assert collection_data(read_event, kind)["read"] == 1
    lab.assert_quiet(len(lab.callback.requests))
    start = len(lab.callback.requests)
    shutil.rmtree(lab.roots[kind] / "item_2")
    assert lab.event(kind, start)["snapshot"] is False


@pytest.mark.parametrize("kind", ["voicemail", "text", "voice"])
def test_content_changed_during_outage_is_live_on_recovery(collection_lab, kind):
    lab = collection_lab
    root = lab.roots[kind]
    saved = root.with_name(root.name + "-offline")
    start = len(lab.callback.requests)
    root.rename(saved)
    assert lab.event(kind, start)["snapshot"] is True
    info = saved / "item_1" / "msg_info.ini"
    info.write_text(info.read_text(encoding="utf-8").replace("Read=0", "Read=1"), encoding="utf-8")
    start = len(lab.callback.requests)
    saved.rename(root)
    event = lab.event(kind, start)
    assert event["snapshot"] is False
    assert collection_data(event, kind)["read"] == 1


@pytest.mark.parametrize("collection_lab", ["voicemail", "text", "voice"], indirect=True)
def test_first_available_read_is_baseline(collection_lab):
    lab = collection_lab
    kind = next(kind for kind, root in lab.roots.items() if not root.exists())
    with tempfile.TemporaryDirectory(dir=lab.roots[kind].parent) as directory:
        staging = Path(directory) / "collection"
        staging.mkdir()
        if kind == "voicemail":
            write_voicemail_message(staging, "item_1", read=False, unix_time=1710000000)
        else:
            write_memo(staging, "item_1", kind=kind, read=False, unix_time=1710000000)
        start = len(lab.callback.requests)
        staging.rename(lab.roots[kind])
        event = lab.event(kind, start)
    assert event["snapshot"] is True
    assert collection_data(event, kind)["total" if kind == "voicemail" else f"{kind}_total"] == 1
    start = len(lab.callback.requests)
    lab.write(kind, "item_2")
    assert lab.event(kind, start)["snapshot"] is False


def test_missing_text_does_not_hide_voice_changes(collection_lab):
    lab = collection_lab
    start = len(lab.callback.requests)
    lab.roots["text"].rename(lab.roots["text"].with_name("text-offline"))
    assert lab.event("text", start)["snapshot"] is True
    start = len(lab.callback.requests)
    lab.write("voice", "item_2")
    event = lab.event("voice", start)
    assert event["snapshot"] is False
    assert event["data"]["memos"]["voice_total"] == 2
    assert event["data"]["memos"]["text_total"] == 0
