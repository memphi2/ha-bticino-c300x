from __future__ import annotations

import asyncio
import re
import subprocess
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from custom_components.bticino_c300x import blueprint_installer as installer_module
from custom_components.bticino_c300x.blueprint_installer import (
    async_install_bundled_blueprints,
    install_bundled_blueprints,
)

ROOT = Path(__file__).resolve().parents[1]


def _pre_manifest_tags() -> list[str]:
    """Return release tags older than 1.8.0, where the manifest was added."""

    tags = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout.split()
    versions = []
    for tag in tags:
        # Ignore anything that is not a plain vX.Y.Z release tag, so a future
        # pre-release like v1.10.0-rc1 cannot break this with a ValueError.
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
        if match is not None:
            versions.append((tuple(int(part) for part in match.groups()), tag))
    return [tag for version, tag in sorted(versions) if version < (1, 8, 0)]


def _released_digests(filename: str) -> frozenset[str]:
    """Return every content digest a pre-manifest release shipped for a file."""

    path = f"custom_components/bticino_c300x/blueprints/automation/bticino_c300x/{filename}"
    digests = set()
    for tag in _pre_manifest_tags():
        blob = subprocess.run(
            ["git", "show", f"{tag}:{path}"],
            capture_output=True,
            check=False,
            cwd=ROOT,
        )
        if blob.returncode == 0:
            digests.add(sha256(blob.stdout).hexdigest())
    return frozenset(digests)


def _legacy_release_bytes(filename: str) -> bytes:
    """Return the oldest shipped content for one bundled blueprint."""

    path = f"custom_components/bticino_c300x/blueprints/automation/bticino_c300x/{filename}"
    for tag in _pre_manifest_tags():
        blob = subprocess.run(
            ["git", "show", f"{tag}:{path}"],
            capture_output=True,
            check=False,
            cwd=ROOT,
        )
        if blob.returncode == 0:
            return blob.stdout
    raise AssertionError(f"no pre-manifest release shipped {filename}")


def test_install_bundled_blueprints_copies_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"

    result = install_bundled_blueprints(target)

    assert {path.name for path in result.installed} == {
        "doorbell_call_android.yaml",
        "doorbell_call_ios.yaml",
        "doorbell_notification.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
        "strict_phrase_decision.yaml",
    }
    assert result.updated == []
    assert result.removed == []
    assert result.changed is True
    assert (target / "ring_capture.yaml").exists()


def test_install_bundled_blueprints_updates_existing_managed_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    source = tmp_path / "source"
    source.mkdir()
    bundled = source / "ring_capture.yaml"
    bundled.write_text("old bundled blueprint\n", encoding="utf-8")
    monkeypatch.setattr(installer_module, "_SOURCE_DIR", source)

    installed = install_bundled_blueprints(target)
    assert target / "ring_capture.yaml" in installed.installed

    bundled.write_text("new bundled blueprint\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    existing = target / "ring_capture.yaml"
    assert existing.read_text(encoding="utf-8") == "new bundled blueprint\n"
    assert existing in result.updated
    assert existing not in result.installed


def test_install_bundled_blueprints_preserves_customized_bundled_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    existing = target / "ring_capture.yaml"
    existing.write_text("user edited\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    assert existing.read_text(encoding="utf-8") == "user edited\n"
    assert existing not in result.updated
    assert existing not in result.installed
    assert (target / "doorbell_notification.yaml").exists()


def test_install_bundled_blueprints_preserves_modified_managed_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    installed = install_bundled_blueprints(target)
    assert installed.installed
    existing = target / "ring_capture.yaml"
    existing.write_text("user edited after install\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    assert existing.read_text(encoding="utf-8") == "user edited after install\n"
    assert existing not in result.updated
    assert existing not in result.installed


def test_install_bundled_blueprints_preserves_extra_files(tmp_path: Path) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    extra = target / "local_experiment.yaml"
    extra.write_text("user edited\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    assert extra.read_text(encoding="utf-8") == "user edited\n"
    assert extra not in result.installed
    assert extra not in result.updated


def test_install_bundled_blueprints_removes_obsolete_bundles(tmp_path: Path) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    obsolete_files = {
        target / "doorbell_call_mobile_dashboard.yaml",
        target / "doorbell_call_notification.yaml",
    }
    for obsolete in obsolete_files:
        obsolete.write_text("old bundled blueprint\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    assert all(not obsolete.exists() for obsolete in obsolete_files)
    assert set(result.removed) == obsolete_files


def test_async_install_bundled_blueprints_reloads_running_automations(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str, dict[str, object], bool]] = []
    tasks: list[asyncio.Task[None]] = []

    class _Services:
        def has_service(self, domain: str, service: str) -> bool:
            return domain == "automation" and service == "reload"

        async def async_call(
            self,
            domain: str,
            service: str,
            data: dict[str, object],
            *,
            blocking: bool,
        ) -> None:
            calls.append((domain, service, data, blocking))

    class _Hass:
        is_running = True
        services = _Services()
        bus = SimpleNamespace(async_listen_once=lambda *_args: None)

        def __init__(self) -> None:
            self.config = SimpleNamespace(
                path=lambda *parts: str(tmp_path.joinpath(*parts))
            )

        async def async_add_executor_job(self, func, *args):  # type: ignore[no-untyped-def]
            return func(*args)

        def async_create_task(self, coro):  # type: ignore[no-untyped-def]
            task = asyncio.create_task(coro)
            tasks.append(task)
            return task

    async def _run() -> None:
        await async_install_bundled_blueprints(_Hass())  # type: ignore[arg-type]
        await asyncio.gather(*tasks)

    asyncio.run(_run())

    assert calls == [("automation", "reload", {}, False)]


def test_install_bundled_blueprints_updates_pristine_pre_manifest_copies(
    tmp_path: Path,
) -> None:
    """Installs from before the manifest (1.8.0) have no manifest entry, so an
    untouched old blueprint looked customized and would never receive another
    fix. A copy matching known shipped content is adopted and updated."""

    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    legacy = target / "doorbell_call_android.yaml"
    legacy_bytes = _legacy_release_bytes("doorbell_call_android.yaml")
    legacy.write_bytes(legacy_bytes)
    packaged = (
        installer_module._SOURCE_DIR / "doorbell_call_android.yaml"
    ).read_bytes()
    assert legacy_bytes != packaged

    result = install_bundled_blueprints(target)

    assert legacy.read_bytes() == packaged
    assert legacy in result.updated


def test_install_bundled_blueprints_still_preserves_unknown_pre_manifest_edits(
    tmp_path: Path,
) -> None:
    """Adoption is by known content only: an edited pre-manifest file does not
    match any shipped digest and must survive untouched."""

    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    edited = target / "doorbell_call_android.yaml"
    edited.write_bytes(
        _legacy_release_bytes("doorbell_call_android.yaml") + b"\n# my edit\n"
    )

    result = install_bundled_blueprints(target)

    assert edited.read_bytes().endswith(b"# my edit\n")
    assert edited not in result.updated


def test_legacy_shipped_digests_match_real_release_history() -> None:
    """The digest table must describe what was actually shipped, so build it
    from git rather than trusting hand-copied hashes."""

    for filename, digests in installer_module._LEGACY_SHIPPED_DIGESTS.items():
        assert digests == _released_digests(filename), filename
        assert (installer_module._SOURCE_DIR / filename).exists(), filename


def test_install_bundled_blueprints_keeps_a_deliberate_downgrade(
    tmp_path: Path,
) -> None:
    """Restoring an older shipped blueprint is the usual workaround when a new
    one breaks a setup. With a manifest entry that choice is tracked, so legacy
    content must not be adopted back over it."""

    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    install_bundled_blueprints(target)
    downgraded = target / "doorbell_call_android.yaml"
    legacy_bytes = _legacy_release_bytes("doorbell_call_android.yaml")
    downgraded.write_bytes(legacy_bytes)

    result = install_bundled_blueprints(target)

    assert downgraded.read_bytes() == legacy_bytes
    assert downgraded not in result.updated
