from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_services_yaml_exposes_reboot_without_redundant_ssh_service() -> None:
    sections = _services_yaml_sections()

    assert "reboot" in sections
    assert "reload_gui" in sections
    assert "start_ssh" not in sections


def test_services_yaml_places_stair_light_address_on_stair_light_service() -> None:
    sections = _services_yaml_sections()

    assert "\n    address:\n" in sections["stair_light"]
    assert "\n    address:\n" not in sections["unlock_door"]


def test_services_yaml_exposes_doorbell_video_activation() -> None:
    sections = _services_yaml_sections()

    assert "activate_doorbell_video" in sections
    assert "\n    audio:\n" in sections["activate_doorbell_video"]


def test_services_yaml_exposes_latest_video_message_play_and_delete() -> None:
    sections = _services_yaml_sections()

    assert "play_latest_video_message" in sections
    assert "play_latest_voice_memo" in sections
    assert "delete_latest_video_message" in sections
    assert "media_player_entity_id" in sections["play_latest_video_message"]
    assert "domain: media_player" in sections["play_latest_video_message"]
    assert "media_player_entity_id" in sections["play_latest_voice_memo"]
    assert "domain: media_player" in sections["play_latest_voice_memo"]


def test_services_yaml_exposes_latest_text_memo_delete() -> None:
    sections = _services_yaml_sections()

    assert "delete_latest_text_memo" in sections
    assert "entry_id" in sections["delete_latest_text_memo"]


def test_services_yaml_exposes_latest_voice_memo_delete() -> None:
    sections = _services_yaml_sections()

    assert "delete_latest_voice_memo" in sections
    assert "entry_id" in sections["delete_latest_voice_memo"]


def _services_yaml_sections() -> dict[str, str]:
    text = (ROOT / "custom_components" / "bticino_c300x" / "services.yaml").read_text(
        encoding="utf-8"
    )
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines(keepends=True):
        if line and not line.startswith(" ") and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1]
            sections[current] = [line]
            continue
        if current is not None:
            sections[current].append(line)

    return {key: "".join(lines) for key, lines in sections.items()}
