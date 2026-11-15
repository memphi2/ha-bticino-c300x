"""Both SSH cleanup commands operate only on an exact regular source file."""

import subprocess
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]


def _cleanup(remote_dir, shell_installer):
    if shell_installer:
        line = next(line for line in (ROOT / "scripts/install_c300x_device.sh").read_text().splitlines()
                    if line.startswith('ssh_cmd "if [ -L ') and "C300XEnergyDistribution.qml" in line)
        return subprocess.run(
            ["bash", "-s", "--", str(remote_dir)],
            input='REMOTE_DIR=$1\nssh_cmd() { sh -c "$1"; }\n' + line,
            capture_output=True, text=True, timeout=5,
        )

    class Client:
        result = None

        def run(self, command):
            self.result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=5)

    client = Client()
    installer._remove_obsolete_display_source_sync(client, str(remote_dir))
    return client.result


@pytest.mark.parametrize("shell_installer", [False, True])
def test_only_exact_old_source_removed_and_idempotent(tmp_path, shell_installer):
    qml = tmp_path / "custom agent/qml"
    qml.mkdir(parents=True)
    old = qml / "C300XEnergyDistribution.qml"
    old.write_text("old distribution")
    for name in ("HomePage.qml", "MemoPage.qml", "user.qml", "C300XEnergyDistribution.qml.user"):
        (qml / name).write_text("keep")
    for _ in range(2):
        result = _cleanup(qml.parent, shell_installer)
        assert result.returncode == 0, result.stderr
        assert not old.exists()
    assert {path.name: path.read_text() for path in qml.iterdir()} == dict.fromkeys(
        ("HomePage.qml", "MemoPage.qml", "user.qml", "C300XEnergyDistribution.qml.user"), "keep"
    )


@pytest.mark.parametrize("shell_installer", [False, True])
@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory", "parent-symlink"])
def test_unsafe_cleanup_targets_refused_without_following(tmp_path, shell_installer, kind):
    agent = tmp_path / "agent"
    qml = agent / "qml"
    qml.mkdir(parents=True)
    old = qml / "C300XEnergyDistribution.qml"
    victim = tmp_path / "stock.qml"
    victim.write_text("keep stock")
    if kind == "directory":
        old.mkdir()
    elif kind == "parent-symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / old.name).write_text("keep outside")
        qml.rmdir()
        qml.symlink_to(outside, target_is_directory=True)
    else:
        old.symlink_to(victim if kind == "symlink" else tmp_path / "missing")
    result = _cleanup(agent, shell_installer)
    assert result.returncode != 0
    assert victim.read_text() == "keep stock"
    if kind == "parent-symlink":
        assert old.read_text() == "keep outside"
    elif kind == "directory":
        assert old.is_dir()
    else:
        assert old.is_symlink()
