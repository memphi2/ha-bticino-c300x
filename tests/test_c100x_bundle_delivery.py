"""Compact C100X payload delivery and real disk transactions, without a GUI."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_c100x_display_transaction import tree, assert_original  # noqa: F401
from test_native_agent_update_legacy_bootstrap import _compile_updater

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import c100x_bundle_builder as payload  # noqa: E402
import c100x_qml_builder as qml  # noqa: E402
import stage_device_agent_bundle as stager  # noqa: E402


def test_builder_rejects_stale_output_without_removing_unrelated_files(tmp_path):
    output = tmp_path / "adapter"
    output.mkdir()
    stale = output / "DeletedPage.qml"
    stale.write_text("user or retired source")
    with pytest.raises(ValueError, match="fresh empty"):
        qml.build(output)
    assert stale.read_text() == "user or retired source"
    assert list(output.iterdir()) == [stale]
    alias = tmp_path / "alias"
    alias.symlink_to(output, target_is_directory=True)
    with pytest.raises(ValueError, match="fresh empty"):
        qml.build(alias)


def test_payload_is_deterministic_and_original_shell_accepts_it(tmp_path):
    first = payload.build(tmp_path / "one.sh")
    second = payload.build(tmp_path / "two.sh")
    assert first.read_bytes() == second.read_bytes()
    assert first.stat().st_mode & 0o777 == 0o700
    assert first.stat().st_size < payload.MAX_PAYLOAD_BYTES
    firmware = ROOT.parent / "c300x-fwpatch/work/rootfs-c100x-1.5.8"
    busybox = firmware / "bin/busybox.nosuid"
    if not busybox.is_file() or not shutil.which("qemu-arm"):
        pytest.skip("original firmware shell and qemu-arm required")
    result = subprocess.run(["qemu-arm", "-L", str(firmware), str(busybox), "sh", "-n", str(first)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_payload_runs_real_transaction_and_restores_without_current_sources(tree):
    directory, gui, _, env = tree
    script = payload.build(directory / "payload.sh")
    # Neither supplied source nor helper/transform overrides may replace the
    # embedded trusted inputs. Original firmware paths still point to copies.
    env = {**env, "C100X_SOURCE_DIR": str(directory / "absent"),
           "C100X_IDENTITY_SCRIPT": str(directory / "absent"), "C100X_HOOKS_AWK": str(directory / "absent")}
    def run(action, success=True):
        result = subprocess.run(["sh", str(script), action], env=env, capture_output=True, text=True, timeout=20)
        assert (result.returncode == 0) == success, result.stderr
        assert not list(directory.glob("c100x-payload.*"))
        return result

    assert json.loads(run("status").stdout)["state"] == "stock"
    run("apply")
    assert b"c100xFullScreen" in (gui / "main.qml").read_bytes()
    # Damage only a QML block: apply refuses it, restore never extracts it.
    content = script.read_bytes()
    needle = b"property bool c100xFullScreen: true"
    assert content.count(needle) == 1
    script.write_bytes(content.replace(needle, b"property bool c100xFullScreen: false"))
    run("apply", False)
    run("restore")
    assert_original(tree)
    assert (directory / "backup/main.qml").is_file()


@pytest.fixture(scope="module")
def updaters(tmp_path_factory):
    directory = tmp_path_factory.mktemp("c100x-payload-updaters")
    # Actual fixed file-set-6 updater, including its 8192-byte manifest reader.
    old = _compile_updater(directory, False, False, commit="5a6ff2b9")
    current_root = directory / "new"
    current_root.mkdir()
    current = _compile_updater(current_root, False, False)
    return old, current


@pytest.mark.parametrize("damage", [None, "missing", "corrupt"])
def test_actual_old_reader_bootstraps_compact_payload(tmp_path, updaters, damage):
    agent = tmp_path / "agent"
    (agent / "qml").mkdir(parents=True)
    unrelated = agent / "qml/user.qml"
    unrelated.write_text("keep unrelated file")
    stage = agent / ".update"
    binary = tmp_path / "not-executed"
    binary.write_bytes(b"test native binary never executed")
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest = stage / "device_agent/bundle.json"
    document = json.loads(manifest.read_bytes())
    assert len(manifest.read_bytes()) < 8192
    assert document["update_file_set_version"] == 7
    entries = [item for item in document["files"] if "c100x" in item["path"]]
    assert len(entries) == 1 and entries[0]["path"] == payload.MEMBER
    source = stage / payload.MEMBER
    expected = source.read_bytes()
    target = agent / "qml/c100x_bundle.sh"

    def apply(updater, success):
        result = subprocess.run([str(updater), str(agent), str(manifest), str(int(success))],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr

    apply(updaters[0], True)
    assert not target.exists()  # File-set 6 cannot install this new path.
    assert (agent / "c300x-agent-native").read_bytes() == binary.read_bytes()
    if damage == "missing":
        source.unlink()
    elif damage == "corrupt":
        source.write_bytes(b"corrupt")
    apply(updaters[1], damage is None)
    if damage:
        assert not target.exists()
        source.write_bytes(expected)
        source.chmod(0o700)
        apply(updaters[1], True)
    assert target.read_bytes() == expected
    assert hashlib.sha256(expected).hexdigest() == entries[0]["sha256"]
    assert target.stat().st_mode & 0o777 == 0o700
    assert unrelated.read_text() == "keep unrelated file"
    assert not list(agent.rglob("*.update-backup"))


def test_manifest_limit_is_enforced_before_writing_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(stager, "LEGACY_MANIFEST_BUFFER_BYTES", 100)
    with pytest.raises(stager.BundleStageError, match="legacy updater buffer"):
        stager.stage_bundle(tmp_path / "stage", version="test", skip_build=True, agent_binary=ROOT / "project-versions.json")
    assert not (tmp_path / "stage/device_agent/bundle.json").exists()


def test_ssh_installer_resolves_generated_payload_and_refuses_incomplete_package(tmp_path, monkeypatch):
    from custom_components.bticino_c300x import device_installer

    stager.stage_bundle(tmp_path, version="test", skip_build=True, agent_binary=ROOT / "project-versions.json")
    monkeypatch.setattr(device_installer, "COMPONENT_DIR", tmp_path)
    bundle = device_installer._resolve_bundle("/agent")
    found = [item for item in bundle.payload_files if item.remote_path == "/agent/qml/c100x_bundle.sh"]
    assert len(found) == 1 and found[0].mode == "700"
    assert found[0].source == tmp_path / payload.MEMBER
    found[0].source.unlink()
    with pytest.raises(device_installer.C300XDeviceInstallError, match="agent_bundle_missing"):
        device_installer._resolve_bundle("/agent")
