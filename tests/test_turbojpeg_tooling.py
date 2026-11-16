"""Pinned dev-only TurboJPEG setup must fail closed and never unpack paths."""

import hashlib
import io
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import check_turbojpeg, setup_turbojpeg


def archive_bytes(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, kind, payload in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = "../../outside"
            member.size = len(payload) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


@pytest.fixture
def pinned(monkeypatch):
    package = b"verified test package"
    monkeypatch.setattr(setup_turbojpeg, "ASSET_SIZE", len(package))
    monkeypatch.setattr(setup_turbojpeg, "SHA256", hashlib.sha256(package).hexdigest())
    monkeypatch.setattr(setup_turbojpeg, "LIBRARY_SIZE", 4)
    return package


def test_package_hash_and_size_are_both_required(pinned):
    setup_turbojpeg.verify_package(pinned)
    for bad in (pinned[:-1], pinned + b"x", b"x" * len(pinned)):
        with pytest.raises(ValueError, match="size/SHA256 mismatch"):
            setup_turbojpeg.verify_package(bad)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_library_member_rejects_links_and_special_files(pinned, kind):
    archive = archive_bytes([(setup_turbojpeg.LIBRARY_MEMBER, kind, b"")])
    with pytest.raises(ValueError, match="regular file"):
        setup_turbojpeg.library_payload(archive)


@pytest.mark.parametrize("name", ["/opt/libjpeg-turbo/lib64/libturbojpeg.so.0.5.0", "../../outside", "./opt/../opt/libjpeg-turbo/lib64/libturbojpeg.so.0.5.0"])
def test_unexpected_member_paths_are_not_accepted(pinned, name):
    with pytest.raises(ValueError, match="exactly one"):
        setup_turbojpeg.library_payload(archive_bytes([(name, tarfile.REGTYPE, b"test")]))


def test_duplicate_missing_and_wrong_sized_payloads_fail(pinned):
    member = (setup_turbojpeg.LIBRARY_MEMBER, tarfile.REGTYPE, b"test")
    for entries in ([], [member, member], [(member[0], member[1], b"short")]):
        with pytest.raises(ValueError):
            setup_turbojpeg.library_payload(archive_bytes(entries))


def test_only_pinned_payload_is_read_even_with_hostile_unrelated_members(pinned):
    data = archive_bytes([
        ("../../outside", tarfile.REGTYPE, b"bad"),
        ("./opt/libjpeg-turbo/doc", tarfile.SYMTYPE, b""),
        (setup_turbojpeg.LIBRARY_MEMBER, tarfile.REGTYPE, b"test"),
    ])
    assert setup_turbojpeg.library_payload(data) == b"test"


def test_install_verifies_cached_package_and_repairs_only_library(tmp_path, monkeypatch, pinned):
    package = tmp_path / setup_turbojpeg.ASSET
    package.write_bytes(pinned)
    data = archive_bytes([(setup_turbojpeg.LIBRARY_MEMBER, tarfile.REGTYPE, b"test")])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[:2] == ["dpkg-deb", "--fsys-tarfile"]
        assert Path(command[2]).read_bytes() == pinned
        assert Path(command[2]) != package
        return SimpleNamespace(stdout=data)

    monkeypatch.setattr(setup_turbojpeg.subprocess, "run", run)
    library = setup_turbojpeg.install(tmp_path)
    assert library.read_bytes() == b"test"
    inode = library.stat().st_ino
    assert setup_turbojpeg.install(tmp_path).stat().st_ino == inode
    library.write_bytes(b"corrupt")
    assert setup_turbojpeg.install(tmp_path).read_bytes() == b"test"
    package.write_bytes(b"x" * len(pinned))
    with pytest.raises(ValueError, match="SHA256"):
        setup_turbojpeg.install(tmp_path)
    assert len(calls) == 3
    assert library.read_bytes() == b"test"
    assert not list(tmp_path.glob(".turbojpeg-*"))


def test_download_is_pinned_and_bounded_before_dpkg(tmp_path, monkeypatch, pinned):
    class Response(io.BytesIO):
        url = setup_turbojpeg.URL

    urls = []

    def download(url, **kwargs):
        urls.append(url)
        assert kwargs["timeout"] == 60
        return Response(b"x" * (len(pinned) + 100))

    monkeypatch.setattr(setup_turbojpeg.urllib.request, "urlopen", download)
    monkeypatch.setattr(setup_turbojpeg.subprocess, "run", lambda *a, **k: pytest.fail("unverified package parsed"))
    with pytest.raises(ValueError, match="SHA256"):
        setup_turbojpeg.install(tmp_path)
    assert urls == [setup_turbojpeg.URL]
    assert not (tmp_path / setup_turbojpeg.ASSET).exists()


def test_cache_cannot_be_in_repository():
    with pytest.raises(ValueError, match="outside the repository"):
        setup_turbojpeg.install(setup_turbojpeg.ROOT / ".artifacts/turbojpeg")


def test_loader_path_preserves_existing_entries_without_empty_or_duplicate(tmp_path, monkeypatch):
    library = tmp_path / "libturbojpeg.so.0"
    monkeypatch.setenv("LD_LIBRARY_PATH", f":/existing::{tmp_path}:/existing:")
    assert setup_turbojpeg.loader_path(library) == f"{tmp_path}:/existing"
    monkeypatch.setenv("LD_LIBRARY_PATH", "/existing\nINJECT=value")
    with pytest.raises(ValueError, match="newlines"):
        setup_turbojpeg.loader_path(library)


@pytest.mark.parametrize("directory", ["bad\npath", "bad\rpath", "bad:path"])
def test_cache_path_cannot_inject_export(directory):
    with pytest.raises(ValueError, match="newlines or colons"):
        setup_turbojpeg.loader_path(Path(directory) / "libturbojpeg.so.0")


@pytest.mark.parametrize("success", [True, False])
def test_github_export_only_after_verified_subprocess(tmp_path, monkeypatch, capsys, success):
    library = tmp_path / "lib/libturbojpeg.so.0"
    output = tmp_path / "github-env"
    monkeypatch.setattr(sys, "argv", ["setup_turbojpeg.py", "--github-env"])
    monkeypatch.setenv("GITHUB_ENV", str(output))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/existing")
    monkeypatch.setattr(setup_turbojpeg.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup_turbojpeg.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(setup_turbojpeg, "install", lambda cache: library)

    def run(command, **kwargs):
        assert command[0] == sys.executable
        assert command[-2:] == ["--expect-library", str(library)]
        assert kwargs["env"]["LD_LIBRARY_PATH"] == f"{library.parent}:/existing"
        assert kwargs["check"]
        if not success:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(setup_turbojpeg.subprocess, "run", run)
    assert setup_turbojpeg.main() == (0 if success else 1)
    if success:
        assert output.read_text() == f"LD_LIBRARY_PATH={library.parent}:/existing\n"
        assert capsys.readouterr().out == f"{library.parent}\n"
    else:
        assert not output.exists()
        assert capsys.readouterr().out == ""


def test_unsupported_platform_fails_before_download(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["setup_turbojpeg.py"])
    monkeypatch.setattr(setup_turbojpeg.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(setup_turbojpeg, "install", lambda cache: pytest.fail("unsupported install"))
    assert setup_turbojpeg.main() == 1


@pytest.mark.parametrize("workflow", ["validate.yml", "release.yml"])
def test_both_workflows_keep_matrix_and_verify_turbojpeg_before_gate(workflow):
    document = yaml.safe_load((setup_turbojpeg.ROOT / ".github/workflows" / workflow).read_text())
    job = document["jobs"]["validate"]
    assert {leg["name"] for leg in job["strategy"]["matrix"]["include"]} == {"min-ha", "current-ha"}
    steps = job["steps"]
    setup = next(i for i, step in enumerate(steps) if step.get("run") == "python scripts/setup_turbojpeg.py --github-env")
    gate = next(i for i, step in enumerate(steps) if step.get("run") == "python scripts/check_validate.py")
    assert setup < gate
    assert "if" not in steps[setup]
    assert "continue-on-error" not in steps[setup]
    assert "libturbojpeg0" not in str(steps)


def test_runtime_check_error_is_a_gate_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_turbojpeg.py"])

    def fail(expected):
        raise RuntimeError("no TurboJPEG 3")

    monkeypatch.setattr(check_turbojpeg, "check", fail)
    assert check_turbojpeg.main() == 1
    assert "no TurboJPEG 3" in capsys.readouterr().err
