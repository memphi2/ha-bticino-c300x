"""The installed manifest commits only a completely verified bootstrap bundle."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.bticino_c300x import device_installer as installer
from custom_components.bticino_c300x.agent_update import compare_agent_bundle


@pytest.fixture
def transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Keep shared Qt4 transaction/failure coverage; C100X package admission is
    # exercised without this double in test_c100x_ssh_admission.py.
    monkeypatch.setattr(installer, "_verify_c100x_bundle_sync", lambda *_: "qt4_ondisk")
    component = tmp_path / "component"
    manifest = {
        "agent_version": "same-version", "api_version": "1",
        "bundle_hash": "sha256:new", "update_file_set_version": 4,
    }
    old_manifest = json.dumps({**manifest, "bundle_hash": "sha256:old"}).encode()
    for name in (
        "armhf/c300x-agent-native", "init/c300x-native-agent",
        "scripts/qml_patch.sh", "scripts/remove_agent.sh", "scripts/bootstrap_firewall.sh",
        *(f"qml/{name}" for name in installer.DISPLAY_FILES), "qml/c100x_bundle.sh", "bundle.json",
    ):
        path = component / "device_agent" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(manifest).encode() if name == "bundle.json" else name.encode())
    monkeypatch.setattr(installer, "COMPONENT_DIR", component)
    remote_dir = "/synthetic/custom-agent"
    bundle = installer._resolve_bundle(remote_dir)
    manifest_path = f"{remote_dir}/bundle.json"
    obsolete_path = f"{remote_dir}/qml/C300XEnergyDistribution.qml"

    class Client:
        failure: str | None = None
        closed = False

        def __init__(self) -> None:
            self.files = {manifest_path: old_manifest, obsolete_path: b"old distribution"}
            self.operations: list[str] = []
            self.writes: list[str] = []

        def stage(self, name: str) -> None:
            self.operations.append(name)
            if name == self.failure:
                raise installer.C300XDeviceInstallError("device_install_failed")

        def write(self, path: str, data: bytes) -> bool:
            if self.files.get(path) == data:
                return False
            self.files[path] = data
            self.writes.append(path)
            return True

        def put_file(self, source: Path, path: str, _mode: str | None) -> bool:
            self.stage("manifest" if path == manifest_path else (
                "qml-transfer" if "/qml/" in path else "payload"
            ))
            return self.write(path, source.read_bytes())

        def run(self, command: str) -> str:
            if command.startswith("if [ -L ") and "printf absent" in command:
                self.stage("firewall-preflight")
                return "absent" if self.failure == "missing-hook" else ""
            if "libQt5Core" in command:
                # A device with the Qt 4 display, which the Display patch edits.
                return "qt4\nc300x\n"
            if command.startswith("if [ -L ") and obsolete_path in command:
                self.stage("cleanup-source")
                self.files.pop(obsolete_path, None)
            elif command.endswith(" restart"):
                self.stage("restart")
            elif "qml_patch.sh " in command:
                action = command.rsplit(" ", 1)[1]
                self.stage(action)
                return json.dumps({
                    "ok": self.failure != f"bad-{action}", "core_patched": True,
                    "gui_running": True, "patched": action == "apply",
                })
            else:
                assert command.startswith("mkdir -p "), command
            return ""

        def close(self) -> None:
            self.closed = True

    client = Client()
    monkeypatch.setattr(installer, "_connect_device_client", lambda _request: client)
    monkeypatch.setattr(installer, "_read_remote_config_sync", lambda *_args: {})

    def write_config(_client, path, data, **_kwargs):
        client.stage("config")
        return client.write(path, data)

    def startup(*_args):
        client.stage("startup")
        return ()

    monkeypatch.setattr(installer, "_write_remote_file_sync", write_config)
    monkeypatch.setattr(installer, "_install_startup_script_sync", startup)
    monkeypatch.setattr(installer, "_apply_firewall_patch_sync", lambda *_args: client.stage("firewall"))
    monkeypatch.setattr(installer, "_verify_startup_sync", lambda *_args: client.stage("verify"))

    def install(*, apply_gui_patch: bool):
        client.closed = False
        return installer._install_device_agent_sync(
            installer.C300XDeviceInstallRequest(
                host="unused.invalid", ssh_username="unused", ssh_password="unused",
                remote_dir=remote_dir, apply_gui_patch=apply_gui_patch,
            ),
            bundle, b"{}",
        )

    def update_required() -> bool:
        installed = json.loads(client.files[manifest_path])
        return compare_agent_bundle({
            "version": "same-version", "api_version": "1",
            "agent": {"bundle_hash": installed["bundle_hash"], "self_update_supported": True,
                      "self_update_file_set_version": 4},
        }, manifest).update_required

    return SimpleNamespace(
        client=client, install=install, update_required=update_required,
        manifest_path=manifest_path, old_manifest=old_manifest,
        obsolete_path=obsolete_path,
    )


@pytest.mark.parametrize("apply_gui_patch", [False, True])
@pytest.mark.parametrize("failure", [
    "payload", "qml-transfer", "config", "startup", "firewall", "restart", "verify", "core-apply", "manifest",
])
def test_failed_install_preserves_manifest_and_retry_is_idempotent(
    transaction, apply_gui_patch, failure,
) -> None:
    client = transaction.client
    client.failure = failure
    with pytest.raises(installer.C300XDeviceInstallError):
        transaction.install(apply_gui_patch=apply_gui_patch)
    assert client.closed
    assert client.files[transaction.manifest_path] == transaction.old_manifest
    assert client.files[transaction.obsolete_path] == b"old distribution"
    assert transaction.update_required()
    if failure != "manifest":
        assert "manifest" not in client.operations

    client.failure = None
    client.operations.clear()
    changed = transaction.install(apply_gui_patch=apply_gui_patch)
    assert client.closed
    assert changed[-1] == transaction.manifest_path
    assert client.operations[-2:] == ["manifest", "cleanup-source"]
    assert transaction.obsolete_path not in client.files
    assert ("apply" in client.operations) is apply_gui_patch
    assert not transaction.update_required()
    writes = client.writes.copy()
    assert transaction.install(apply_gui_patch=apply_gui_patch) == ()
    assert client.writes == writes
    assert client.writes.count(transaction.manifest_path) == 1


def test_missing_hook_leaves_firewall_alone_and_completes_install(transaction, monkeypatch) -> None:
    monkeypatch.setattr(installer, "_verify_c100x_bundle_sync", lambda *_: "qt5_ondisk")
    transaction.client.failure = "missing-hook"
    transaction.install(apply_gui_patch=False)
    assert "firewall-preflight" in transaction.client.operations
    assert "firewall" not in transaction.client.operations
    for phase in ("startup", "restart", "verify", "manifest"):
        assert phase in transaction.client.operations
    config = next(data for path, data in transaction.client.files.items() if path.endswith("/config.json"))
    assert json.loads(config)["maintenance"]["firewall"]["enabled"] is False
    assert transaction.client.closed


@pytest.mark.parametrize("kind", ["missing", "missing-directory", "file", "directory", "symlink", "dangling"])
def test_firewall_preflight_checks_real_file_type(tmp_path, monkeypatch, kind):
    path = tmp_path / "path with spaces"
    source = tmp_path / "source"
    if kind == "missing-directory":
        path = path / "missing parent" / "iptables"
    elif kind == "file":
        path.write_text("#!/bin/sh\n")
    elif kind == "directory":
        path.mkdir()
    elif kind in ("symlink", "dangling"):
        if kind == "symlink":
            source.touch()
        path.symlink_to(source)
    monkeypatch.setattr(installer, "REMOTE_FIREWALL_PATH", str(path))
    client = SimpleNamespace(run=lambda command: subprocess.check_output(["sh", "-c", command], text=True))
    if kind in ("file", "missing", "missing-directory"):
        assert installer._firewall_hook_present_sync(client) is (kind == "file")
    else:
        with pytest.raises(installer.C300XDeviceInstallError, match="installer_firewall_hook_unsupported"):
            installer._firewall_hook_present_sync(client)


def test_failed_firewall_does_not_install_autostart(transaction) -> None:
    transaction.client.failure = "firewall"
    with pytest.raises(installer.C300XDeviceInstallError):
        transaction.install(apply_gui_patch=False)
    assert "startup" not in transaction.client.operations
    assert "restart" not in transaction.client.operations


def test_full_patch_failure_does_not_publish_manifest(transaction) -> None:
    transaction.client.failure = "apply"
    with pytest.raises(installer.C300XDeviceInstallError):
        transaction.install(apply_gui_patch=True)
    assert transaction.client.closed
    assert transaction.client.files[transaction.manifest_path] == transaction.old_manifest
    assert transaction.client.files[transaction.obsolete_path] == b"old distribution"
    assert "manifest" not in transaction.client.operations
    assert transaction.update_required()
    transaction.client.failure = None
    assert transaction.install(apply_gui_patch=True)[-1] == transaction.manifest_path
    assert not transaction.update_required()


@pytest.mark.parametrize("action", ["core-apply", "apply"])
def test_failed_qml_json_retains_manifest(transaction, action) -> None:
    transaction.client.failure = f"bad-{action}"
    with pytest.raises(installer.C300XDeviceInstallError, match="device_install_verify_failed"):
        transaction.install(apply_gui_patch=True)
    assert transaction.client.closed
    assert transaction.client.files[transaction.manifest_path] == transaction.old_manifest
    assert transaction.client.files[transaction.obsolete_path] == b"old distribution"
    assert "manifest" not in transaction.client.operations
    assert transaction.update_required()


def test_source_cleanup_failure_is_not_install_success(transaction) -> None:
    transaction.client.failure = "cleanup-source"
    with pytest.raises(installer.C300XDeviceInstallError):
        transaction.install(apply_gui_patch=False)
    assert transaction.client.closed
    assert transaction.client.files[transaction.obsolete_path] == b"old distribution"
    assert transaction.client.operations[-2:] == ["manifest", "cleanup-source"]


def test_native_metadata_reader_observes_manifest_commit_without_restart(tmp_path) -> None:
    """The function used by capabilities must reopen the manifest each time."""
    root = Path(__file__).resolve().parents[1]
    manifest = tmp_path / "bundle.json"
    staged = tmp_path / "bundle.json.new"
    for path, value in ((manifest, "sha256:old"), (staged, "sha256:new")):
        path.write_text(json.dumps({
            "bundle_hash": value, "agent_version": "same-version", "api_version": "1",
        }))
    source = tmp_path / "metadata_reader.c"
    source.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "agent_update.h"
#include "c300x_agent.h"

int main(int argc, char **argv)
{
    assert(argc == 4);
    struct c300x_config config = {0};
    assert(snprintf(config.config_path, sizeof(config.config_path), "%s", argv[1])
        < (int)sizeof(config.config_path));
    char hash[128], version[64], api[32];
    assert(read_agent_bundle_metadata(&config, hash, sizeof(hash),
        version, sizeof(version), api, sizeof(api)));
    assert(strcmp(hash, "sha256:old") == 0);
    assert(rename(argv[2], argv[3]) == 0);
    assert(read_agent_bundle_metadata(&config, hash, sizeof(hash),
        version, sizeof(version), api, sizeof(api)));
    assert(strcmp(hash, "sha256:new") == 0);
    assert(strcmp(version, "same-version") == 0);
    return 0;
}
''')
    binary = tmp_path / "metadata-reader"
    native = root / "native_agent/src"
    compiled = subprocess.run([
        "cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
        "-Wall", "-Wextra", "-Werror", "-O2", "-I", str(native), str(source),
        *(str(native / name) for name in (
            "agent_update.c", "device_detect.c", "file_io.c", "string_util.c", "json_util.c", "json_parse.c", "sha256.c",
        )), "-o", str(binary),
    ], capture_output=True, text=True, check=False, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([
        str(binary), str(tmp_path / "config.json"), str(staged), str(manifest),
    ], capture_output=True, text=True, check=False, timeout=5)
    assert result.returncode == 0, result.stderr
