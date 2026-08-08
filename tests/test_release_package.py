from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_hacs_release.py"
STAGE_SCRIPT = ROOT / "scripts" / "stage_device_agent_bundle.py"
RELEASE_ASSETS_SCRIPT = ROOT / "scripts" / "write_release_assets.py"
RELEASE_TAG_SCRIPT = ROOT / "scripts" / "check_release_tag.py"
PROJECT_VERSIONS_PATH = ROOT / "project-versions.json"
RESERVED_DEVICE_PATCH_PATHS = (
    "device_agent/patches/common.sh",
    "device_agent/patches/display_qml.sh",
    "device_agent/patches/firewall.sh",
    "device_agent/patches/legacy_mqtt.sh",
    "device_agent/patches/audio_codec.sh",
    "device_agent/patches/device_routing.sh",
)

# Scripts under scripts/ import each other and the shared manifest_version
# helper as plain top-level modules, matching how they resolve imports when
# run directly (python scripts/foo.py adds its own directory to sys.path).
sys.path.insert(0, str(ROOT / "scripts"))


def _load_release_builder():
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


def _load_release_assets():
    spec = importlib.util.spec_from_file_location("write_release_assets", RELEASE_ASSETS_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_release_tag_checker():
    spec = importlib.util.spec_from_file_location("check_release_tag", RELEASE_TAG_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
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
    for path in package_root.rglob("*"):
        if path.is_file():
            os.utime(path, (1_900_000_000, 1_900_000_000))
    second_output = tmp_path / "second-ha-bticino-c300x.zip"
    builder._write_zip(second_output)

    assert (package_root / "manifest.json").exists()
    assert not (package_root / "custom_components").exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        timestamps = {info.date_time for info in archive.infolist()}

    assert "manifest.json" in names
    assert "LICENSE" in names
    assert "NOTICE" in names
    assert "PRIVACY.md" in names
    assert "SECURITY.md" in names
    assert "docs/legal.md" in names
    assert "__init__.py" in names
    assert "frontend/c300x-doorbell-call-card.js" in names
    assert "frontend/c300x-doorbell-call-card-metadata.js" in names
    assert "frontend/c300x-ringback-tone.js" in names
    assert "device_agent/bundle.json" in names
    assert "device_agent/scripts/bootstrap_firewall.sh" in names
    assert not any(name.startswith("custom_components/") for name in names)
    assert timestamps == {builder.ZIP_TIMESTAMP}
    assert output.read_bytes() == second_output.read_bytes()


def test_release_builder_requires_verified_device_sysroot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = _load_release_builder()
    missing_sysroot = tmp_path / "missing"
    valid_sysroot = tmp_path / "rootfs"
    (valid_sysroot / "lib").mkdir(parents=True)
    (valid_sysroot / "lib" / "libc.so.6").write_text("", encoding="utf-8")

    monkeypatch.setattr(builder, "AUTO_DEVICE_SYSROOT", missing_sysroot)
    monkeypatch.delenv("C300X_DEVICE_SYSROOT", raising=False)
    assert builder._release_sysroot() is None

    monkeypatch.setenv("C300X_DEVICE_SYSROOT", str(valid_sysroot))
    assert builder._release_sysroot() == valid_sysroot


def test_release_builder_can_reuse_agent_from_release_zip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builder = _load_release_builder()
    agent_binary = tmp_path / "native_agent" / "build" / "armhf" / "c300x-agent-native"
    release_zip = tmp_path / "ha-bticino-c300x.zip"
    with zipfile.ZipFile(release_zip, "w") as archive:
        archive.writestr("device_agent/armhf/c300x-agent-native", b"agent")

    monkeypatch.setattr(builder, "AGENT_BINARY", agent_binary)

    builder._restore_agent_from_release_zip(release_zip)

    assert agent_binary.read_bytes() == b"agent"
    assert agent_binary.stat().st_mode & 0o777 == 0o700


def test_release_workflow_accepts_verified_same_tag_assets() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    changed_inputs_block = workflow.split(
        'if [ -n "$changed_inputs" ]; then',
        1,
    )[1].split(
        'echo "::error::Native agent/bundle inputs changed',
        1,
    )[0]

    assert "Waiting for same-tag release assets" in changed_inputs_block
    assert "--pattern ha-bticino-c300x.zip" in changed_inputs_block
    assert "--pattern SHA256SUMS" in changed_inputs_block
    assert "--pattern build-metadata.json" in changed_inputs_block
    assert "--pattern sbom.spdx.json" in changed_inputs_block
    assert "sha256sum -c SHA256SUMS" in changed_inputs_block
    assert 'cp .release/reuse-current/ha-bticino-c300x.zip "$RELEASE_ZIP"' in (
        changed_inputs_block
    )
    assert 'cp .release/reuse-current/build-metadata.json "$RELEASE_METADATA"' in (
        changed_inputs_block
    )
    assert 'echo "asset_source=current-release" >> "$GITHUB_OUTPUT"' in (
        changed_inputs_block
    )
    assert "--reuse-agent-from-release-zip .release/reuse-current" not in (
        changed_inputs_block
    )
    assert (
        "if: steps.reusable-agent.outputs.asset_source == 'build'"
        in workflow
    )


def test_release_tag_checker_matches_current_metadata() -> None:
    checker = _load_release_tag_checker()
    version = json.loads(PROJECT_VERSIONS_PATH.read_text(encoding="utf-8"))[
        "integration_version"
    ]

    assert checker.validate_release_tag(f"v{version}") == []
    assert checker.validate_release_tag(version) == [
        f"release tag must use vX.Y.Z format, got {version!r}"
    ]


def test_release_assets_are_reproducible_for_same_zip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writer = _load_release_assets()
    monkeypatch.delenv("C300X_DEVICE_SYSROOT", raising=False)
    zip_path = tmp_path / "ha-bticino-c300x.zip"
    bundle = {
        "agent_version": "1.6.1",
        "api_version": "1",
        "architecture": "armhf",
        "bundle_hash": "bundle-sha",
    }
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("manifest.json", "{}\n")
        archive.writestr("device_agent/bundle.json", json.dumps(bundle) + "\n")

    first = tmp_path / "first"
    second = tmp_path / "second"
    for output_dir in (first, second):
        writer.write_release_assets(
            zip_path=zip_path,
            tag="v1.6.2",
            repository="example/repo",
            sha256sums_path=output_dir / "SHA256SUMS",
            metadata_path=output_dir / "build-metadata.json",
            sbom_path=output_dir / "sbom.spdx.json",
        )

    assert (first / "build-metadata.json").read_bytes() == (
        second / "build-metadata.json"
    ).read_bytes()
    assert (first / "sbom.spdx.json").read_bytes() == (
        second / "sbom.spdx.json"
    ).read_bytes()
    assert (first / "SHA256SUMS").read_bytes() == (second / "SHA256SUMS").read_bytes()

    metadata = json.loads((first / "build-metadata.json").read_text(encoding="utf-8"))
    assert metadata["release_tag"] == "v1.6.2"
    assert metadata["repository"] == "example/repo"
    assert metadata["device_agent_bundle"]["bundle_hash"] == "bundle-sha"
    assert metadata["lts_evidence"] == {
        "release": "v1.6.2",
        "min_homeassistant": "2026.5.0",
        "current_homeassistant": "2026.8.1",
        "validated_homeassistant": ["2026.5.0", "2026.8.1"],
        "python": "3.14",
        "firmware_target": "1.7.x",
        "native_agent_rebuilt": True,
        "native_agent_reused_from": None,
        "native_agent_sysroot": {
            "configured": False,
            "available": False,
            "fingerprint": None,
            "files": {},
        },
        "validated_jobs": ["min-ha", "current-ha", "hacs", "hassfest"],
    }

    checksum_lines = (first / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert any(line.endswith("  ha-bticino-c300x.zip") for line in checksum_lines)
    assert any(line.endswith("  build-metadata.json") for line in checksum_lines)
    assert any(line.endswith("  sbom.spdx.json") for line in checksum_lines)

    sbom = json.loads((first / "sbom.spdx.json").read_text(encoding="utf-8"))
    assert sbom["spdxVersion"] == "SPDX-2.3"
    assert {file["fileName"] for file in sbom["files"]} == {
        "device_agent/bundle.json",
        "manifest.json",
    }


def test_release_metadata_records_reused_native_agent(tmp_path: Path) -> None:
    writer = _load_release_assets()
    zip_path = tmp_path / "ha-bticino-c300x.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("manifest.json", "{}\n")

    writer.write_release_assets(
        zip_path=zip_path,
        tag="v1.6.5",
        repository="example/repo",
        native_agent_reused_from="v1.6.4",
        sha256sums_path=tmp_path / "SHA256SUMS",
        metadata_path=tmp_path / "build-metadata.json",
        sbom_path=tmp_path / "sbom.spdx.json",
    )

    metadata = json.loads((tmp_path / "build-metadata.json").read_text(encoding="utf-8"))
    assert metadata["lts_evidence"]["native_agent_rebuilt"] is False
    assert metadata["lts_evidence"]["native_agent_reused_from"] == "v1.6.4"


def test_release_metadata_records_native_sysroot_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    writer = _load_release_assets()
    zip_path = tmp_path / "ha-bticino-c300x.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("manifest.json", "{}\n")

    sysroot = tmp_path / "rootfs"
    libc = sysroot / "lib" / "libc.so.6"
    ld_linux = sysroot / "lib" / "ld-linux-armhf.so.3"
    libc.parent.mkdir(parents=True)
    libc.write_bytes(b"glibc")
    ld_linux.write_bytes(b"ld")
    monkeypatch.setenv("C300X_DEVICE_SYSROOT", str(sysroot))

    writer.write_release_assets(
        zip_path=zip_path,
        tag="v1.7.0",
        repository="example/repo",
        sha256sums_path=tmp_path / "SHA256SUMS",
        metadata_path=tmp_path / "build-metadata.json",
        sbom_path=tmp_path / "sbom.spdx.json",
    )

    metadata = json.loads((tmp_path / "build-metadata.json").read_text(encoding="utf-8"))
    sysroot_evidence = metadata["lts_evidence"]["native_agent_sysroot"]
    assert sysroot_evidence["configured"] is True
    assert sysroot_evidence["available"] is True
    assert sysroot_evidence["files"] == {
        "lib/ld-linux-armhf.so.3": f"sha256:{hashlib.sha256(b'ld').hexdigest()}",
        "lib/libc.so.6": f"sha256:{hashlib.sha256(b'glibc').hexdigest()}",
    }
    assert sysroot_evidence["fingerprint"].startswith("sha256:")
    assert "path" not in sysroot_evidence


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
    assert "device_agent/init/c300x-native-agent" in paths
    assert "device_agent/scripts/qml_patch.sh" in paths
    assert "device_agent/scripts/remove_agent.sh" in paths
    assert "device_agent/scripts/bootstrap_firewall.sh" in paths
    assert not any(path.startswith("device_agent/patches/") for path in paths)
    for path in RESERVED_DEVICE_PATCH_PATHS:
        assert path not in paths
    modes = {entry["path"]: entry["mode"] for entry in bundle["files"]}
    assert modes["device_agent/armhf/c300x-agent-native"] == "700"
    assert modes["device_agent/init/c300x-native-agent"] == "700"
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


def test_device_install_uploads_packaged_agent_binary() -> None:
    install_script = (ROOT / "scripts" / "install_c300x_device.sh").read_text(
        encoding="utf-8"
    )

    assert '"$ROOT_DIR/scripts/stage_device_agent_bundle.py" --skip-build' in install_script
    assert 'PACKAGED_AGENT_BINARY="$ROOT_DIR/custom_components/bticino_c300x/device_agent/armhf/c300x-agent-native"' in install_script
    assert 'PACKAGED_BUNDLE_MANIFEST="$ROOT_DIR/custom_components/bticino_c300x/device_agent/bundle.json"' in install_script
    assert '"$PACKAGED_AGENT_BINARY"' in install_script
    assert '"$PACKAGED_BUNDLE_MANIFEST"' in install_script
    assert "'$REMOTE_DIR/bundle.json'" in install_script
    assert '"$ROOT_DIR/native_agent/build/armhf/c300x-agent-native"' not in install_script


def test_ha_test_install_uses_release_agent_bundle_by_default() -> None:
    install_script = (ROOT / "scripts" / "install_ha_test.sh").read_text(
        encoding="utf-8"
    )

    assert 'PACKAGE_DEVICE_AGENT_DIR="$ROOT_DIR/.release/package/device_agent"' in install_script
    assert 'C300X_INSTALL_DEVICE_AGENT_SOURCE:-release' in install_script
    assert 'cp -a "$PACKAGE_DEVICE_AGENT_DIR/." "$INSTALL_STAGE_DIR/device_agent/"' in install_script
    workspace_branch = install_script[
        install_script.index("        workspace)") :
        install_script.index("        *)", install_script.index("        workspace)"))
    ]
    assert '"$ROOT_DIR/scripts/stage_device_agent_bundle.py"' in workspace_branch


def test_bundle_hash_ignores_integration_version_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stager = _load_bundle_stager()
    agent_binary = tmp_path / "c300x-agent-native"
    version_file = tmp_path / "VERSION"
    agent_binary.write_bytes(b"same-agent-binary")
    version_file.write_text("0.3.1\n", encoding="utf-8")
    monkeypatch.setattr(stager, "AGENT_BINARY", agent_binary)
    monkeypatch.setattr(stager, "AGENT_VERSION_FILE", version_file)

    first_component = tmp_path / "first" / "bticino_c300x"
    second_component = tmp_path / "second" / "bticino_c300x"
    stager.stage_bundle(first_component, version="1.0.0", skip_build=True)
    stager.stage_bundle(second_component, version="1.0.1", skip_build=True)

    first = json.loads(
        (first_component / "device_agent" / "bundle.json").read_text(encoding="utf-8")
    )
    second = json.loads(
        (second_component / "device_agent" / "bundle.json").read_text(encoding="utf-8")
    )

    assert first["integration_version"] == "1.0.0"
    assert second["integration_version"] == "1.0.1"
    assert first["bundle_hash"] == second["bundle_hash"]


def test_bundle_hash_changes_with_native_agent_version_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stager = _load_bundle_stager()
    agent_binary = tmp_path / "c300x-agent-native"
    version_file = tmp_path / "VERSION"
    agent_binary.write_bytes(b"same-agent-binary")
    monkeypatch.setattr(stager, "AGENT_BINARY", agent_binary)
    monkeypatch.setattr(stager, "AGENT_VERSION_FILE", version_file)

    first_component = tmp_path / "first" / "bticino_c300x"
    second_component = tmp_path / "second" / "bticino_c300x"
    version_file.write_text("0.3.1\n", encoding="utf-8")
    stager.stage_bundle(first_component, version="1.0.0", skip_build=True)
    version_file.write_text("0.3.2\n", encoding="utf-8")
    stager.stage_bundle(second_component, version="1.0.0", skip_build=True)

    first = json.loads(
        (first_component / "device_agent" / "bundle.json").read_text(encoding="utf-8")
    )
    second = json.loads(
        (second_component / "device_agent" / "bundle.json").read_text(encoding="utf-8")
    )

    assert first["agent_version"] == "0.3.1"
    assert second["agent_version"] == "0.3.2"
    assert first["bundle_hash"] != second["bundle_hash"]


def test_native_self_update_apply_matches_staged_manifest_files() -> None:
    """The native apply list must cover every staged self-update file."""

    update_paths = (ROOT / "native_agent/src/agent_update_paths.h").read_text(encoding="utf-8")

    assert '"device_agent/armhf/c300x-agent-native"' in update_paths
    assert '"device_agent/scripts/qml_patch.sh"' in update_paths
    assert '"device_agent/scripts/remove_agent.sh"' in update_paths
    assert '"device_agent/scripts/bootstrap_firewall.sh"' in update_paths
    assert '"device_agent/init/c300x-native-agent"' in update_paths


def test_native_self_update_reserves_external_patch_scripts_without_staging() -> None:
    """Carrier agent can receive future patch scripts without packaging them yet."""

    native_http = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    update_paths = (ROOT / "native_agent/src/agent_update_paths.h").read_text(encoding="utf-8")
    safe_path = native_http.split("static int safe_agent_update_path", 1)[1].split(
        "static int agent_update_stage_path",
        1,
    )[0]
    target_path = native_http.split("static int agent_update_target_path", 1)[1].split(
        "static int read_agent_bundle_metadata",
        1,
    )[0]
    apply_file = native_http.split("static int apply_agent_update_file", 1)[1].split(
        "static int render_agent_init_script",
        1,
    )[0]
    apply_files = native_http.split("static int apply_agent_update_files", 1)[1].split(
        "static void handle_agent_update_apply",
        1,
    )[0]

    assert "c300x_agent_update_file_path(path)" in safe_path
    assert "c300x_agent_update_patch_path(bundle_path)" in target_path
    assert 'relative_target = bundle_path + strlen("device_agent/")' in target_path
    assert "if (access(stage_path, F_OK) != 0)" in apply_file
    assert "return optional && !agent_update_manifest_sha_for_path" in apply_file
    assert "c300x_agent_update_patch_path(bundle_path)" in apply_file
    assert "C300X_AGENT_UPDATE_FILE_COUNT" in apply_files
    assert "C300X_AGENT_UPDATE_FILES[index].optional" in apply_files
    for path in RESERVED_DEVICE_PATCH_PATHS:
        assert f'"{path}"' in update_paths


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


def test_native_self_update_restarts_when_running_binary_is_stale() -> None:
    """Self-update must not trust bundle.json when the old process is still running."""

    native_http = (ROOT / "native_agent/src/http.c").read_text(encoding="utf-8")
    stale_check = native_http.split(
        "static int running_agent_binary_differs_from_update_manifest",
        1,
    )[1].split("static int apply_agent_update_file", 1)[0]
    apply_files = native_http.split("static int apply_agent_update_files", 1)[1].split(
        "static void handle_agent_update_apply",
        1,
    )[0]

    assert '"/proc/self/exe"' in stale_check
    assert "c300x_sha256_file_hex" in stale_check
    assert '"device_agent/armhf/c300x-agent-native"' in stale_check
    assert "running_agent_binary_differs_from_update_manifest(manifest)" in apply_files
    assert "summary->runtime_changed" in apply_files


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
