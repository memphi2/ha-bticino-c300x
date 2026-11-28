"""The C100X agent never drives a memo LED: none is proven on its hardware."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from native_agent.test.smoke import (
    TOKEN,
    api_get,
    api_post,
    free_tcp_ports,
    wait_for_health,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def c100x_binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("c100x-memo-led-build")
    marker = build / "BtClass100"
    marker.touch()
    flags = (
        "-std=c11 -O2 -Wall -Wextra -Werror -pedantic -D_DEFAULT_SOURCE "
        "-D_POSIX_C_SOURCE=200809L "
        f'-DC300X_C100X_DISPLAY_MARKER=\\"{marker}\\"'
    )
    subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), f"BUILD_DIR={build}",
         f"CFLAGS={flags}", "-j2", "all"],
        check=True, capture_output=True, text=True, timeout=600,
    )
    return build / "host/c300x-agent-native"


def test_c100x_neither_advertises_nor_lights_a_present_memo_led(c100x_binary, tmp_path):
    api, ui = free_tcp_ports(2)
    led = tmp_path / "led_memo"
    text, voice = tmp_path / "stores/text", tmp_path / "stores/voice"
    for directory in (led, text, voice):
        directory.mkdir(parents=True)
    # A C300X-style LED in sysfs: the C300X agent would claim and light it.
    (led / "brightness").write_text("0\n")
    (led / "trigger").write_text("[none] timer\n")
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
    with tempfile.TemporaryDirectory(dir="/dev/shm") as runtime:
        proc = subprocess.Popen(
            [str(c100x_binary), "--config", str(config)], cwd=tmp_path,
            env={**os.environ, "C300X_LED_CLASS_ROOT": str(tmp_path),
                 "C300X_MEMO_LED_RUNTIME_DIR": runtime},
        )
        try:
            wait_for_health(api)
            assert api_get(api, "/api/v1/capabilities")["capabilities"]["memo_led"] is False
            api_post(api, "/api/v1/display-bridge", {
                "webhook_url": "http://127.0.0.1:1/webhook", "shared_secret": "secret",
            })
            for topic in ("notifications", "display_bridge.state"):
                api_post(api, "/api/v1/display-bridge/events",
                         {"topic": topic, "unread": True}, expected_status=202)
            time.sleep(0.3)
            assert (led / "brightness").read_text() == "0\n"
            assert not (Path(runtime) / "c300x-agent.memo-led.claim").exists()
        finally:
            proc.terminate()
            proc.wait(timeout=5)
