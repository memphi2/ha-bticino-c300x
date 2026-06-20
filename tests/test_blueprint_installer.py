from __future__ import annotations

from pathlib import Path

from custom_components.bticino_c300x.blueprint_installer import (
    install_bundled_blueprints,
)


def test_install_bundled_blueprints_copies_missing_files(tmp_path: Path) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"

    installed = install_bundled_blueprints(target)

    assert {path.name for path in installed} == {
        "doorbell_call_mobile_dashboard.yaml",
        "doorbell_call_notification.yaml",
        "doorbell_notification.yaml",
        "ring_capture.yaml",
        "ring_capture_wyoming.yaml",
        "strict_phrase_decision.yaml",
    }
    assert (target / "ring_capture.yaml").exists()


def test_install_bundled_blueprints_preserves_existing_files(tmp_path: Path) -> None:
    target = tmp_path / "blueprints" / "automation" / "bticino_c300x"
    target.mkdir(parents=True)
    existing = target / "ring_capture.yaml"
    existing.write_text("user edited\n", encoding="utf-8")

    installed = install_bundled_blueprints(target)

    assert existing.read_text(encoding="utf-8") == "user edited\n"
    assert existing not in installed
    assert (target / "doorbell_notification.yaml").exists()
