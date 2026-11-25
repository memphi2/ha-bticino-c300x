"""Bounded Low choices change only configuration, never the media binary or LCD."""

import subprocess
from pathlib import Path

import pytest
from test_native_camera_quality import (
    CONFIRM,
    SETTINGS,
    STACK,
    Lab,
)
from test_native_camera_quality import (
    binary as binary,
)
from test_native_camera_quality import (
    lab as lab,
)
from test_native_camera_quality import (
    media_image as media_image,
)
from test_native_camera_quality import (
    qt5 as qt5,
)
from test_native_camera_quality import (
    reboot as reboot,
)


@pytest.mark.parametrize("qt5", [True])
@pytest.mark.parametrize("size", ["320x240", "480x288", "640x384", "720x432"])
def test_fw306_low_choices_preserve_viewport_binary_and_running_baseline(lab: Lab, size: str) -> None:
    target = Path(lab.env["C300X_MEDIA_GEOMETRY_TARGET"])
    original = target.read_bytes()
    body = lab.call({**CONFIRM, "size": size})
    width, height = size.split("x")
    assert lab.settings.read_text() == SETTINGS.replace(
        "WidthLow=400\nHeightLow=288", f"WidthLow={width}\nHeightLow={height}")
    assert lab.stack.read_text() == STACK and target.read_bytes() == original
    assert not Path(lab.env["C300X_MEDIA_GEOMETRY_BACKUP"]).exists()
    assert (body["size"], body["running_size"], body["restart_required"]) == (size, "400x288", True)
    lab.restart_agent()
    body = lab.call()
    assert (body["size"], body["running_size"], body["restart_required"]) == (size, "400x288", True)
    # Removal retains the factory dimensions, not the last selected size.
    subprocess.run([str(lab.binary), "--restore-media-patches"], env=lab.env,
                   cwd=lab.settings.parent, check=True, capture_output=True, timeout=10)
    assert lab.settings.read_text() == SETTINGS
    assert lab.stack.read_text() == STACK and target.read_bytes() == original


@pytest.mark.parametrize("qt5", [True])
@pytest.mark.parametrize("size", ["800x480", "960x576", "1920x1080", "481x288"])
def test_fw306_low_rejects_unbounded_and_high_patch_choices(lab: Lab, size: str) -> None:
    before = lab.settings.read_bytes()
    assert "960x576" not in lab.call()["sizes"]
    assert lab.call({**CONFIRM, "size": size}, status=400)["error"] == "camera_quality_invalid_size"
    assert lab.settings.read_bytes() == before


@pytest.mark.parametrize("size", ["320x240", "480x288", "640x384", "720x432"])
def test_low_additions_do_not_expand_legacy_high_choices(lab: Lab, size: str) -> None:
    assert size not in lab.call()["sizes"]
    lab.call({**CONFIRM, "size": size}, status=400)
    assert lab.settings.read_text() == SETTINGS
