"""Conservative release decisions from the off-loop native memo scan."""

import os
from pathlib import Path
import subprocess

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
