"""C100X must never enter the incompatible C300X speaker lifecycle."""

import base64
import subprocess
import time
from pathlib import Path

import pytest
from test_native_announce import ROOT, Lab, wav
from test_native_announce import lab as lab


@pytest.fixture(scope="module")
def binary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build = tmp_path_factory.mktemp("c100x-announce-build")
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
        check=True, capture_output=True, text=True, timeout=180,
    )
    return build / "host/c300x-agent-native"


def test_foreign_c300x_tools_do_not_advertise_c100x_speaker_support(lab: Lab) -> None:
    # All C300X tools/profile are executable/readable in this lab. Presence
    # must not substitute for a compatible backend on the detected model.
    assert lab.call()["supported"] is False
    for action, payload in (
        ("/audio", {"offset": 0, "data": base64.b64encode(wav()).decode()}),
        ("/actions/play", {"volume": 25}),
    ):
        assert lab.call(action, payload, status=409)["error"] == "announcement_unsupported"
    assert lab.log() == []


def test_leftover_upload_never_runs_c300x_cleanup_on_c100x(lab: Lab) -> None:
    assert lab.process is not None
    lab.process.terminate()
    lab.process.wait(timeout=5)
    # Match stock C100X: missing old DSP tool means unsupported even before
    # the model guard, but startup recovery used to bypass that capability.
    (lab.dir / "zl-tool").unlink()
    (lab.dir / "announce.wav").write_bytes(wav())
    lab.restart()
    assert lab.call()["supported"] is False
    assert not (lab.dir / "announce.wav").exists()
    # Let the former deferred cleanup complete, avoiding an orphan on the
    # intentionally failing baseline run as well as checking its writes.
    time.sleep(6.5)
    assert lab.log() == []
    assert lab.call()["busy"] is False
    lab.process.terminate()
    lab.process.wait(timeout=5)
    assert lab.log() == []
