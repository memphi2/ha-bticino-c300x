from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_services_yaml_has_no_services_the_buttons_replace() -> None:
    sections = _services_yaml_sections()

    for removed in (
        "start_ssh", "reboot", "reload_gui", "stair_light", "unlock_door", "stop_doorbell_video",
        "run_device_activation", "delete_latest_video_message", "delete_latest_text_memo",
        "delete_latest_voice_memo", "answer_doorbell_call", "hangup_doorbell_call",
    ):
        assert removed not in sections


def test_services_target_devices_or_entities_instead_of_entry_ids() -> None:
    sections = _services_yaml_sections()

    assert "entry_id" not in "".join(sections.values())
    for name, text in sections.items():
        if name != "run_ring_wyoming_analysis":
            assert "\n  target:\n    device:\n      integration: bticino_c300x\n" in text, name


def test_services_yaml_exposes_doorbell_video_activation() -> None:
    sections = _services_yaml_sections()

    assert "activate_doorbell_video" in sections
    assert "answer_call" in sections
    assert "hangup_call" in sections
    assert "capture_doorbell_call" in sections
    assert "\n    audio:\n" in sections["activate_doorbell_video"]
    assert "\n    call_id:\n" in sections["answer_call"]
    assert "\n    call_id:\n" in sections["hangup_call"]
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
    assert "\n    lock_id:\n" not in sections["evaluate_ring_analysis"]
    # It opens the unit the recording names; a target of another unit is refused.
    unlock = sections["evaluate_ring_analysis"].split("\n    unlock_on_match:\n", 1)[1]
    assert "the outdoor unit that rang in the recording" in unlock
    assert "a target of another outdoor unit is refused" in unlock
    assert "otherwise the unit of the current call" not in unlock
    assert "/config/c300x/analysis/decision.json" in sections["evaluate_ring_analysis"]


def test_services_yaml_exposes_home_call_controls() -> None:
    sections = _services_yaml_sections()

    assert "start_home_call" in sections
    assert "stop_home_call" in sections
    assert "\n    duration_seconds:\n" in sections["start_home_call"]


def test_services_yaml_exposes_latest_video_message_play() -> None:
    sections = _services_yaml_sections()

    assert "play_latest_video_message" in sections
    assert "play_latest_voice_memo" in sections
    assert "media_player_entity_id" in sections["play_latest_video_message"]
    assert "domain: media_player" in sections["play_latest_video_message"]
    assert "media_player_entity_id" in sections["play_latest_voice_memo"]
    assert "domain: media_player" in sections["play_latest_voice_memo"]


def test_services_yaml_exposes_text_memo_writer() -> None:
    sections = _services_yaml_sections()

    assert "write_text_memo" in sections
    assert "\n    text:\n" in sections["write_text_memo"]
    assert "multiline: true" in sections["write_text_memo"]


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


def test_service_texts_fit_both_station_models() -> None:
    """Actions are global: their names and descriptions name no station model."""

    text = (ROOT / "custom_components" / "bticino_c300x" / "services.yaml").read_text(encoding="utf-8")
    shown = [line for line in text.splitlines() if line.strip().startswith(("name:", "description:"))]
    assert [line for line in shown if "C300X" in line or "C100X" in line] == []


def test_service_icons_name_only_services_that_exist() -> None:
    import json

    icons = json.loads((ROOT / "custom_components/bticino_c300x/icons.json").read_text(encoding="utf-8"))
    assert set(icons.get("services", {})) <= set(_services_yaml_sections())


def test_user_docs_name_no_removed_service() -> None:
    # The CHANGELOG, release notes and developer notes name them on purpose.
    removed = (
        "stop_doorbell_video", "run_device_activation", "unlock_door", "reload_gui",
        "bticino_c300x.stair_light", "bticino_c300x.reboot", "delete_latest_video_message",
        "delete_latest_text_memo", "delete_latest_voice_memo", "answer_doorbell_call",
        "hangup_doorbell_call",
    )
    pages = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "PRIVACY.md", *sorted((ROOT / "docs").glob("*.md"))]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert [name for name in removed if name in text] == [], page.name
