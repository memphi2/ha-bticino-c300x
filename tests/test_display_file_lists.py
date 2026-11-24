"""Every place that lists the display files names the same ones."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_every_list_of_the_display_files_names_the_same_files() -> None:
    from device_file_strip import DEVICE_SOURCE_FILES, EMBEDDED_SETTINGS

    from custom_components.bticino_c300x.device_installer import DISPLAY_FILES

    expected = set(DISPLAY_FILES)
    assert len(expected) == len(DISPLAY_FILES)
    standalone = expected.copy()
    expected.update(EMBEDDED_SETTINGS)
    assert set(DEVICE_SOURCE_FILES) == expected

    script = (ROOT / "native_agent/scripts/qml_patch.sh").read_text()
    generated = re.search(r'^GENERATED_FEATURE_FILES="([^"]+)"$', script, re.M)
    assert generated is not None
    core = re.search(r'^CORE_PATCH_FILES="([^"]+)"$', script, re.M)
    assert core is not None
    # The stock EventManager is patched, never shipped in the bundle.
    assert set(generated.group(1).split()) | (set(core.group(1).split()) - {"EventManager.qml"}) == expected

    update_paths = (ROOT / "native_agent/src/agent_update_paths.h").read_text()
    assert set(re.findall(r'"device_agent/qml/([^"]+)"', update_paths)) == standalone

    installer = (ROOT / "scripts/install_c300x_device.sh").read_text()
    assert set(re.findall(r'"\$QML_STAGE_DIR/([^"]+)"', installer)) == expected

    repo_files = (ROOT / "scripts/check_repo.py").read_text()
    assert set(re.findall(r'"device_qml/([^"]+\.(?:qml|js))"', repo_files)) | {
        "C300XRingerControl.qml"
    } >= expected
    assert {path.relative_to(ROOT / "device_qml").as_posix()
            for path in (ROOT / "device_qml").rglob("*") if path.suffix in {".qml", ".js"}} == expected


def test_manual_installer_preserves_javascript_subdirectory() -> None:
    source = (ROOT / "scripts/install_c300x_device.sh").read_text()
    groups = re.findall(r'scp_cmd \\\n(.*?)"\$REMOTE:\$REMOTE_DIR/qml/([^\"]*)"', source, re.S)
    assert len(groups) == 2
    for body, destination in groups:
        files = re.findall(r'"\$QML_STAGE_DIR/([^\"]+)"', body)
        assert files
        assert all(Path(name).parent == Path(destination or ".")
                   for name in files)
