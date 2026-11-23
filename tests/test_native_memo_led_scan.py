"""Conservative release decisions from the off-loop native memo scan."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def scanner(tmp_path_factory):
    native = Path(__file__).resolve().parents[1] / "native_agent"
    exe = tmp_path_factory.mktemp("memo-scan") / "scan"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread",
                    native / "test/memo_led_scan_test.c", native / "src/memo_led_scan.c",
                    "-o", exe], check=True)
    return exe


@pytest.mark.parametrize("fault", [
    "fifo", "file_link", "entry_link", "root_link", "ancestor_link", "oversize",
    "ambiguous", "missing", "directory_budget", "valid",
])
def test_bounded_regular_metadata(scanner, tmp_path, fault):
    store = tmp_path / "stores"
    text, voice = store / "text", store / "voice"
    entry = text / "memo_1"
    entry.mkdir(parents=True)
    voice.mkdir()
    data = "[Message Information]\nRead=1\n"
    info = entry / "msg_info.ini"
    if fault == "fifo":
        os.mkfifo(info)
    elif fault == "file_link":
        (store / "decoy").write_text(data)
        info.symlink_to(store / "decoy")
    elif fault == "oversize":
        info.write_text(data + "#" * 4096)
    elif fault == "ambiguous":
        info.write_text(data + "Read=0\n")
    elif fault == "directory_budget":
        info.write_text(data)
        for i in range(513):
            (text / f"extra{i}").touch()
    elif fault != "missing":
        info.write_text(data)
        path = {"entry_link": entry, "root_link": text, "ancestor_link": store}.get(fault)
        if path:
            moved = path.rename(tmp_path / "moved")
            path.symlink_to(moved, target_is_directory=True)

    def result():
        return int(subprocess.check_output([scanner, text, voice], timeout=4))

    assert result() == (0 if fault == "valid" else -1)
    if fault == "valid":
        info.write_text(data.replace("Read=1", "Read=0"))
        assert result() == 1


@pytest.mark.parametrize("missing", ["text", "voice", "both", "ancestor"])
def test_a_memo_store_that_does_not_exist_holds_no_unread_memo(scanner, tmp_path, missing):
    """A store the station has not created yet cannot hold an unread memo,
    so the scan must say "none" and let the LED claim go, not "unknown"."""

    store = tmp_path / "stores"
    text, voice = store / "text", store / "voice"
    if missing in ("text", "both"):
        voice.mkdir(parents=True)
    if missing in ("voice", "both"):
        text.mkdir(parents=True)
    if missing == "both":
        voice.rmdir()
    if missing == "ancestor":
        text = tmp_path / "absent" / "deeper" / "text"
        voice.mkdir(parents=True)

    def result():
        return int(subprocess.check_output([scanner, text, voice], timeout=4))

    assert result() == 0
    entry = (text if missing in ("text", "both", "ancestor") else voice) / "memo_1"
    entry.mkdir(parents=True)
    (entry / "msg_info.ini").write_text("[Message Information]\nRead=0\n")
    assert result() == 1


def test_an_unset_memo_store_stays_unknown(scanner, tmp_path):
    voice = tmp_path / "voice"
    voice.mkdir()
    assert int(subprocess.check_output([scanner, "", voice], timeout=4)) == -1
