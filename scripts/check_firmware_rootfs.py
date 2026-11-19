#!/usr/bin/env python3
"""Check that a C300X firmware root file system matches the supported baseline.

The native agent is built and ABI-checked against one firmware root file
system, and the display patch edits the vendor GUI files of that firmware. A
second firmware version is supported by the same build only when everything
the agent and its scripts depend on is unchanged. This tool compares a
candidate root file system with the baseline and fails on any difference in:

- the libraries the agent links against or loads at run time,
- the vendor GUI tree the display patch edits,
- the device tools the installer and the agent scripts call,
- the routing target, which must be a build the routing patch knows.

Both root file systems are private local extractions; the repository holds no
firmware. Vendor programs that differ are listed for the device test plan and
do not fail the check.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

# Linked by the ARMHF build, then loaded with dlopen() by the agent.
LIBRARIES = (
    "lib/libc.so.6",
    "lib/ld-linux-armhf.so.3",
    "lib/libpthread.so.0",
    "lib/libdl.so.2",
    "usr/lib/libcurl.so.4",
    "usr/lib/libsrtp.so.1",
    "usr/lib/libspeex.so.1",
)
GUI_TREE = "home/bticino/bin/gui/skins"
VENDOR_PROGRAMS = "home/bticino/bin"
ROUTING_TARGET = "home/bticino/bin/bt_answering_machine"
FIRMWARE_INFO = "home/bticino/sp/dbfiles_ws.xml"
TOOL_DIRS = ("bin", "sbin", "usr/bin", "usr/sbin")
# Called by device_installer.py and native_agent/scripts/*.sh.
TOOLS = (
    "awk", "bash", "cat", "chmod", "cmp", "cp", "dirname", "grep", "iptables",
    "killall", "ln", "mkdir", "mktemp", "mount", "mv", "pidof", "readlink",
    "rm", "setsid", "sha256sum", "sleep", "start-stop-daemon", "stat", "tail",
    "timeout",
)
_MAX_LINKS = 16


def resolve(root: Path, relative: str) -> Path | None:
    """Follow symbolic links inside the root file system, never outside it."""

    current = PurePosixPath("/") / relative
    for _ in range(_MAX_LINKS):
        path = root / str(current).lstrip("/")
        if not path.is_symlink():
            return path if path.exists() else None
        target = PurePosixPath(path.readlink().as_posix())
        current = target if target.is_absolute() else current.parent / target
        parts: list[str] = []
        for part in current.parts[1:]:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        current = PurePosixPath("/", *parts)
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hash(root: Path, relative: str) -> str | None:
    path = resolve(root, relative)
    return sha256(path) if path is not None and path.is_file() else None


def tree_hashes(root: Path, relative: str) -> dict[str, str]:
    base = root / relative
    hashes: dict[str, str] = {}
    if not base.is_dir():
        return hashes
    for path in sorted(base.rglob("*")):
        name = path.relative_to(base).as_posix()
        if path.is_symlink():
            hashes[name] = f"link:{path.readlink().as_posix()}"
        elif path.is_file():
            hashes[name] = sha256(path)
    return hashes


def firmware_version(root: Path) -> str | None:
    path = root / FIRMWARE_INFO
    if not path.is_file():
        return None
    match = re.search(
        r"<ver_webserver>\s*([0-9A-Za-z._-]+)\s*</ver_webserver>",
        path.read_text(encoding="utf-8", errors="replace"),
    )
    return match.group(1) if match else None


def known_routing_hashes() -> set[str]:
    """Stock hashes of the routing target builds the routing patch supports."""

    spec = importlib.util.spec_from_file_location(
        "device_routing_builder", ROOT / "scripts" / "device_routing_builder.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("device_routing_builder.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return {
        value for name, value in vars(module).items()
        if name.startswith("STOCK_SHA256") and isinstance(value, str)
    }


def has_tool(root: Path, tool: str) -> bool:
    return any((root / folder / tool).exists() or (root / folder / tool).is_symlink()
               for folder in TOOL_DIRS)


def compare(
    baseline: Path, candidate: Path, routing_hashes: set[str]
) -> tuple[list[str], list[str]]:
    """Return (failures, notes) for the candidate against the baseline."""

    failures: list[str] = []
    notes: list[str] = []

    for root, label in ((baseline, "baseline"), (candidate, "candidate")):
        version = firmware_version(root)
        if version is None:
            failures.append(f"{label}: firmware version not found in {FIRMWARE_INFO}")
        else:
            notes.append(f"{label} firmware: {version}")

    for library in LIBRARIES:
        expected = file_hash(baseline, library)
        found = file_hash(candidate, library)
        if expected is None:
            failures.append(f"baseline lacks {library}")
        elif found is None:
            failures.append(f"candidate lacks {library}")
        elif found != expected:
            failures.append(f"{library} differs from the baseline")

    expected_gui = tree_hashes(baseline, GUI_TREE)
    found_gui = tree_hashes(candidate, GUI_TREE)
    if not expected_gui:
        failures.append(f"baseline lacks {GUI_TREE}")
    if not found_gui:
        failures.append(f"candidate lacks {GUI_TREE}")
    if expected_gui and found_gui:
        for name in sorted(set(expected_gui) | set(found_gui)):
            if expected_gui.get(name) != found_gui.get(name):
                failures.append(f"{GUI_TREE}/{name} differs from the baseline")

    for tool in TOOLS:
        if has_tool(baseline, tool) and not has_tool(candidate, tool):
            failures.append(f"candidate lacks the device tool {tool}")

    routing = file_hash(candidate, ROUTING_TARGET)
    if routing is None:
        failures.append(f"candidate lacks {ROUTING_TARGET}")
    elif routing not in routing_hashes:
        failures.append(
            f"{ROUTING_TARGET} is not a build the routing patch supports: {routing}"
        )

    expected_programs = tree_hashes(baseline, VENDOR_PROGRAMS)
    found_programs = tree_hashes(candidate, VENDOR_PROGRAMS)
    changed = sorted(
        name for name in set(expected_programs) | set(found_programs)
        if "/" not in name and expected_programs.get(name) != found_programs.get(name)
    )
    if changed:
        notes.append("vendor programs to cover in the device test: " + ", ".join(changed))
    return failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline", type=Path, help="Root file system the agent is built against")
    parser.add_argument("candidate", type=Path, help="Root file system of the other firmware")
    args = parser.parse_args()
    for root in (args.baseline, args.candidate):
        if not root.is_dir():
            sys.stderr.write(f"FAIL: not a directory: {root}\n")
            return 1
    failures, notes = compare(args.baseline, args.candidate, known_routing_hashes())
    for note in notes:
        sys.stdout.write(f"{note}\n")
    for failure in failures:
        sys.stderr.write(f"FAIL: {failure}\n")
    if failures:
        return 1
    sys.stdout.write("Firmware root file system check passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
