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
        "if name == 'sshpass' and os.environ.get('FAIL_STARTUP') == '1' "
        "and sys.argv[-1].startswith('sh -s -- '):\n"
        "    sys.exit(1)\n"
    )
    path.chmod(0o700)


def _run_install(
    tmp_path: Path, *, fail_target: str = "", fail_startup: bool = False,
    remote_dir: str = "/synthetic/agent",
):
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
            "FAIL_STARTUP": "1" if fail_startup else "0",
            "C300X_HOST": "synthetic.invalid",
            "C300X_USER": "synthetic",
            "C300X_PASSWORD": "synthetic",
            "C300X_AGENT_DIR": remote_dir,
        },
        capture_output=True, text=True, check=False, timeout=10,
    )
    return result, [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


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


def test_complete_bundle_is_uploaded_before_publishing_manifest(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import stage_bundle

    binary = tmp_path / "fake-agent"
    binary.write_bytes(b"synthetic, not executable")
    package = tmp_path / "expected"
    stage_bundle(package, version="test", skip_build=True, agent_binary=binary)
    expected = {
        item["path"] for item in json.loads((package / "device_agent/bundle.json").read_text())["files"]
    }
    result, calls = _run_install(tmp_path)
    assert result.returncode == 0, result.stderr
    uploads = [call for call in calls if call[0] == "sshpass" and "scp" in call]
    sources = {
        "device_agent/" + arg.split("/device_agent/", 1)[1]
        for call in uploads for arg in call[1:] if "/device_agent/" in arg
    }
    assert sources == expected | {"device_agent/bundle.json"}
    startup = next(i for i, call in enumerate(calls) if call[-1].startswith("sh -s -- "))
    manifest = next(i for i, call in enumerate(calls) if any(arg.endswith("/device_agent/bundle.json") for arg in call))
    assert startup < manifest
    assert ".bundle.json.new" in calls[-1][-1]


def test_failed_startup_install_never_publishes_bundle_manifest(tmp_path):
    result, calls = _run_install(tmp_path, fail_startup=True)
    assert result.returncode != 0
    assert not any("bundle.json" in arg for call in calls for arg in call)
    assert "Installed" not in result.stdout


@pytest.mark.parametrize("remote_dir", ["relative", "/agent/../other", "/agent'bad", "/agent$(bad)"])
def test_unsafe_custom_path_is_rejected_before_any_command(tmp_path, remote_dir):
    result, calls = _run_install(tmp_path, remote_dir=remote_dir)
    assert result.returncode != 0
    assert calls == []


@pytest.fixture
def startup_tree(tmp_path):
    init = tmp_path / "etc/init.d/c300x-native-agent"
    link = tmp_path / "etc/rc5.d/S40c300x-native-agent"
    init.parent.mkdir(parents=True)
    link.parent.mkdir(parents=True)
    init.write_text("old init\n")
    init.chmod(0o700)
    link.symlink_to("old-init")
    agent = tmp_path / "custom-agent"
    agent.mkdir()
    return agent, init, link, tmp_path / "mounts.log"


def _run_startup(tree, *, fail_step=""):
    agent, init, link, log = tree
    source = ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent"
    shutil.copy(source, agent / ".c300x-native-agent-init.new")
    installer = (ROOT / "scripts/install_c300x_device.sh").read_text()
    script = installer.split("<<'STARTUP_SCRIPT'\n", 1)[1].split("\nSTARTUP_SCRIPT", 1)[0]
    script = script.replace("init=/etc/init.d/c300x-native-agent", f"init='{init}'")
    script = script.replace("link=/etc/rc5.d/S40c300x-native-agent", f"link='{link}'")
    # Only mount is unconditionally mocked; file operations use temporary paths.
    doubles = '''
mount() {
    printf '%s\\n' "$*" >> "$MOUNT_LOG"
    case "$FAIL_STEP:$*" in rw:*remount,rw*|ro:*remount,ro*) return 1;; esac
}
cp() { [ "$FAIL_STEP" != copy ] || return 1; command cp "$@"; }
ln() { [ "$FAIL_STEP" != link ] || return 1; command ln "$@"; }
rm() {
    [ "$FAIL_STEP" != cleanup ] || [ "$2" != "$source" ] || return 1
    command rm "$@"
}
mv() {
    [ "$FAIL_STEP" != rename_init ] || [ "$3" != "$init" ] || return 1
    [ "$FAIL_STEP" != rename_link ] || [ "$3" != "$link" ] || return 1
    command mv "$@"
}
'''
    return subprocess.run(
        ["sh", "-s", "--", str(agent)], input=doubles + script,
        env={**os.environ, "FAIL_STEP": fail_step, "MOUNT_LOG": str(log)},
        capture_output=True, text=True, check=False, timeout=10,
    )


def test_startup_install_preserves_custom_path_and_is_idempotent(startup_tree):
    agent, init, link, log = startup_tree
    result = _run_startup(startup_tree)
    assert result.returncode == 0, result.stderr
    assert f'DEFAULT_AGENT_DIR="{agent}"' in init.read_text()
    assert init.stat().st_mode & 0o777 == 0o700
    assert link.readlink() == init
    assert (agent / "c300x-agent.env").read_text() == f"C300X_AGENT_DIR='{agent}'\n"
    assert log.read_text().splitlines() == ["-o remount,rw /", "-o remount,ro /"]
    stamp = init.stat().st_mtime_ns
    result = _run_startup(startup_tree)
    assert result.returncode == 0, result.stderr
    assert init.stat().st_mtime_ns == stamp
    assert len(log.read_text().splitlines()) == 2
    assert not list(agent.glob(".c300x-native-agent-init.new*"))


@pytest.mark.parametrize("step", ["rw", "copy", "link", "rename_init", "rename_link", "ro", "cleanup"])
def test_startup_failure_propagates_and_remounts_read_only(startup_tree, step):
    _agent, init, _link, log = startup_tree
    result = _run_startup(startup_tree, fail_step=step)
    assert result.returncode != 0
    if step not in {"rename_link", "ro", "cleanup"}:
        assert init.read_text() == "old init\n"
    mounts = log.read_text().splitlines()
    assert mounts == (["-o remount,rw /"] if step == "rw" else ["-o remount,rw /", "-o remount,ro /"])


@pytest.mark.parametrize("target", ["init", "link"])
def test_startup_refuses_directory_targets_before_remount(startup_tree, target):
    _agent, init, link, log = startup_tree
    path = init if target == "init" else link
    path.unlink()
    path.mkdir()
    result = _run_startup(startup_tree)
    assert result.returncode != 0
    assert path.is_dir()
    assert not log.exists()


@pytest.mark.parametrize("target", ["init", "link"])
def test_startup_refuses_unsafe_symlink_targets(startup_tree, target):
    agent, init, link, log = startup_tree
    victim = agent / "unrelated"
    if target == "init":
        victim.write_text("do not change")
    else:
        victim.mkdir()
    path = init if target == "init" else link
    path.unlink()
    path.symlink_to(victim)
    result = _run_startup(startup_tree)
    assert result.returncode != 0
    assert path.readlink() == victim
    assert not log.exists()
    if target == "init":
        assert victim.read_text() == "do not change"
    else:
        assert not list(victim.iterdir())
