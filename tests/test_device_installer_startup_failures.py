"""Execute startup-install shell sequencing with local command doubles only."""

import subprocess
from pathlib import Path

import pytest

from custom_components.bticino_c300x import device_installer as installer

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("init_changed", "failure", "expected_status"), [
    (init_changed, failure, status)
    for init_changed in (False, True)
    for failure, status in (("none", 0), ("rw", 21), ("ro", 22), ("link", 23), ("link_ro", 23))
] + [
    (True, "copy", 27), (True, "copy_ro", 27),
    (True, "chmod", 24), (True, "chmod_ro", 24),
    (True, "move", 25), (True, "move_ro", 25),
    (True, "cleanup", 26), (True, "cleanup_ro", 26),
])
def test_startup_failures_propagate_and_stop_install(
    monkeypatch: pytest.MonkeyPatch, init_changed: bool,
    failure: str, expected_status: int,
) -> None:
    commands: list[str] = []
    operations: list[str] = []
    statuses: list[int] = []

    class Client:
        closed = False

        def run(self, command: str, input_data: bytes | None = None) -> str:
            commands.append(command)
            if command.startswith("mount -o remount,rw /;"):
                # Never execute mount, chmod, mv or ln against the host filesystem.
                doubles = '''
mount() {
    case "$*" in
        *remount,rw*) printf 'rw\\n'; [ "$failure" != rw ] || return 21 ;;
        *remount,ro*) printf 'ro\\n'; case "$failure" in *ro) return 22;; esac ;;
        *) return 99 ;;
    esac
}
ln() { printf 'link\\n'; case "$failure" in link*) return 23;; esac; }
cp() { printf 'copy\\n'; case "$failure" in copy*) return 27;; esac; }
chmod() { printf 'chmod\\n'; case "$failure" in chmod*) return 24;; esac; }
mv() { printf 'move\\n'; case "$failure" in move*) return 25;; esac; }
rm() {
    if [ "$#" -gt 2 ]; then
        printf 'cleanup\\n'
        case "$failure" in cleanup*) return 26;; esac
    fi
}
'''
                result = subprocess.run(
                    ["sh", "-c", f"failure={failure}\n" + doubles + command],
                    capture_output=True, text=True, check=False, timeout=5,
                )
                operations.extend(result.stdout.splitlines())
                statuses.append(result.returncode)
                if result.returncode:
                    raise installer.C300XDeviceInstallError("device_install_failed")
            if command.startswith("readlink "):
                return installer.REMOTE_INIT_SCRIPT
            if command.endswith("qml_patch.sh core-apply"):
                return '{"ok":true,"core_patched":true,"gui_running":true}'
            return ""

        def close(self) -> None:
            self.closed = True

    client = Client()
    monkeypatch.setattr(installer, "_connect_device_client", lambda _request: client)
    # Isolate startup failures after admission; model rejection is tested
    # separately with real manifests in test_c100x_ssh_admission.
    monkeypatch.setattr(installer, "_verify_c100x_bundle_sync", lambda *_args: None)
    monkeypatch.setattr(installer, "_read_remote_config_sync", lambda *_args: {})
    monkeypatch.setattr(installer, "_write_remote_file_sync", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(installer, "_remote_content_matches_sync", lambda *_args: not init_changed)
    monkeypatch.setattr(installer, "_remote_symlink_target_matches_sync", lambda *_args: False)
    request = installer.C300XDeviceInstallRequest(
        host="unused.invalid", ssh_username="unused", ssh_password="unused",
        apply_firewall_patch=False, apply_gui_patch=False,
    )
    bundle = installer._ResolvedBundle(
        (), ROOT / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent",
    )
    if expected_status:
        with pytest.raises(installer.C300XDeviceInstallError, match="device_install_failed"):
            installer._install_device_agent_sync(request, bundle, b"{}")
        assert not any(command.endswith(" restart") for command in commands)
        assert not any("qml_patch.sh" in command for command in commands)
    else:
        changed = installer._install_device_agent_sync(request, bundle, b"{}")
        assert changed == (
            (installer.REMOTE_INIT_SCRIPT, installer.REMOTE_INIT_LINK)
            if init_changed else (installer.REMOTE_INIT_LINK,)
        )
        assert any(command.endswith(" restart") for command in commands)
    assert statuses == [expected_status]
    assert client.closed
    expected_operations = ["rw"]
    if failure != "rw":
        if init_changed:
            expected_operations.append("copy")
            if not failure.startswith("copy"):
                expected_operations.append("chmod")
                if not failure.startswith("chmod"):
                    expected_operations.append("move")
            expected_operations.append("cleanup")
        if not failure.startswith(("copy", "chmod", "move", "cleanup")):
            expected_operations.append("link")
        expected_operations.append("ro")
    assert operations == expected_operations
