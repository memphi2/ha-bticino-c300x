"""The Home Assistant address the station shows never carries path or query."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN = r"""
#include "ui_status.h"
#include <stdio.h>
int main(int argc, char **argv)
{
    char out[512];
    if (argc == 2) {
        int ok = c300x_ui_status_origin(argv[1], out, sizeof(out));
        printf("%d|%s", ok, out);
        return 0;
    }
    if (argc == 3) {
        char small[40];
        printf("%d", c300x_ui_status_json("2.9.2", "1.7.19", argv[1], 1, 0, 100, 160, small, sizeof(small)));
        return 0;
    }
    if (argc == 5) {
        if (!c300x_ui_status_json("2.9.2", argv[4], argv[1], 1, 0, 100, 160, out, sizeof(out))) return 1;
        fputs(out, stdout);
        return 0;
    }
    if (!c300x_ui_status_json("2.9.2", "1.7.19", argv[1], argv[2][0] == '1', argv[2][0] == 'd', 100, argv[3][0] == 'b' ? 40 : 160, out, sizeof(out))) return 1;
    fputs(out, stdout);
    return 0;
}
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler")
    work = tmp_path_factory.mktemp("ui-status")
    (work / "main.c").write_text(MAIN)
    subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "native_agent/src"),
                    str(work / "main.c"), str(ROOT / "native_agent/src/ui_status.c"),
                    str(ROOT / "native_agent/src/json_util.c"), "-ffunction-sections", "-Wl,--gc-sections",
                    "-o", str(work / "probe")],
                   check=True, capture_output=True, text=True, timeout=60)

    def run(*args):
        return subprocess.run([str(work / "probe"), *args], check=True, capture_output=True, text=True, timeout=10).stdout

    return run


@pytest.mark.parametrize(("url", "shown"), [
    ("http://192.0.2.10:8123/api/webhook/0123456789abcdef?token=secret#x", "http://192.0.2.10:8123"),
    ("https://ha.example.org/api/webhook/abc", "https://ha.example.org"),
    ("https://ha.example.org:443?x=1", "https://ha.example.org:443"),
    ("http://homeassistant.local:8123", "http://homeassistant.local:8123"),
    ("http://[fd00::10]:8123/api/webhook/abc", "http://[fd00::10]:8123"),
    ("http://user:password@ha.example.org:8123/api/webhook/abc", ""),
    ("http://ha.example.org\\@evil/api", ""),
    ("http://ha example/api", ""),
    ("http://ha.example.org%2Fapi%2Fwebhook%2Fabc", ""),
    ("ftp://ha.example.org/", ""),
    ("http:///api/webhook/abc", ""),
    ("http://" + "a" * 600 + "/api", ""),
    ("", ""),
])
def test_only_scheme_host_and_port_are_shown(probe, url, shown):
    ok, text = probe(url).split("|", 1)
    assert text == shown and ok == ("1" if shown else "0")
    for part in ("/api", "webhook", "?", "#", "@", "secret", "password", "0123456789abcdef"):
        assert part not in text


def test_status_body(probe):
    import json

    url = "https://ha.example.org:8123/api/webhook/abc?x=1"
    assert json.loads(probe(url, "1", "a")) == {
        "ok": True, "version": "2.9.2", "firmware": "1.7.19", "registered": True, "disabled": False,
        "home_assistant": "https://ha.example.org:8123", "last_contact_age": 60,
    }
    # A clock that stepped back never shows a negative age.
    assert json.loads(probe(url, "1", "b"))["last_contact_age"] == 0
    assert json.loads(probe(url, "0", "a"))["last_contact_age"] is None
    assert json.loads(probe("", "0", "a")) == {
        "ok": True, "version": "2.9.2", "firmware": "1.7.19", "registered": False, "disabled": False,
        "home_assistant": "", "last_contact_age": None,
    }
    # Switched off by Home Assistant is told apart from "never registered".
    assert json.loads(probe("", "d", "a"))["disabled"] is True
    # An address that is not shown still counts as registered.
    assert json.loads(probe("http://u:p@h/x", "1", "a"))["registered"] is True
    assert probe(url, "small") == "0"


def test_a_configured_firmware_value_cannot_break_the_status_body(probe):
    """`device_firmware` comes from the configuration and was printed unescaped."""
    import json

    url = "https://ha.example.org:8123/api/webhook/abc"
    body = json.loads(probe(url, "1", "a", '1.7"x\\y\n'))
    assert body["firmware"] == '1.7"x\\y\n' and body["ok"] is True and body["registered"] is True
    source = (ROOT / "native_agent/src/firmware_version.c").read_text(encoding="utf-8")
    resolver = source.rsplit("void resolve_device_firmware(", 1)[1].split("\n}", 1)[0]
    assert "firmware_version_is_safe(config->device_firmware, strlen(config->device_firmware))" in resolver
