from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_hacs_release.py"
STAGE_SCRIPT = ROOT / "scripts" / "stage_device_agent_bundle.py"


def _load_release_builder():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("build_hacs_release", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_bundle_stager():
    spec = importlib.util.spec_from_file_location("stage_device_agent_bundle", STAGE_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hacs_release_zip_uses_component_root_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = _load_release_builder()
    package_root = tmp_path / "package"
    output = tmp_path / "ha-bticino-c300x.zip"

    def stage_bundle_stub(component_dir: Path, *, version: str, skip_build: bool) -> None:
        assert version == "0.3.1"
        assert skip_build is True
        bundle = component_dir / "device_agent" / "bundle.json"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text("{}\n", encoding="utf-8")
        bootstrap = component_dir / "device_agent" / "scripts" / "bootstrap_firewall.sh"
        bootstrap.parent.mkdir(parents=True, exist_ok=True)
        bootstrap.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(builder, "PACKAGE_ROOT", package_root)
    monkeypatch.setattr(builder, "stage_bundle", stage_bundle_stub)

    builder._prepare_package("0.3.1")
    builder._write_zip(output)

    assert (package_root / "manifest.json").exists()
    assert not (package_root / "custom_components").exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert "manifest.json" in names
    assert "__init__.py" in names
    assert "device_agent/bundle.json" in names
    assert "device_agent/scripts/bootstrap_firewall.sh" in names
    assert not any(name.startswith("custom_components/") for name in names)


def test_staged_self_update_bundle_contains_agent_managed_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stager = _load_bundle_stager()
    component_dir = tmp_path / "bticino_c300x"
    agent_binary = tmp_path / "c300x-agent-native"
    version_file = tmp_path / "VERSION"
    agent_binary.write_bytes(b"agent")
    version_file.write_text("0.3.1\n", encoding="utf-8")
    monkeypatch.setattr(stager, "AGENT_BINARY", agent_binary)
    monkeypatch.setattr(stager, "AGENT_VERSION_FILE", version_file)

    stager.stage_bundle(component_dir, version="0.3.1", skip_build=True)

    bundle = json.loads(
        (component_dir / "device_agent" / "bundle.json").read_text(encoding="utf-8")
    )
    paths = {entry["path"] for entry in bundle["files"]}
    assert bundle["agent"] == "device_agent/armhf/c300x-agent-native"
    assert "device_agent/armhf/c300x-agent-native" in paths
    assert "device_agent/init/c300x-native-agent" not in paths
    assert "device_agent/scripts/qml_patch.sh" in paths
    assert "device_agent/scripts/remove_agent.sh" in paths
    assert "device_agent/scripts/bootstrap_firewall.sh" in paths


def test_native_self_update_apply_matches_staged_manifest_files() -> None:
    """The native apply list must cover every staged self-update file."""

    native_http = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    apply_files = native_http.split("static int apply_agent_update_files", 1)[1].split(
        "if (summary != NULL)",
        1,
    )[0]

    assert '"device_agent/armhf/c300x-agent-native"' in apply_files
    assert '"device_agent/scripts/qml_patch.sh"' in apply_files
    assert '"device_agent/scripts/remove_agent.sh"' in apply_files
    assert '"device_agent/scripts/bootstrap_firewall.sh"' in apply_files
    assert '"device_agent/init/c300x-native-agent"' not in apply_files
