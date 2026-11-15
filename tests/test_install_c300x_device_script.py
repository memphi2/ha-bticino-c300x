"""Exercise the developer installer with local, non-network command doubles."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _fake_tool(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"name = {name!r}\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as log:\n"
        "    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
        "if name == 'make' and os.environ.get('FAIL_TARGET') in sys.argv[1:]:\n"
        "    sys.exit(1)\n"
    )
    path.chmod(0o700)


def _run_install(tmp_path: Path, *, fail_target: str = ""):
    tree = tmp_path / "checkout"
    scripts = tree / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts/install_c300x_device.sh", scripts)
    for filename, name in (
        ("stage_device_agent_bundle.py", "stage"),
        ("device_file_strip.py", "strip"),
    ):
        _fake_tool(scripts / filename, name)
    commands = tmp_path / "commands"
    for name in ("make", "sshpass"):
        _fake_tool(commands / name, name)
    log = tmp_path / "commands.jsonl"
    result = subprocess.run(
        ["bash", str(scripts / "install_c300x_device.sh"), "--agent"],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "FAIL_TARGET": fail_target,
            "C300X_HOST": "synthetic.invalid",
            "C300X_USER": "synthetic",
            "C300X_PASSWORD": "synthetic",
            "C300X_AGENT_DIR": "/synthetic/agent",
        },
        capture_output=True, text=True, check=False, timeout=10,
    )
    return result, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize("target", ["armhf", "armhf-abi-check"])
def test_build_failure_stops_before_staging_or_remote_mutation(tmp_path, target):
    result, calls = _run_install(tmp_path, fail_target=target)
    assert result.returncode != 0
    assert [call[0] for call in calls] == ["make"]
    assert "Installed" not in result.stdout


def test_abi_check_precedes_staging_and_remote_mutation(tmp_path):
    result, calls = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert calls[0][-2:] == ["armhf", "armhf-abi-check"]
    assert calls[1][0] == "stage"
    assert calls[2][0] == "sshpass"
