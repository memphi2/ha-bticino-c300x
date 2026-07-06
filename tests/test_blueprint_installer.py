from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from custom_components.bticino_c300x.blueprint_installer import (
    async_install_bundled_blueprints,
    install_bundled_blueprints,
)


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
) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    existing = target / "ring_capture.yaml"
    existing.write_text("old bundled blueprint\n", encoding="utf-8")

    result = install_bundled_blueprints(target)

    assert existing.read_text(encoding="utf-8") != "old bundled blueprint\n"
    assert existing in result.updated
    assert existing not in result.installed
    assert (target / "doorbell_notification.yaml").exists()


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
            self.config = SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts)))

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
