"""Real legacy required-file preflight followed by the current updater."""

import shutil
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "4ce1a48"


def _compile_updater(tmp_path, legacy, sanitize, *, commit=None):
    tree = tmp_path / ("legacy" if legacy else "current")
    (tree / "src").mkdir(parents=True)
    (tree / "test").mkdir()
    for source in (ROOT / "native_agent/src").glob("*.[ch]"):
        shutil.copyfile(source, tree / "src" / source.name)
    if legacy or commit:
        for name in ("agent_update.c", "agent_update.h", "agent_update_paths.h"):
            historical = subprocess.run(
                ["git", "show", f"{commit or LEGACY_COMMIT}:native_agent/src/{name}"],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout
            (tree / "src" / name).write_bytes(historical)
        if legacy:
            assert '{"device_agent/qml/C300XEnergyDistribution.qml", 0644, 0}' in (tree / "src/agent_update_paths.h").read_text()
    shutil.copyfile(ROOT / "native_agent/test/agent_update_upgrade_test.c", tree / "test/agent_update_upgrade_test.c")
    binary = tree / "updater"
    flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitize else ["-O2"]
    result = subprocess.run(
        ["cc", "-std=c11", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror", *flags,
         *(str(tree / name) for name in ("test/agent_update_upgrade_test.c", "src/file_io.c", "src/string_util.c", "src/json_util.c", "src/json_parse.c", "src/sha256.c")),
         "-o", str(binary)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("sanitize", [False, True])
def test_real_legacy_bootstrap_then_new_source_cleanup(tmp_path, monkeypatch, sanitize):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import (
        LEGACY_BOOTSTRAP_CONTENT,
        LEGACY_BOOTSTRAP_QML,
        stage_bundle,
    )

    agent = tmp_path / "agent"
    (agent / "qml").mkdir(parents=True)
    old_source = agent / "qml/C300XEnergyDistribution.qml"
    old_source.write_text("old generated distribution")
    unknown = agent / "qml/user.qml"
    unknown.write_text("user owned")
    stock = agent / "qml/HomePage.qml"
    stock.write_text("stock source must remain")
    binary = tmp_path / "not-executed-native-binary"
    binary.write_bytes(b"synthetic payload, never executed")
    stage = agent / ".update"
    stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest = stage / "device_agent/bundle.json"
    legacy_source = stage / LEGACY_BOOTSTRAP_QML
    assert legacy_source.read_bytes() == LEGACY_BOOTSTRAP_CONTENT
    old = _compile_updater(tmp_path, True, sanitize)
    current = _compile_updater(tmp_path, False, sanitize)

    def apply(updater, expected=True):
        result = subprocess.run(
            [str(updater), str(agent), str(manifest), str(int(expected))],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "C100X_TEST_MODEL": "1"},
        )
        assert result.returncode == 0, result.stderr

    legacy_source.unlink()
    apply(old, False)
    assert old_source.read_text() == "old generated distribution"
    assert not (agent / "bundle.json").exists()
    legacy_source.write_bytes(LEGACY_BOOTSTRAP_CONTENT)
    apply(old)
    assert old_source.read_bytes() == LEGACY_BOOTSTRAP_CONTENT
    assert not (agent / "qml/C300XEnergyConsumers.qml").exists()
    apply(current)
    assert not old_source.exists()
    assert (agent / "qml/C300XEnergyConsumers.qml").is_file()
    assert legacy_source.read_bytes() == LEGACY_BOOTSTRAP_CONTENT
    apply(current)
    assert not old_source.exists()
    assert unknown.read_text() == "user owned"
    assert stock.read_text() == "stock source must remain"
    assert not list(agent.rglob("*.update-backup"))
