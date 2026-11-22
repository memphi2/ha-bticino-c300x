"""One bounded updater entry for the isolated C100X disk adapter.

Fixed text members avoid archive path interpretation and codecs absent from the
original firmware. Extraction never installs or restarts the GUI by itself.
"""

from hashlib import sha256
from pathlib import Path
import re
import tempfile

from c100x_qml_builder import ROOT, build as build_qml

MEMBER = "device_agent/qml/c100x_bundle.sh"
SCRIPTS = ("c100x_display.sh", "c100x_display_identity.sh", "c100x_display_trial.sh", "c100x_display_probe.sh", "c100x_hooks.awk")
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
HEADER = '''#!/bin/sh
set -eu
umask 077
ACTION=${1:-status}
case "$ACTION" in apply|prepare|confirm|status|restore|recover) ;; *) exit 1 ;; esac
WORK=$(mktemp -d "${TMPDIR:-/tmp}/c100x-payload.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
trap 'exit 1' HUP INT TERM
mkdir "$WORK/source" "$WORK/source/js" "$WORK/source/hooks"
'''
FOOTER = '''
export C100X_SOURCE_DIR="$WORK/source"
export C100X_IDENTITY_SCRIPT="$WORK/c100x_display_identity.sh"
export C100X_HOOKS_AWK="$WORK/c100x_hooks.awk"
export C100X_TRIAL_SCRIPT="$WORK/c100x_display_trial.sh"
export C100X_PROBE_SCRIPT="$WORK/c100x_display_probe.sh"
sh "$WORK/c100x_display.sh" "$ACTION"
'''


def _member(name: str, data: bytes) -> bytes:
    if not re.fullmatch(r"(?:source/)?(?:(?:js|hooks)/)?[A-Za-z0-9_.]+", name):
        raise ValueError("Unsafe C100X payload member")
    if not data.endswith(b"\n") or b"\0" in data:
        raise ValueError("C100X payload requires newline-terminated text")
    digest = sha256(data).hexdigest()
    delimiter = "C100X_" + digest
    if delimiter.encode() in data.splitlines():
        raise ValueError("C100X payload delimiter collision")
    return (
        f'cat > "$WORK/{name}" <<\'{delimiter}\'\n'.encode() + data
        + f'{delimiter}\n[ "$(sha256sum "$WORK/{name}" | awk \'{{print $1}}\')" = "{digest}" ]\n'.encode()
    )


def build(destination: Path, *, root: Path = ROOT) -> Path:
    """Build from a dedicated fresh tree; preserve all unrelated staging paths."""
    with tempfile.TemporaryDirectory(prefix="c100x-bundle-") as directory:
        source = Path(directory) / "qml"
        build_qml(source, root / "device_qml")
        content = bytearray(HEADER.encode())
        for name in SCRIPTS:
            content.extend(_member(name, (root / "native_agent/scripts" / name).read_bytes()))
        # Recovery needs only the reviewed recipes and backups, not QML sources.
        content.extend(b'if [ "$ACTION" = apply ] || [ "$ACTION" = prepare ]; then\n')
        for path in sorted(source.rglob("*")):
            if path.is_file():
                content.extend(_member("source/" + path.relative_to(source).as_posix(), path.read_bytes()))
        content.extend(b"fi\n")
        content.extend(FOOTER.encode())
    if len(content) > MAX_PAYLOAD_BYTES:
        raise ValueError("C100X payload exceeds bounded delivery size")
    if destination.is_symlink():
        raise ValueError("C100X payload output must not be a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    destination.chmod(0o700)
    return destination
