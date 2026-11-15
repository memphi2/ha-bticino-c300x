"""Offline checks for reviewer-approved native release reuse."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_hacs_release as builder  # noqa: E402
import check_release_contents as contents  # noqa: E402
import check_repo  # noqa: E402
import native_build_lock as lock  # noqa: E402


@pytest.fixture
def approved(tmp_path):
    root = tmp_path / "checkout"
    for name in lock.INPUT_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("2.3.0\n" if name.endswith("VERSION") else "input\n")
    for name in lock.INPUT_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "source").write_text("source\n")
    data = b"reviewed stripped executable"
    manifest = {"schema": 1, "agent_version": "2.3.0",
                "inputs_sha256": lock.input_digest(root),
                "binary_sha256": hashlib.sha256(data).hexdigest()}
    (root / lock.LOCK_PATH).write_text(json.dumps(manifest))
    return root, data


def archive_at(path, data):
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(lock.BINARY_MEMBER, data)
        zipped.writestr("device_agent/bundle.json", json.dumps({
            "agent_version": "2.3.0", "sha256": hashlib.sha256(data).hexdigest(),
        }))
    return path


def test_old_executable_current_metadata_rejected(approved, tmp_path):
    root, data = approved
    archive = archive_at(tmp_path / "release.zip", b"old executable")
    with pytest.raises(ValueError, match="reviewed build lock"):
        lock.validate_archive(archive, root=root)
    archive_at(archive, data)
    lock.validate_archive(archive, root=root)


def test_contents_checker_requires_lock_even_when_extracted_binary_matches(approved, tmp_path, monkeypatch):
    root, _ = approved
    old = tmp_path / "old-agent"
    old.write_bytes(b"old executable")
    archive = archive_at(tmp_path / "release.zip", old.read_bytes())
    monkeypatch.setattr(contents, "ROOT", root)
    with pytest.raises(ValueError, match="reviewed build lock"):
        contents.validate_release_contents(archive, agent_binary=old,
                                           build_lock=root / lock.LOCK_PATH)


@pytest.mark.parametrize("change", ["edit", "add", "delete", "rename", "flags", "version"])
def test_input_changes_invalidate_lock(approved, change):
    root, data = approved
    path = root / "native_agent/src/source"
    if change == "edit":
        path.write_text("new source")
    elif change == "add":
        (path.parent / "untracked.c").write_text("new source")
    elif change == "delete":
        path.unlink()
    elif change == "rename":
        path.rename(path.with_name("renamed"))
    elif change == "flags":
        (root / "native_agent/Makefile").write_text("CFLAGS=-O3")
    else:
        (root / "native_agent/VERSION").write_text("2.4.0")
    with pytest.raises(ValueError, match="differs|differ"):
        lock.validate_binary(data, root=root)


def test_lock_and_build_outputs_are_not_self_referential(approved):
    root, _ = approved
    before = lock.input_digest(root)
    (root / lock.LOCK_PATH).write_text("updated review record")
    (root / "native_agent/build").mkdir()
    (root / "native_agent/build/agent").write_bytes(b"output")
    assert lock.input_digest(root) == before


@pytest.mark.parametrize("path", check_repo.NATIVE_AGENT_BUNDLE_INPUT_PATHS)
def test_repo_gate_rejects_omitted_lock_input(monkeypatch, path):
    monkeypatch.setattr(lock, "INPUT_DIRS", tuple(p for p in lock.INPUT_DIRS if p != path))
    monkeypatch.setattr(lock, "INPUT_FILES", tuple(p for p in lock.INPUT_FILES if p != path))
    assert f"native build lock must gate agent reuse on {path}" in check_repo.check_hacs_metadata()


def test_missing_lock_fails_closed(approved):
    root, data = approved
    (root / lock.LOCK_PATH).unlink()
    with pytest.raises(FileNotFoundError):
        lock.validate_binary(data, root=root)


@pytest.mark.parametrize("content", ["{", "[]", '{"schema": 2}'])
def test_malformed_lock_fails_closed(approved, content):
    root, data = approved
    (root / lock.LOCK_PATH).write_text(content)
    with pytest.raises(ValueError):
        lock.validate_binary(data, root=root)


@pytest.mark.parametrize("digest", [None, "", "g" * 64, "a" * 63, 123])
def test_invalid_binary_digest_fails_closed(approved, digest):
    root, data = approved
    path = root / lock.LOCK_PATH
    manifest = json.loads(path.read_text())
    manifest["binary_sha256"] = digest
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="binary SHA256"):
        lock.validate_binary(data, root=root)


@pytest.mark.parametrize("copies", [0, 2])
def test_archive_requires_exactly_one_executable(approved, tmp_path, copies):
    root, data = approved
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        if copies:
            zipped.writestr(lock.BINARY_MEMBER, data)
            with pytest.warns(UserWarning, match="Duplicate name"):
                zipped.writestr(lock.BINARY_MEMBER, data)
    with pytest.raises(ValueError, match="missing or duplicate"):
        lock.validate_archive(archive, root=root)


def test_generation_failure_preserves_existing_lock(approved, tmp_path, monkeypatch):
    root, _ = approved
    path = root / lock.LOCK_PATH
    before = path.read_bytes()
    binary = tmp_path / "not-elf"
    binary.write_bytes(b"not an executable")
    monkeypatch.setattr(sys, "argv", ["native_build_lock.py", "--generate", str(binary),
                                     "--lock", str(path)])
    with pytest.raises(ValueError, match="ELF executable"):
        lock.main()
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["--check-inputs", "--zip", "--generate"])
def test_cli_forwards_selected_lock_and_inputs(tmp_path, monkeypatch, mode):
    path = tmp_path / "reviewed.json"
    artifact = tmp_path / "artifact"
    settings = tmp_path / "settings"
    calls = []
    monkeypatch.setattr(lock, "read_lock", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(lock, "validate_archive", lambda archive, **kwargs: calls.append((archive, kwargs)))

    def generate(binary, build_settings):
        calls.append((binary, build_settings))
        return {"test": "generated"}

    monkeypatch.setattr(lock, "generate", generate)
    args = ["native_build_lock.py", mode]
    if mode != "--check-inputs":
        args.append(str(artifact))
    monkeypatch.setattr(sys, "argv", args + ["--lock", str(path), "--build-settings", str(settings)])
    lock.main()
    if mode == "--check-inputs":
        assert calls == [{"lock_path": path}]
    elif mode == "--zip":
        assert calls == [(artifact, {"lock_path": path})]
    else:
        assert calls == [(artifact, settings)]
        assert json.loads(path.read_text()) == {"test": "generated"}


def test_restore_rejects_before_overwriting_existing_build(approved, tmp_path, monkeypatch):
    root, _ = approved
    binary = tmp_path / "agent"
    binary.write_bytes(b"existing build")
    monkeypatch.setattr(builder, "ROOT", root)
    monkeypatch.setattr(builder, "AGENT_BINARY", binary)
    with pytest.raises(ValueError, match="reviewed build lock"):
        builder._restore_agent_from_release_zip(archive_at(tmp_path / "bad.zip", b"old"))
    assert binary.read_bytes() == b"existing build"


def test_generation_hashes_stripped_copy_and_records_settings(approved, tmp_path, monkeypatch):
    root, _ = approved
    binary = tmp_path / "agent"
    binary.write_bytes(b"\x7fELFwith symbols")
    settings = tmp_path / "build-settings"
    settings.write_text("2.3.0\n/home/private-user/toolchain/bin/gcc\n-L/private/rootfs/lib\n")

    def strip(source, target):
        assert source == binary
        target.write_bytes(b"stripped")
        return target

    monkeypatch.setattr(lock, "_copy_agent_binary", strip)
    generated = lock.generate(binary, settings, root=root)
    assert generated["binary_sha256"] == hashlib.sha256(b"stripped").hexdigest()
    assert generated["inputs_sha256"] == lock.input_digest(root)
    assert generated["local_build_settings_sha256"] == hashlib.sha256(settings.read_bytes()).hexdigest()
    assert "private" not in json.dumps(generated)
    assert binary.read_bytes() == b"\x7fELFwith symbols"


@pytest.mark.parametrize("accepted", ["v2.3.0", "v2.2.0", "none"])
def test_workflow_checks_same_tag_and_older_bytes_offline(tmp_path, accepted):
    workflow = yaml.safe_load((lock.ROOT / ".github/workflows/release.yml").read_text())
    resolve = next(step["run"] for step in workflow["jobs"]["publish"]["steps"]
                   if step.get("id") == "reusable-agent")
    # Stub every external operation: no network, compiler, or real release.
    stubs = '''
    python() {
      case "$1:$2" in
        scripts/native_build_lock.py:--check-inputs) return 0 ;;
        scripts/release_version.py:*) printf 'v2.2.0\\n' ;;
        scripts/native_build_lock.py:--zip) [ "$(cat "$3")" = "$ACCEPTED" ] ;;
        *) return 90 ;;
      esac
    }
    gh() { printf '%s' "$3" > .release/reuse/ha-bticino-c300x.zip; }
    '''
    output = tmp_path / "output"
    result = subprocess.run(["bash", "-c", stubs + resolve], cwd=tmp_path,
                            env={**os.environ, "C300X_DEVICE_SYSROOT": "",
                                 "RELEASE_TAG": "v2.3.0", "ACCEPTED": accepted,
                                 "GITHUB_OUTPUT": str(output)}, capture_output=True, text=True)
    assert result.returncode == (1 if accepted == "none" else 0), result.stderr
    if accepted == "none":
        assert not output.exists()
    else:
        assert f"reused_from={accepted}\n" in output.read_text()
