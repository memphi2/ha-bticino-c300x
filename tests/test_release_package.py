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
    modes = {entry["path"]: entry["mode"] for entry in bundle["files"]}
    assert modes["device_agent/armhf/c300x-agent-native"] == "700"
    assert modes["device_agent/scripts/qml_patch.sh"] == "700"
    assert modes["device_agent/scripts/remove_agent.sh"] == "700"
    assert modes["device_agent/scripts/bootstrap_firewall.sh"] == "700"
    assert modes["device_agent/qml/Alarm.qml"] == "644"
    assert modes["device_agent/qml/HomeAssistant.qml"] == "644"
    assert modes["device_agent/qml/js/c300x_ha.js"] == "644"
    assert modes["device_agent/qml/js/c300x_i18n.js"] == "644"
    assert modes["device_agent/qml/js/c300x_memos.js"] == "644"


def test_stage_bundle_strips_elf_agent_binary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stager = _load_bundle_stager()
    component_dir = tmp_path / "bticino_c300x"
    agent_binary = tmp_path / "c300x-agent-native"
    version_file = tmp_path / "VERSION"
    strip_calls: list[list[str]] = []
    agent_binary.write_bytes(b"\x7fELFagent")
    version_file.write_text("0.3.1\n", encoding="utf-8")
    monkeypatch.setattr(stager, "AGENT_BINARY", agent_binary)
    monkeypatch.setattr(stager, "AGENT_VERSION_FILE", version_file)
    monkeypatch.setattr(stager, "_run", strip_calls.append)

    stager.stage_bundle(component_dir, version="0.3.1", skip_build=True)

    assert strip_calls == [
        [
            "arm-linux-gnueabihf-strip",
            "--strip-unneeded",
            str(component_dir / "device_agent/armhf/c300x-agent-native"),
        ]
    ]


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


def test_native_self_update_apply_repairs_existing_startup_link() -> None:
    """Self-update keeps legacy bundles compatible but still repairs rc startup."""

    native_http = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    apply_files = native_http.split("static int apply_agent_update_files", 1)[1].split(
        "static void handle_agent_update_apply",
        1,
    )[0]
    repair = native_http.split(
        "static int repair_agent_init_link_after_update",
        1,
    )[1].split("static int apply_agent_update_files", 1)[0]

    assert "repair_agent_init_link_after_update(summary)" in apply_files
    assert "agent_init_link_matches()" in repair
    assert "access(C300X_AGENT_INIT_SCRIPT, X_OK)" in repair
    assert "ensure_agent_init_link()" in repair


def test_native_agent_startup_link_check_accepts_relative_rc_links() -> None:
    """Stock rc links are usually relative but still point to the same init script."""

    native_http = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    link_check = native_http.split(
        "static int agent_init_link_matches(void)\n{",
        1,
    )[1].split("static int apply_agent_update_init_script", 1)[0]
    ensure_link = native_http.split(
        "static int ensure_agent_init_link",
        1,
    )[1].split("static int agent_init_link_matches", 1)[0]

    assert "realpath(C300X_AGENT_INIT_LINK, resolved)" in link_check
    assert "strcmp(resolved, C300X_AGENT_INIT_SCRIPT) == 0" in link_check
    assert "agent_init_link_matches()" in ensure_link
