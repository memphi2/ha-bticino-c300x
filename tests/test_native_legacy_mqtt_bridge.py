"""Legacy MQTT off stays off while a third-party watchdog restarts the bridge."""

import os
import signal
import subprocess
import time

import pytest
from test_native_agent_maintenance_jobs import lab as lab
from test_native_agent_maintenance_jobs import response, wait_until
from test_native_service_command_jobs import binary as binary
from test_native_service_command_jobs import maintenance_options as maintenance_options

LEGACY = "/api/v1/maintenance/legacy-mqtt"
# fquinto's watchdog loop, as installed in /etc/init.d/bt_service_watchdog.
FQUINTO_WATCHDOG = (
    '#!/bin/sh\n'
    'if ! /usr/bin/pgrep -f "TcpDump2Mqtt$" > /dev/null 2>&1; then\n'
    '\t/etc/tcpdump2mqtt/TcpDump2Mqtt >> /tmp/tcp_log.txt 2>&1 &\n'
    'fi\n'
)


@pytest.fixture
def stub_tools(tmp_path, monkeypatch):
    """pkill and mount of the agent are stand-ins: nothing on the host is signalled by name."""
    tools = tmp_path / "stub-bin"
    tools.mkdir()
    (tools / "pkill").write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> pkill-log\n'
        '[ "$2" = TcpDump2Mqtt ] && [ -f bridge-pid ] && kill "$(cat bridge-pid)" 2>/dev/null\nexit 0\n')
    (tools / "mount").write_text("#!/bin/sh\nexit 0\n")
    for tool in tools.iterdir():
        tool.chmod(0o700)
    (tmp_path / "firmware-writable").touch()
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    return tools


def legacy_install(root):
    etc = root / "foreign/etc"
    for folder in ("tcpdump2mqtt", "rc5.d", "init.d"):
        (etc / folder).mkdir(parents=True, exist_ok=True)
    bridge = etc / "tcpdump2mqtt/TcpDump2Mqtt"
    bridge.write_text("#!/bin/sh\ntouch bridge-started\nexec sleep 30\n")
    bridge.chmod(0o750)
    (etc / "tcpdump2mqtt/TcpDump2Mqtt.sh").write_text("#!/bin/sh\nexit 0\n")
    (etc / "tcpdump2mqtt/TcpDump2Mqtt.sh").chmod(0o755)
    (etc / "rc5.d/S99TcpDump2Mqtt").symlink_to("../tcpdump2mqtt/TcpDump2Mqtt.sh")
    (etc / "init.d/bt_service_watchdog").write_text(FQUINTO_WATCHDOG)
    return bridge


def start_watchdog(root):
    """A stand-in for the watchdog loop under a unique name, in its own process group."""
    loop = root / f"c300x-test-watchdog-{os.getpid()}.sh"
    loop.write_text(
        "#!/bin/sh\nwhile :; do\n"
        '  if ! { [ -f bridge-pid ] && kill -0 "$(cat bridge-pid)" 2>/dev/null; }; then\n'
        "    ./foreign/etc/tcpdump2mqtt/TcpDump2Mqtt >/dev/null 2>&1 &\n"
        '    echo "$!" > bridge-pid\n'
        "  fi\n  sleep 0.05\ndone\n")
    loop.chmod(0o700)
    return subprocess.Popen([str(loop)], cwd=root, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_legacy_mqtt_off_keeps_the_watchdog_from_restarting_the_bridge(stub_tools, lab):
    bridge = legacy_install(lab.root)
    record = lab.root / "foreign/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt/bridge-mode"
    status = response(lab.request(LEGACY))
    assert (status["bridge_blocked"], status["watchdog"]) == (False, True)
    watchdog = start_watchdog(lab.root)
    try:
        wait_until(lambda: (lab.root / "bridge-started").exists())

        off = response(lab.request(LEGACY, {"enabled": False}))

        assert (off["enabled"], off["bridge_blocked"], off["watchdog"]) == (False, True, True)
        assert "-f TcpDump2Mqtt" in (lab.root / "pkill-log").read_text()
        assert bridge.stat().st_mode & 0o7777 == 0o640
        assert record.read_text() == "0750\n"
        (lab.root / "bridge-started").unlink()
        time.sleep(0.5)
        assert not (lab.root / "bridge-started").exists(), "the watchdog started the bridge again"
        # The watchdog's own file stays as it was.
        assert (lab.root / "foreign/etc/init.d/bt_service_watchdog").read_text() == FQUINTO_WATCHDOG
        assert response(lab.request(LEGACY, {"enabled": False}))["bridge_blocked"] is True
        assert record.read_text() == "0750\n"

        on = response(lab.request(LEGACY, {"enabled": True}))

        assert (on["enabled"], on["bridge_blocked"]) == (True, False)
        assert bridge.stat().st_mode & 0o7777 == 0o750
        assert not record.exists()
        assert os.readlink(lab.root / "foreign/etc/rc5.d/S99TcpDump2Mqtt") == "../tcpdump2mqtt/TcpDump2Mqtt.sh"
        wait_until(lambda: (lab.root / "bridge-started").exists())
    finally:
        os.killpg(watchdog.pid, signal.SIGKILL)
        watchdog.wait(timeout=3)


def test_a_bridge_made_executable_again_keeps_its_new_mode(stub_tools, lab):
    bridge = legacy_install(lab.root)
    record = lab.root / "foreign/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt/bridge-mode"
    assert response(lab.request(LEGACY, {"enabled": False}))["bridge_blocked"] is True
    # Reinstalled by its own tool meanwhile: that mode wins, the record goes.
    bridge.chmod(0o700)
    assert response(lab.request(LEGACY))["bridge_blocked"] is False
    assert response(lab.request(LEGACY, {"enabled": True}))["enabled"] is True
    assert bridge.stat().st_mode & 0o7777 == 0o700
    assert not record.exists()
    # A link is never followed: its target keeps its mode.
    bridge.unlink()
    target = lab.root / "bridge-target"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    bridge.symlink_to(target)
    assert response(lab.request(LEGACY, {"enabled": False}))["bridge_blocked"] is False
    assert target.stat().st_mode & 0o7777 == 0o755


def test_on_without_a_record_makes_a_bridge_without_execute_bits_runnable(stub_tools, lab):
    """Removing the agent drops the record; an agent installed again must still turn it on."""
    bridge = legacy_install(lab.root)
    record = lab.root / "foreign/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt/bridge-mode"
    (lab.root / "foreign/etc/rc5.d/S99TcpDump2Mqtt").unlink()
    bridge.chmod(0o640)
    assert response(lab.request(LEGACY))["bridge_blocked"] is False

    on = response(lab.request(LEGACY, {"enabled": True}))

    assert (on["enabled"], on["bridge_blocked"]) == (True, False)
    assert bridge.stat().st_mode & 0o7777 == 0o750
    assert not record.exists()
    assert os.readlink(lab.root / "foreign/etc/rc5.d/S99TcpDump2Mqtt") == "../tcpdump2mqtt/TcpDump2Mqtt.sh"


BACKUPS = "foreign/home/bticino/cfg/extra/c300x-device-file-backups"
START_LINK = "foreign/etc/rc5.d/S99TcpDump2Mqtt"


def test_off_keeps_the_start_link_when_the_bridge_cannot_be_blocked(stub_tools, lab):
    bridge = legacy_install(lab.root)
    # The record cannot be written, so the block fails before any change.
    (lab.root / BACKUPS).mkdir(parents=True)
    (lab.root / BACKUPS / "legacy-mqtt").write_text("not a directory\n")

    assert response(lab.request(LEGACY, {"enabled": False}), 500)["error"] == "legacy_mqtt_disable_failed"

    assert os.readlink(lab.root / START_LINK) == "../tcpdump2mqtt/TcpDump2Mqtt.sh"
    assert bridge.stat().st_mode & 0o7777 == 0o750
    assert response(lab.request(LEGACY))["enabled"] is True


def test_off_gives_the_bridge_its_mode_back_when_the_start_link_cannot_go(stub_tools, lab):
    bridge = legacy_install(lab.root)
    link = lab.root / START_LINK
    link.unlink()
    (link / "entry").mkdir(parents=True)

    assert response(lab.request(LEGACY, {"enabled": False}), 500)["error"] == "legacy_mqtt_disable_failed"

    assert bridge.stat().st_mode & 0o7777 == 0o750
    assert not (lab.root / BACKUPS / "legacy-mqtt/bridge-mode").exists()
    assert response(lab.request(LEGACY))["bridge_blocked"] is False


def test_on_blocks_the_bridge_again_when_the_start_link_cannot_come(stub_tools, lab):
    bridge = legacy_install(lab.root)
    record = lab.root / BACKUPS / "legacy-mqtt/bridge-mode"
    assert response(lab.request(LEGACY, {"enabled": False}))["bridge_blocked"] is True
    (lab.root / START_LINK / "entry").mkdir(parents=True)

    assert response(lab.request(LEGACY, {"enabled": True}), 500)["error"] == "legacy_mqtt_enable_failed"

    assert bridge.stat().st_mode & 0o7777 == 0o640
    assert record.read_text() == "0750\n"
    assert response(lab.request(LEGACY))["bridge_blocked"] is True


def test_on_creates_no_start_link_when_the_bridge_mode_cannot_come_back(stub_tools, lab):
    legacy_install(lab.root)
    record = lab.root / BACKUPS / "legacy-mqtt/bridge-mode"
    assert response(lab.request(LEGACY, {"enabled": False}))["bridge_blocked"] is True
    # The record cannot be dropped: unblock fails.
    record.unlink()
    (record / "entry").mkdir(parents=True)

    assert response(lab.request(LEGACY, {"enabled": True}), 500)["error"] == "legacy_mqtt_enable_failed"

    assert not (lab.root / START_LINK).exists() and not (lab.root / START_LINK).is_symlink()
