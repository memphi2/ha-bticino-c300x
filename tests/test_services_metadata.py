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
    assert "stop_doorbell_video" in sections
    assert "answer_doorbell_call" in sections
    assert "hangup_doorbell_call" in sections
    assert "capture_doorbell_call" in sections
    assert "\n    audio:\n" in sections["activate_doorbell_video"]
    assert "\n    audio:\n" not in sections["answer_doorbell_call"]
    assert "call-end action" in sections["stop_doorbell_video"]
    assert "/media/c300x/" in sections["capture_doorbell_call"]
    assert "\n    output_path:\n" in sections["capture_doorbell_call"]
    assert "\n    duration_seconds:\n" in sections["capture_doorbell_call"]
    assert "\n    include_audio:\n" in sections["capture_doorbell_call"]
    assert "\n    wav_output_dir:\n" in sections["capture_doorbell_call"]
    assert "\n    announcement_path:\n" in sections["capture_doorbell_call"]
    assert "run_ring_wyoming_analysis" in sections
    assert "\n    wyoming_host:\n" in sections["run_ring_wyoming_analysis"]
    assert "\n    wav_path:\n" in sections["run_ring_wyoming_analysis"]
    assert "/config/c300x/analysis/result.json" in sections["run_ring_wyoming_analysis"]
    assert "evaluate_ring_analysis" in sections
    assert "\n    unlock_on_match:\n" in sections["evaluate_ring_analysis"]
    assert "/config/c300x/analysis/decision.json" in sections["evaluate_ring_analysis"]


def test_services_yaml_exposes_home_call_controls() -> None:
    sections = _services_yaml_sections()

    assert "start_home_call" in sections
    assert "stop_home_call" in sections
    assert "\n    duration_seconds:\n" in sections["start_home_call"]


def test_services_yaml_exposes_device_activation_runner() -> None:
    sections = _services_yaml_sections()

    assert "run_device_activation" in sections
    assert "\n    activation_id:\n" in sections["run_device_activation"]


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


def test_services_yaml_exposes_text_memo_writer() -> None:
    sections = _services_yaml_sections()

    assert "write_text_memo" in sections
    assert "\n    text:\n" in sections["write_text_memo"]
    assert "multiline: true" in sections["write_text_memo"]


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
