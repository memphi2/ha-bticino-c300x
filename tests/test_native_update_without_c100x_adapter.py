"""A C300X agent takes a package without the Classe 100X display adapter."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from test_native_agent_update_legacy_bootstrap import _compile_updater

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("sanitize", [False, True])
def test_a_c300x_takes_a_package_without_the_c100x_adapter(tmp_path, monkeypatch, sanitize):
    """Every release before the joint package lacks the adapter; a C300X can still go back to one."""

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import stage_device_agent_bundle as stager

    native = _compile_updater(tmp_path, False, sanitize)
    agent = tmp_path / "agent"
    stage = agent / ".update"
    binary = tmp_path / "synthetic-binary"
    binary.write_bytes(b"synthetic payload, never executed")
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest_path = stage / "device_agent/bundle.json"
    manifest = json.loads(manifest_path.read_text())
    adapter = "device_agent/qml/c100x_bundle.sh"
    assert any(item["path"] == adapter for item in manifest["files"])
    manifest["files"] = [item for item in manifest["files"] if item["path"] != adapter]
    manifest_path.write_text(json.dumps(manifest))
    (stage / adapter).unlink()
    installed = agent / "c300x-agent-native"
    installed.write_bytes(b"original")

    def apply(expected, model_env):
        result = subprocess.run(
            [str(native), str(agent), str(manifest_path), str(int(expected))],
            env={**{k: v for k, v in os.environ.items() if k != "C100X_TEST_MODEL"}, **model_env},
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr

    # A C100X needs its adapter and refuses the package untouched.
    apply(False, {"C100X_TEST_MODEL": "1"})
    assert installed.read_bytes() == b"original"
    # A listed adapter that is missing is a broken package on every model.
    broken = {**manifest, "files": [*manifest["files"], {"path": adapter, "sha256": "0" * 64}]}
    manifest_path.write_text(json.dumps(broken))
    apply(False, {})
    assert installed.read_bytes() == b"original"
    manifest_path.write_text(json.dumps(manifest))
    apply(True, {})
    assert installed.read_bytes() == binary.read_bytes()
    assert not (agent / "qml/c100x_bundle.sh").exists()
    apply(True, {})
