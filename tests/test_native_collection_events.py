"""Distinguish local collection availability from confirmed content changes."""

from __future__ import annotations

import ctypes
import json
import os
import select
import shutil
import signal
import socket
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
    api_request,
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
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}", "-j2", "all",
         "LDFLAGS=-pthread -ldl test/memo_led_scan_barrier.c -Wl,--wrap=eventfd_write"],
        check=True, capture_output=True, text=True,
    )
    return build / "host" / "c300x-agent-native"


@dataclass
class CollectionLab:
    api: int
    callback: CallbackServer
    roots: dict[str, Path]
    process: subprocess.Popen | None = None

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
            lab.process = process
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


def eventually(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.01)


@pytest.fixture
def led_runtime():
    with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
        yield Path(directory)


@pytest.mark.parametrize("fault", ["absent_led", "missing_store", "unsafe_dir", "symlink_marker"])
def test_unusable_led_never_claims_or_scans(collection_binary, tmp_path, led_runtime, fault):
    api, ui = free_tcp_ports(2)
    state = led_runtime / "state"
    state.mkdir()
    marker = state / "c300x-agent.memo-led.claim"
    led = tmp_path / "led_memo"
    led.mkdir()
    brightness = led / "brightness"
    if fault != "absent_led":
        brightness.write_text("0\n")
    (led / "trigger").write_text("[none]\n")
    (led / "max_brightness").write_text("255\n")
    decoy = led_runtime / "decoy"
    decoy.mkdir(mode=0o700)
    if fault == "missing_store":
        state.rmdir()
    if fault == "unsafe_dir":
        state.chmod(0o777)
    if fault == "symlink_marker":
        marker.symlink_to(decoy, target_is_directory=True)
    memos = tmp_path / "memos"
    memos.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
        "api": {"token": TOKEN}, "memos": {"enabled": False, "watch": False,
                                          "textRoot": str(memos), "voiceRoot": str(memos)},
        "events": {"udp": {"enabled": False}}, "mdns": {"enabled": False},
        "video": {"enabled": False}, "mqtt": {"enabled": False},
    }))
    proc = subprocess.Popen([str(collection_binary), "--config", str(config)], cwd=tmp_path,
                            env={**os.environ, "C300X_LED_CLASS_ROOT": str(tmp_path),
                                 "C300X_MEMO_LED_RUNTIME_DIR": str(state)})
    try:
        wait_for_health(api)
        api_post(api, "/api/v1/display-bridge", {
            "webhook_url": "http://127.0.0.1:1/webhook", "shared_secret": "secret",
        })
        # Observe actual opendir calls, independently of the brightness value.
        libc = ctypes.CDLL(None)
        watch = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        assert watch >= 0
        try:
            assert libc.inotify_add_watch(watch, os.fsencode(memos), 0x20) >= 0  # IN_OPEN
            for unread in (True, False, False):
                assert not api_get(api, "/api/v1/capabilities")["capabilities"]["memo_led"]
                api_post(api, "/api/v1/display-bridge/events", {
                    "topic": "notifications", "unread": unread,
                }, expected_status=202)
            assert not select.select([watch], [], [], 0)[0]
        finally:
            os.close(watch)
        if fault == "missing_store":
            state.mkdir()
            assert not api_get(api, "/api/v1/capabilities")["capabilities"]["memo_led"]
        if fault == "symlink_marker":
            assert marker.is_symlink() and decoy.is_dir()
        else:
            assert not marker.exists()
        if brightness.exists():
            assert brightness.read_text() == "0\n"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.parametrize("native_at_shutdown", [False, True])
def test_memo_led_coordination(collection_binary, tmp_path, native_at_shutdown, led_runtime):
    api, ui = free_tcp_ports(2)
    led = tmp_path / "led_memo"
    stores = tmp_path / "vendor" / "stores"
    stores.mkdir(parents=True)
    text, voice = stores / "text", stores / "voice"
    for directory in (led, text, voice):
        directory.mkdir()
    brightness, trigger = led / "brightness", led / "trigger"
    brightness.write_text("0\n")
    trigger.write_text("[none] timer\n")
    (led / "max_brightness").write_text("255\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "listen": {"host": "127.0.0.1", "apiPort": api, "uiPort": ui},
        "api": {"token": TOKEN}, "displayBridge": {"enabled": True},
        "events": {"udp": {"enabled": False}}, "mdns": {"enabled": False},
        "video": {"enabled": False}, "mqtt": {"enabled": False},
        "activations": {"autoDiscover": False},
        "memos": {"enabled": False, "watch": False, "textRoot": str(text), "voiceRoot": str(voice)},
    }))
    path = "/api/v1/display-bridge/events"

    def event(unread, topic="notifications", status=202):
        return api_post(api, path, {"topic": topic, "unread": unread}, expected_status=status)

    def expect(level):
        deadline = time.monotonic() + 2
        while brightness.read_text().strip() != str(level):
            assert time.monotonic() < deadline
            time.sleep(0.01)

    marker = led_runtime / "c300x-agent.memo-led.claim"

    def start():
        return subprocess.Popen([str(collection_binary), "--config", str(config)], cwd=tmp_path,
                                env={**os.environ, "C300X_LED_CLASS_ROOT": str(tmp_path),
                                     "C300X_MEMO_LED_RUNTIME_DIR": str(led_runtime)})

    def register():
        api_post(api, "/api/v1/display-bridge", {
            "webhook_url": "http://127.0.0.1:1/webhook", "shared_secret": "secret",
        })

    def tree_watched():
        needle = f" ino:{text.stat().st_ino:x} "
        for fd in Path(f"/proc/{proc.pid}/fdinfo").iterdir():
            try:
                if needle in fd.read_text():
                    return True
            except FileNotFoundError:
                continue
        return False

    proc = start()
    try:
        wait_for_health(api)
        assert api_get(api, "/api/v1/capabilities")["capabilities"]["memo_led"] is True
        led.rename(tmp_path / "absent")
        register()
        event(True)
        event(False)
        assert not marker.exists()
        (tmp_path / "absent").rename(led)
        api_request(api, "POST", path, {"topic": "notifications", "unread": True},
                    authorized=False, expected_status=401)
        event("true", status=400)
        event(True, topic="alarm", status=400)
        assert brightness.read_text() == "0\n"
        event(True, topic="display_bridge.state")
        expect(255)
        assert marker.is_dir() and marker.stat().st_mode & 0o777 == 0o700
        directory_stamp = led_runtime.stat().st_mtime_ns
        stamp = brightness.stat().st_mtime_ns
        event(True)
        api_post(api, path, {"topic": "notifications"}, expected_status=202)
        assert brightness.stat().st_mtime_ns == stamp
        assert led_runtime.stat().st_mtime_ns == directory_stamp
        assert not tree_watched()
        assert start().wait(timeout=5) == 2
        assert marker.stat().st_mode & 0o777 == 0o700
        expect(255)

        # A confirmed empty scan held off-loop cannot release a newer claim.
        barrier = tmp_path / "barrier"
        barrier.mkdir()
        (barrier / "hold").touch()
        event(False)
        eventually((barrier / "ready").exists)
        assert tree_watched()
        event(True)
        assert marker.stat().st_mode & 0o777 == 0o700
        (barrier / "hold").unlink()
        eventually(lambda: not tree_watched())
        expect(255)
        assert marker.is_dir()

        # Replacing an ancestor leaves the old parent and roots intact.
        # The old empty tree must not authorize clearing the replacement's LED.
        (barrier / "ready").unlink()
        (barrier / "hold").touch()
        event(False)
        eventually((barrier / "ready").exists)
        stores.parent.rename(tmp_path / "retired")
        text.mkdir(parents=True)
        voice.mkdir()
        write_memo(text, "replacement", kind="text", read=False, unix_time=1710000000)
        (barrier / "hold").unlink()
        eventually(lambda: not marker.exists())
        expect(255)
        shutil.rmtree(text / "replacement")
        event(True)

        # A vendor memo arriving after the snapshot invalidates its off result.
        (barrier / "ready").unlink()
        (barrier / "hold").touch()
        event(False)
        eventually((barrier / "ready").exists)
        write_memo(text, "late", kind="text", read=False, unix_time=1710000000)
        (barrier / "hold").unlink()
        eventually(lambda: not marker.exists())
        expect(255)
        shutil.rmtree(text / "late")
        event(True)

        # Firmware writes its own off edge after the native memo change.
        write_memo(text, "memo_1", kind="text", read=False, unix_time=1710000000)
        brightness.write_text("0\n")
        expect(255)
        event(False)
        expect(255)
        eventually(lambda: not marker.exists())
        shutil.rmtree(text / "memo_1")
        brightness.write_text("0\n")
        event(False)
        expect(0)

        # Without an HA claim the vendor updater owns both edges.
        for value in ("255\n", "0\n"):
            brightness.write_text(value)
            event(False)
            assert brightness.read_text() == value

        trigger.write_text("none [timer]\n")
        event(True)
        assert brightness.read_text() == "0\n"
        assert trigger.read_text() == "none [timer]\n"
        trigger.write_text("[none] timer\n")
        expect(255)
        # Do not clear until the native watcher sees conclusive metadata.
        item = voice / "memo_1"
        item.mkdir()
        info = item / "msg_info.ini"
        os.mkfifo(info)
        event(False)
        eventually(tree_watched)
        assert marker.stat().st_mode & 0o777 == 0o500
        # Unknown native state survives SIGKILL as pending, not HA unread.
        proc.kill()
        proc.wait(timeout=5)
        proc = start()
        wait_for_health(api)
        eventually(tree_watched)
        brightness.write_text("0\n")
        assert api_get(api, "/api/v1/capabilities")["capabilities"]["memo_led"]
        expect(0)
        brightness.write_text("255\n")
        # Neither symlinks nor oversized metadata authorize switching off.
        info.unlink()
        decoy = tmp_path / "read.ini"
        decoy.write_text("[Message Information]\nRead=1\n")
        info.symlink_to(decoy)
        expect(255)
        info.unlink()
        info.write_text(decoy.read_text() + "#" * 5000)
        expect(255)
        info.write_text(decoy.read_text())
        expect(0)
        eventually(lambda: not tree_watched())
        register()
        event(True)
        api_post(api, "/api/v1/display-bridge", {"enabled": False})
        expect(0)
        api_post(api, "/api/v1/display-bridge", {
            "webhook_url": "http://127.0.0.1:1/webhook", "shared_secret": "secret",
        })
        event(True)
        if native_at_shutdown:
            (item / "msg_info.ini").write_text("[Message Information]\nRead=0\n")
        expect(255)
        proc.kill()
        proc.wait(timeout=5)
        assert marker.is_dir()
        settings = json.loads(config.read_text())
        settings["displayBridge"]["enabled"] = False
        config.write_text(json.dumps(settings))
        proc = start()
        wait_for_health(api)
        # No runtime registration survives the crash. Disable alone releases.
        api_post(api, "/api/v1/display-bridge", {"enabled": False})
        expect(255 if native_at_shutdown else 0)
        eventually(lambda: not marker.exists())
        register()
        # A trigger takeover ends HA ownership even when memo metadata is unknown.
        event(True)
        trigger.write_text("none [timer]\n")
        (item / "msg_info.ini").unlink()
        event(False)
        assert not marker.exists()
        expect(255)
        trigger.write_text("[none] timer\n")
        (item / "msg_info.ini").write_text(f"[Message Information]\nRead={int(not native_at_shutdown)}\n")
        event(True)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    assert proc.returncode == 0
    expect(255 if native_at_shutdown else 0)


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


def test_a_list_read_does_not_swallow_the_change_event(collection_lab):
    """The list read refreshes the watches, which drops pending inotify
    events: the change they announced once never reached Home Assistant."""
    lab = collection_lab
    assert lab.process is not None
    with socket.create_connection(("127.0.0.1", lab.api), timeout=3) as client:
        time.sleep(0.2)
        start = len(lab.callback.requests)
        # The new message and the read reach the agent in one poll round;
        # the HTTP client is served before the inotify fd.
        os.kill(lab.process.pid, signal.SIGSTOP)
        try:
            lab.write("voicemail", "item_2")
            client.sendall(
                b"GET /api/v1/answering-machine/messages HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Authorization: Bearer " + TOKEN.encode() + b"\r\nConnection: close\r\n\r\n")
        finally:
            os.kill(lab.process.pid, signal.SIGCONT)
        assert client.recv(64).startswith(b"HTTP/1.1 200")
    event = lab.event("voicemail", start)
    assert event["snapshot"] is False
    assert collection_data(event, "voicemail")["total"] == 2
