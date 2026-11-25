"""The agent's firewall restore gives back the vendor file byte for byte."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("sanitize", [False, True], ids=["host", "asan-ubsan"])
def test_firewall_restore_keeps_the_vendor_blank_lines(tmp_path: Path, sanitize: bool) -> None:
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "firewall-restore"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else []
    include = os.environ.get("CURL_INCLUDE_DIR")
    if include:
        flags += ["-idirafter", include]
    sources = sorted(str(path) for path in (native / "src").glob("*.c")
                     if path.name not in {"http.c", "main.c"})
    build = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(native / "test/firewall_restore_test.c"), *sources, "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    work = tmp_path / "work"
    work.mkdir()

    result = subprocess.run([str(binary), str(work)], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr

    # The restore run above leaves its firewall file (work/iptables) at the
    # vendor's read-only mode; the command stubs get a directory of their own.
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for family in ("iptables", "ip6tables"):
        stub = stubs / family
        stub.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$RULE_LOG"\n[ "$1" != "-C" ]\n')
        stub.chmod(0o700)
    log = work / "rules"
    for mode in ("disabled", "enabled"):
        log.write_text("")
        result = subprocess.run(
            [str(binary), str(stubs), mode], env={**os.environ, "RULE_LOG": str(log)},
            capture_output=True, text=True, check=True, timeout=10,
        )
        for rules in (result.stdout, log.read_text()):
            for append in ("iptables -A INPUT", "ip6tables -I INPUT 1"):
                assert f"{append} -p tcp --dport 8080 -j ACCEPT" in rules
                for media in ("tcp --dport 7654", "udp --dport 40004"):
                    assert (f"{append} -p {media} -j ACCEPT" in rules) == (mode == "enabled")

def test_subscription_event_list_is_whole_or_refused(tmp_path: Path) -> None:
    """Past 24 types, the rest of a subscription was dropped silently."""
    native = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "subscription-events"
    flags = []
    include = os.environ.get("CURL_INCLUDE_DIR")
    if include:
        flags += ["-idirafter", include]
    sources = sorted(str(path) for path in (native / "src").glob("*.c")
                     if path.name not in {"http.c", "main.c"})
    build = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
         "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections", *flags,
         str(native / "test/subscription_events_test.c"), *sources, "-pthread", "-ldl", "-o", str(binary)],
        capture_output=True, text=True, timeout=120,
    )
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
