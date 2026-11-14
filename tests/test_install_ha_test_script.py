"""Copy failures must stop installation before pruning or reporting success."""

import os
import subprocess
from pathlib import Path


def test_direct_copy_failure_does_not_prune(tmp_path):
    script = (Path(__file__).resolve().parents[1] / "scripts/install_ha_test.sh").read_text()
    function = script[script.index("direct_copy_tree() {"):]
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "alarm_state.py").write_text("_commands_with_alarmo_readiness")
    (source / "camera.py").write_text("new")
    (target / "old.py").write_text("keep until successful copy")
    environment = {**os.environ, "INSTALL_SOURCE_DIR": str(source), "TARGET_DIR": str(target)}
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail\ncp() { return 1; }\ngio_copy_tree() { echo unexpected-fallback; }\n' + function],
        env=environment, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "Installed" not in result.stdout
    assert "unexpected-fallback" not in result.stdout
    assert "installation is incomplete" in result.stderr
    assert (target / "old.py").exists()
