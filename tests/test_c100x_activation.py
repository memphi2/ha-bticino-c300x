"""Persistent activation transaction plus actual native challenge/CLI code."""

import hashlib
import json
import shlex
import shutil
import subprocess

import pytest
from c100x_activation_lab import activation_binary as activation_binary
from c100x_activation_lab import agent_lab, gui_peer
from test_c100x_bundle_delivery import payload
from test_c100x_display_transaction import (
    advance_source,
    assert_original,
    fault_mv,
    run,
)
from test_c100x_display_transaction import tree as tree
from test_c100x_qml_adapter import ROOT


def generation(tree):
    return hashlib.sha256((tree[0] / "source/SHA256SUMS").read_bytes()).hexdigest()


@pytest.mark.parametrize("blocked", [False, True])
def test_confirm_requires_actual_native_roundtrip_not_socket_or_marker(tree, activation_binary, blocked):
    run(tree, "prepare")
    pending = tree[0] / "backup/pending"
    assert pending.is_dir()
    with agent_lab(activation_binary, tree) as port, gui_peer(port, generation(tree), blocked=blocked):
        result = run(tree, "confirm")
    assert json.loads(result.stdout)["runtime_verified"] is True
    assert not pending.exists()
    assert list((tree[0] / "backup").glob("trial-history.*/snapshot/main.qml"))
    run(tree, "restore")
    assert_original(tree)


def test_hung_gui_rolls_back_prior_generation_without_signalling_it(tree, activation_binary):
    run(tree, "apply")
    prior = {name: (tree[1] / name).read_bytes() for name in tree[2]}
    advance_source(tree)
    run(tree, "prepare")
    with agent_lab(activation_binary, tree) as port, gui_peer(port, generation(tree), responsive=False):
        result = run(tree, "confirm", False)
    assert "GUI runtime requires recovery" in result.stderr
    assert prior == {name: (tree[1] / name).read_bytes() for name in tree[2]}
    assert not (tree[0] / "backup/pending").exists()
    assert all((tree[1] / name).stat().st_mode & 0o777 == 0o640 for name in prior)


@pytest.mark.parametrize("fault", ["kill_before", "kill_after"])
def test_persistent_trial_recovers_previous_state_after_process_death(tree, fault):
    run(tree, "apply")
    prior = {name: (tree[1] / name).read_bytes() for name in tree[2]}
    advance_source(tree)
    fault_mv(tree, fault)
    run(tree, "prepare", False)
    assert (tree[0] / "backup/pending").is_dir()
    shutil.rmtree(tree[0] / "source")
    run(tree, "recover")
    assert prior == {name: (tree[1] / name).read_bytes() for name in tree[2]}


@pytest.mark.parametrize("damage", ["main", "release", "symlink", "extra"])
def test_tampered_trial_cannot_authorize_rollback(tree, damage):
    run(tree, "prepare")
    pending = tree[0] / "backup/pending"
    if damage == "main":
        (pending / "main.qml").write_text("independent QML")
    elif damage == "release":
        (pending / "release").write_text(".c100x-" + "0" * 64)
    elif damage == "extra":
        (pending / "extra").touch()
    else:
        (pending / "main.qml").unlink()
        (pending / "main.qml").symlink_to(tree[0] / "backup/main.qml")
    before = (tree[1] / "main.qml").read_bytes()
    run(tree, "recover", False)
    assert (tree[1] / "main.qml").read_bytes() == before
    assert pending.exists()


def test_pending_trial_rejects_replacement_and_stock_restore_retains_history(tree):
    run(tree, "prepare")
    run(tree, "apply", False)
    run(tree, "prepare", False)
    run(tree, "restore")
    assert_original(tree)
    assert not (tree[0] / "backup/pending").exists()
    assert list((tree[0] / "backup").glob("trial-history.*/snapshot/release"))


@pytest.mark.parametrize("damage", ["missing", "corrupt", "symlink"])
def test_failed_installed_payload_rolls_back_without_package_sources(tree, damage):
    run(tree, "prepare")
    page = tree[1] / (".c100x-" + generation(tree)) / "C100XBridge.qml"
    if damage == "corrupt":
        page.write_text("broken QML")
    else:
        page.unlink()
        if damage == "symlink":
            page.symlink_to(tree[0] / "wrapper")
    shutil.rmtree(tree[0] / "source")
    run(tree, "confirm", False)
    assert_original(tree)


@pytest.mark.parametrize("action", ["recover", "restore"])
def test_readonly_failure_after_trial_rollback_never_reinstalls_candidate(tree, action):
    run(tree, "prepare")
    mount = tree[0] / "tools/mount"
    mount.write_text('#!/bin/sh\n[ "$2" != remount,ro ]\n')
    mount.chmod(0o700)
    tree[3]["C100X_NO_REMOUNT"] = "0"
    run(tree, action, False)
    assert_original(tree)
    assert list((tree[0] / "backup").glob("trial-history.*/snapshot/main.qml"))


@pytest.mark.parametrize("damage", [None, "missing_payload", "symlink_payload", "tampered_journal"])
def test_service_start_recovers_pending_trial_before_starting_agent(tree, damage):
    run(tree, "prepare")
    root, _, _, env = tree
    agent = root / "agent"
    agent.mkdir()
    binary = agent / "c300x-agent-native"
    binary.write_text('#!/bin/sh\nexit 99\n')
    binary.chmod(0o700)
    (agent / "config.json").write_text("{}")
    bundle = payload.build(agent / "qml/c100x_bundle.sh")
    if damage == "missing_payload":
        bundle.unlink()
    elif damage == "symlink_payload":
        target = root / "saved-bundle"
        bundle.rename(target)
        bundle.symlink_to(target)
    elif damage == "tampered_journal":
        (root / "backup/pending/main.qml").write_text("unknown change")
    launcher = root / "tools/start-stop-daemon"
    launcher.write_text('#!/bin/sh\nprintf "start\\n" >> "$START_LOG"\n')
    launcher.chmod(0o700)
    settings = root / "agent.env"
    settings.write_text("PATH=" + shlex.quote(env["PATH"]) + "\n")
    env.update(C300X_AGENT_DIR=str(agent), C300X_AGENT_ENV=str(settings), START_LOG=str(root / "start.log"))
    result = subprocess.run(["sh", str(ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent"),
                             "start"], env=env, capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) == (damage is None), result.stdout + result.stderr
    assert (root / "start.log").exists() == (damage is None)
    assert binary.exists() and (root / "backup/main.qml").exists()
    if damage is None:
        assert_original(tree)
    else:
        assert (root / "backup/pending").is_dir()


@pytest.mark.parametrize("mode", ["challenge", "ready", "idle"])
def test_native_response_parser_rejects_ambiguous_or_unbounded_input(activation_binary, mode):
    generation, probe = "a" * 64, "b" * 32
    body = {"ok": True, "gui_ready": True, "idle": True, "generation": generation, "probe": probe}
    arguments = [str(activation_binary), "--c100x-gui-response", mode, generation, probe]
    for value, success in [(json.dumps(body), True), ("{}", False), (json.dumps({**body, "ok": "true"}), False),
                           (json.dumps(body)[:-1] + ', "ok":false}', False),
                           (json.dumps(body) + "garbage", False), (json.dumps(body) + " " * 512, False),
                           (json.dumps(body) + "\0", False)]:
        result = subprocess.run(arguments, input=value, capture_output=True, text=True, timeout=3)
        assert (result.returncode == 0) == success, result.stderr
