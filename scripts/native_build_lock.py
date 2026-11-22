#!/usr/bin/env python3
"""Record reviewer-approved native bytes and source inputs, not compiler provenance.

Generate only after a clean local ARM build and ABI checks, then review and commit
native_agent/build-lock.json with the release sources. External sysroot/toolchain
contents are not attested by this lock. Makefile flags are covered; actual local
build-settings are hashed for review, not independently verified by CI. Raw
settings can contain private toolchain/sysroot paths and are never recorded.

After the final reviewed source changes (from repository root):
    make -C native_agent clean
    C300X_DEVICE_SYSROOT=/private/rootfs make -C native_agent armhf armhf-abi-check
    python scripts/native_build_lock.py --generate native_agent/build/armhf/c300x-agent-native
    python scripts/build_hacs_release.py --skip-build
    python scripts/check_release_contents.py .release/ha-bticino-c300x.zip \
        --agent-binary native_agent/build/armhf/c300x-agent-native \
        --build-lock native_agent/build-lock.json

Review the generated lock with the release sources. The same-tag draft ZIP is
only a binary transport: hosted CI validates its executable against this lock
and regenerates the entire bundle/package from the release checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from stage_device_agent_bundle import _copy_agent_binary

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path("native_agent/build-lock.json")
BINARY_MEMBER = "device_agent/armhf/c300x-agent-native"
INPUT_DIRS = (
    "native_agent/src", "native_agent/scripts", "device_qml",
    "custom_components/bticino_c300x/device_agent/init",
)
INPUT_FILES = (
    "native_agent/Makefile", "native_agent/VERSION", "native_agent/config.example.json",
    "scripts/stage_device_agent_bundle.py", "scripts/device_file_strip.py",
    "scripts/c100x_bundle_builder.py", "scripts/c100x_qml_builder.py",
    "scripts/build_hacs_release.py", "scripts/check_agent_abi.py",
    "scripts/native_build_lock.py",
)


def input_digest(root: Path) -> str:
    """Hash sorted path/content pairs, including new untracked source files.

    Build outputs and the lock itself are excluded. Bundle inputs are included
    conservatively: even display-only changes need renewed reviewer approval,
    though they need not change executable bytes. Deletions and renames count.
    """
    paths = {root / name for name in INPUT_FILES}
    for name in INPUT_DIRS:
        directory = root / name
        if not directory.is_dir():
            raise ValueError(f"missing native input directory: {name}")
        paths.update(path for path in directory.rglob("*") if path.is_file())
    entries = []
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError(f"symlink native input: {path}")
        entries.append([path.relative_to(root).as_posix(),
                        hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def read_lock(root: Path = ROOT, lock_path: Path | None = None) -> dict:
    lock = json.loads((lock_path or root / LOCK_PATH).read_text())
    if not isinstance(lock, dict) or lock.get("schema") != 1:
        raise ValueError("unsupported native build lock")
    if lock.get("agent_version") != (root / "native_agent/VERSION").read_text().strip():
        raise ValueError("native build lock version differs from checkout")
    if lock.get("inputs_sha256") != input_digest(root):
        raise ValueError("native build lock inputs differ from checkout")
    digest = lock.get("binary_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid native build lock binary SHA256")
    return lock


def validate_binary(data: bytes, *, root: Path = ROOT, lock_path: Path | None = None) -> None:
    lock = read_lock(root, lock_path)
    if hashlib.sha256(data).hexdigest() != lock["binary_sha256"]:
        raise ValueError("native executable differs from reviewed build lock")


def validate_archive(archive: Path, *, root: Path = ROOT, lock_path: Path | None = None) -> None:
    with zipfile.ZipFile(archive) as zipped:
        if zipped.namelist().count(BINARY_MEMBER) != 1:
            raise ValueError("missing or duplicate native executable")
        validate_binary(zipped.read(BINARY_MEMBER), root=root, lock_path=lock_path)


def generate(binary: Path, settings: Path, *, root: Path = ROOT) -> dict:
    if binary.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("native build lock requires an ELF executable")
    with tempfile.TemporaryDirectory() as temporary:
        stripped = _copy_agent_binary(binary, Path(temporary) / "agent")
        digest = hashlib.sha256(stripped.read_bytes()).hexdigest()
    return {"schema": 1,
            "agent_version": (root / "native_agent/VERSION").read_text().strip(),
            "inputs_sha256": input_digest(root), "binary_sha256": digest,
            "local_build_settings_sha256": hashlib.sha256(settings.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--generate", type=Path, metavar="BINARY")
    mode.add_argument("--zip", type=Path)
    mode.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--lock", type=Path, default=ROOT / LOCK_PATH)
    parser.add_argument("--build-settings", type=Path,
                        default=ROOT / "native_agent/build/armhf/build-settings")
    args = parser.parse_args()
    if args.generate:
        lock = generate(args.generate, args.build_settings)
        args.lock.write_text(json.dumps(lock, indent=2) + "\n")
    elif args.zip:
        validate_archive(args.zip, lock_path=args.lock)
    else:
        read_lock(lock_path=args.lock)


if __name__ == "__main__":
    main()
