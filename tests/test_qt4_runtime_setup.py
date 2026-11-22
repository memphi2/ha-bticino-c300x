"""Offline Qt 4 setup is reproducible and never silently uses stale probes."""

import hashlib
import json
import os
import subprocess

import pytest

from scripts import setup_qt4_runtime as setup


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    for key in setup.KEYS:
        monkeypatch.delenv("C300X_QT4_" + key, raising=False)
    return setup.cache_directory()


def cached_runtime(cache):
    cache.mkdir(parents=True)
    paths = [cache / name for name in ("qemu", "rootfs", "probe", "imports")]
    for index, path in enumerate(paths):
        if index in (1, 3):
            path.mkdir()
        else:
            path.write_bytes(b"placeholder")
            path.chmod(0o700)
    manifest = {"schema": 1, "source_sha256": setup.source_digest(),
                "binary_sha256": hashlib.sha256(paths[2].read_bytes()).hexdigest(),
                "paths": [str(path) for path in paths]}
    (cache / "environment.json").write_text(json.dumps(manifest))
    return manifest


def test_missing_optional_runtime(isolated_cache):
    assert setup.runtime_paths() is None


def test_cached_runtime_is_discovered(isolated_cache):
    manifest = cached_runtime(isolated_cache)
    assert setup.runtime_paths() == manifest["paths"]


@pytest.mark.parametrize("fault", ["source", "binary", "missing", "schema", "paths"])
def test_stale_or_broken_setup_fails_instead_of_skipping(isolated_cache, fault):
    manifest = cached_runtime(isolated_cache)
    if fault == "source":
        manifest["source_sha256"] = "stale"
    elif fault == "schema":
        manifest["schema"] = 0
    elif fault == "paths":
        manifest["paths"] = {"invalid": True}
    elif fault == "missing":
        (isolated_cache / "probe").unlink()
    else:
        (isolated_cache / "probe").write_bytes(b"changed")
    (isolated_cache / "environment.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        setup.runtime_paths()


def test_partial_explicit_setup_is_not_silently_ignored(isolated_cache, monkeypatch):
    cached_runtime(isolated_cache)
    monkeypatch.setenv("C300X_QT4_QEMU", "/does/not/exist")
    with pytest.raises(ValueError):
        setup.runtime_paths()


def test_explicit_setup_takes_precedence(isolated_cache, monkeypatch):
    paths = cached_runtime(isolated_cache)["paths"]
    for key, path in zip(setup.KEYS, paths, strict=True):
        monkeypatch.setenv("C300X_QT4_" + key, path)
    (isolated_cache / "environment.json").write_text("invalid cached JSON")
    assert setup.runtime_paths() == paths


def test_sysroot_is_never_used_as_build_output(isolated_cache):
    isolated_cache.mkdir(parents=True)
    with pytest.raises(ValueError, match="outside"):
        setup.install(isolated_cache, "cc", "qemu-arm")
    assert not list(isolated_cache.iterdir())


def test_runtime_rejects_invalid_qml(tmp_path):
    paths = setup.runtime_paths()
    if paths is None:
        pytest.skip("Optional Qt 4 firmware runtime is not configured")
    source = tmp_path / "Invalid.qml"
    source.write_text("import QtQuick 1.1\nItem { definitelyMissingProperty: true }\n")
    result = subprocess.run(setup.probe_command(paths, source),
                            env={**os.environ, "PROBE_CREATE": "1"}, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "definitelyMissingProperty" in result.stderr
