"""Check init-to-child path inheritance without executing maintenance actions."""

import subprocess
from pathlib import Path


def test_init_exports_effective_maintenance_paths(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env_file = tmp_path / "agent.env"
    env_file.write_text("C300X_AGENT_DIR='/custom/agent'\nC300X_BACKUP_ROOT='/custom/backups'\n")
    init = (root / "custom_components/bticino_c300x/device_agent/init/c300x-native-agent").read_text()
    prefix = init.split('[ -f /etc/init.d/functions ]')[0]
    for script, stop, expected in (
        ("qml_patch.sh", "NO_REMOUNT=", "/custom/agent/qml|/custom/backups/original/gui/skins/default"),
        ("remove_agent.sh", "QML_PATCH=", "/custom/agent|/custom/backups"),
    ):
        source = (root / "native_agent/scripts" / script).read_text().split(stop)[0]
        fields = '"$SOURCE_DIR|$BACKUP_DIR"' if script == "qml_patch.sh" else '"$AGENT_DIR|$BACKUP_ROOT"'
        child = tmp_path / script
        child.write_text(source + f"\nprintf '%s' {fields}\n")
        result = subprocess.run(["sh", "-c", prefix + '\nsh "$1"', "test", str(child)],
                                env={"C300X_AGENT_ENV": str(env_file)}, check=True,
                                capture_output=True, text=True)
        assert result.stdout == expected
