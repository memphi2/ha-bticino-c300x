"""Exercise the developer installer with local, non-network command doubles."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QML_SUCCESS = {"ok": True, "patched": True, "core_patched": True, "gui_running": True}


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
        "if name == 'sshpass' and sys.argv[-1].endswith(\"qml_patch.sh' apply\"):\n"
        "    print(os.environ['QML_RESULT'])\n"
        "    sys.exit(int(os.environ['QML_EXIT']))\n"
        "if name == 'sshpass' and sys.argv[-1].endswith(\"qml_patch.sh' status\"):\n"
        "    answers = json.loads(os.environ.get('QML_STATUS', '[]'))\n"
        "    seen = sum(1 for line in open(os.environ['COMMAND_LOG']) if \"qml_patch.sh' status\" in line)\n"
        "    print(json.dumps(answers[min(seen, len(answers)) - 1]))\n"
        "if name == 'sshpass' and 'ssh' in sys.argv "
        "and \"mv -f '\" in sys.argv[-1] and '.bundle.json.new' in sys.argv[-1]:\n"
        "    if os.environ.get('FAIL_MANIFEST') == '1': sys.exit(1)\n"
        "    with open(os.environ['REMOTE_MANIFEST'], 'w') as manifest:\n"
        "        manifest.write('new manifest\\n')\n"
        "if name == 'sshpass' and sys.argv[-1].startswith('if [ -L ') "
        "and 'C300XEnergyDistribution.qml' in sys.argv[-1]:\n"
        "    if os.environ.get('FAIL_CLEANUP') == '1': sys.exit(1)\n"
        "    os.unlink(os.environ['REMOTE_OBSOLETE_SOURCE'])\n"
        "if name == 'sshpass' and os.environ.get('FAIL_STARTUP') == '1' "
        "and sys.argv[-1].startswith('sh -s -- '):\n"
        "    sys.exit(1)\n"
    )
    path.chmod(0o700)


def _run_install(
    tmp_path: Path, *, fail_target: str = "", fail_startup: bool = False,
    remote_dir: str = "/synthetic/agent", apply_qml: bool = False,
    qml_result: str = "", qml_exit: int = 0, upload_agent: bool = True,
    fail_manifest: bool = False, fail_cleanup: bool = False, qml_status: list | None = None,
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
    manifest = tmp_path / "remote-bundle.json"
    manifest.write_text("old manifest\n")
    obsolete = tmp_path / "old-distribution.qml"
    obsolete.write_text("old distribution\n")
    result = subprocess.run(
        ["bash", str(scripts / "install_c300x_device.sh"),
         *(["--agent"] if upload_agent else []), *(["--apply-qml"] if apply_qml else [])],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "FAIL_TARGET": fail_target,
            "FAIL_STARTUP": "1" if fail_startup else "0",
            "QML_RESULT": qml_result,
            "QML_EXIT": str(qml_exit),
            "QML_STATUS": json.dumps(qml_status or []),
            "C300X_DISPLAY_RESTART_POLL_SECONDS": "0",
            "REMOTE_MANIFEST": str(manifest),
            "REMOTE_OBSOLETE_SOURCE": str(obsolete),
            "FAIL_MANIFEST": "1" if fail_manifest else "0",
            "FAIL_CLEANUP": "1" if fail_cleanup else "0",
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
    from stage_device_agent_bundle import LEGACY_BOOTSTRAP_QML, stage_bundle

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
    # The old-updater tombstone is staging-only, never an SSH-installed source.
    assert sources == (expected - {LEGACY_BOOTSTRAP_QML}) | {"device_agent/bundle.json"}
    assert LEGACY_BOOTSTRAP_QML not in sources
    startup = next(i for i, call in enumerate(calls) if call[-1].startswith("sh -s -- "))
    manifest = next(i for i, call in enumerate(calls) if any(arg.endswith("/device_agent/bundle.json") for arg in call))
    assert startup < manifest
    assert ".bundle.json.new" in calls[-2][-1]
    assert "C300XEnergyDistribution.qml" in calls[-1][-1]
    assert not (tmp_path / "old-distribution.qml").exists()


def test_failed_startup_install_never_publishes_bundle_manifest(tmp_path):
    result, calls = _run_install(tmp_path, fail_startup=True)
    assert result.returncode != 0
    assert not any("bundle.json" in arg for call in calls for arg in call)
    assert "Installed" not in result.stdout


@pytest.mark.parametrize("payload", [
    "", "not JSON", "null", "[]", "true", "{}",
    json.dumps(json.dumps(QML_SUCCESS)),
    json.dumps(QML_SUCCESS) + "\n{}",
    *[json.dumps({**QML_SUCCESS, key: value})
      for key in QML_SUCCESS for value in (False, None, 1, "true")],
    *[json.dumps({key: value for key, value in QML_SUCCESS.items() if key != missing})
      for missing in QML_SUCCESS],
    json.dumps({"ok": False, "state": "reload_failed", "patched": None,
                "core_patched": None, "gui_running": False}),
    *[json.dumps({**QML_SUCCESS, "qt5_overlay": overlay})
      for overlay in ("failed", "incomplete", "off", "unknown")],
])
def test_failed_qml_result_preserves_old_manifest(tmp_path, payload):
    result, calls = _run_install(tmp_path, apply_qml=True, qml_result=payload)
    assert result.returncode != 0
    assert "QML patch verification failed" in result.stderr
    assert "Installed" not in result.stdout
    assert not any("bundle.json" in arg for call in calls for arg in call)
    assert (tmp_path / "remote-bundle.json").read_text() == "old manifest\n"
    assert (tmp_path / "old-distribution.qml").read_text() == "old distribution\n"


def test_qml_transport_failure_preserves_old_manifest(tmp_path):
    result, calls = _run_install(
        tmp_path, apply_qml=True, qml_result=json.dumps(QML_SUCCESS), qml_exit=1,
    )
    assert result.returncode != 0
    assert "Installed" not in result.stdout
    assert not any("bundle.json" in arg for call in calls for arg in call)
    assert (tmp_path / "remote-bundle.json").read_text() == "old manifest\n"
    assert (tmp_path / "old-distribution.qml").read_text() == "old distribution\n"


def test_verified_qml_result_precedes_manifest_publication(tmp_path):
    payload = json.dumps({**QML_SUCCESS, "state": "patched"}, indent=2)
    result, calls = _run_install(tmp_path, apply_qml=True, qml_result=payload)
    assert result.returncode == 0, result.stderr
    qml = next(i for i, call in enumerate(calls) if call[-1].endswith("qml_patch.sh' apply"))
    manifest = next(i for i, call in enumerate(calls) if "bundle.json" in call[-1])
    assert qml < manifest
    assert (tmp_path / "remote-bundle.json").read_text() == "new manifest\n"
    assert payload in result.stdout
    assert "Installed" in result.stdout


def test_an_unknown_qt5_display_still_installs_the_agent(tmp_path):
    payload = json.dumps({"ok": False, "error": "display_unsupported", "qt5_unsupported": "display_program_unknown",
                          "patched": False, "core_patched": False, "gui_running": True, "qt5_overlay": "off"})
    result, _calls = _run_install(tmp_path, apply_qml=True, qml_result=payload)
    assert result.returncode == 0, result.stderr
    assert "display_program_unknown" in result.stderr
    assert (tmp_path / "remote-bundle.json").read_text() == "new manifest\n"
    assert "Installed" in result.stdout


@pytest.mark.parametrize("success", [False, True])
def test_qml_only_install_also_validates_result(tmp_path, success):
    result, calls = _run_install(
        tmp_path, apply_qml=True, upload_agent=False,
        qml_result=json.dumps({**QML_SUCCESS, "gui_running": success}),
    )
    assert (result.returncode == 0) is success
    assert ("Installed" in result.stdout) is success
    assert not any("bundle.json" in arg for call in calls for arg in call)
    assert (tmp_path / "remote-bundle.json").read_text() == "old manifest\n"
    assert (tmp_path / "old-distribution.qml").exists() is not success


def test_failed_manifest_retains_old_source(tmp_path):
    result, calls = _run_install(tmp_path, apply_qml=True, qml_result=json.dumps(QML_SUCCESS), fail_manifest=True)
    assert result.returncode != 0
    assert (tmp_path / "old-distribution.qml").read_text() == "old distribution\n"
    assert not any(call[-1].startswith("if [ -L ") for call in calls)


def test_source_cleanup_error_is_not_install_success(tmp_path):
    result, _calls = _run_install(tmp_path, fail_cleanup=True)
    assert result.returncode != 0
    assert "Installed" not in result.stdout
    assert (tmp_path / "old-distribution.qml").read_text() == "old distribution\n"


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


def test_a_display_restart_still_running_is_waited_for(tmp_path):
    """The apply answer says the restart is still in flight: the status settles it."""

    pending = {**QML_SUCCESS, "gui_running": False, "qt5_overlay": "off", "gui_restart": "pending"}
    settled = {"ok": True, "patched": True, "core_patched": True, "gui_running": True,
               "qt5_overlay": "active", "gui_restart": "idle"}
    result, calls = _run_install(
        tmp_path, apply_qml=True, qml_result=json.dumps(pending),
        qml_status=[{**pending}, settled],
    )
    assert result.returncode == 0, result.stderr
    assert sum("qml_patch.sh' status" in call[-1] for call in calls) == 2
    assert (tmp_path / "remote-bundle.json").read_text() == "new manifest\n"


def test_a_display_restart_that_ends_failed_still_fails_the_install(tmp_path):
    pending = {**QML_SUCCESS, "gui_running": False, "qt5_overlay": "off", "gui_restart": "pending"}
    failed = {"ok": True, "patched": True, "core_patched": True, "gui_running": True,
              "qt5_overlay": "failed", "gui_restart": "idle"}
    result, _calls = _run_install(
        tmp_path, apply_qml=True, qml_result=json.dumps(pending), qml_status=[failed],
    )
    assert result.returncode != 0
    assert "QML patch verification failed" in result.stderr
    assert (tmp_path / "remote-bundle.json").read_text() == "old manifest\n"
