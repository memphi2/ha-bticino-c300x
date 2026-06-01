from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard_entities import (
    normalize_dashboard_entity_ids,
)
from custom_components.bticino_c300x.entry_config import entry_config_value
from custom_components.bticino_c300x.error_text import compact_error_text
from custom_components.bticino_c300x.message_metadata import (
    latest_metadata_item,
    localized_choice,
    metadata_sort_key,
)


def test_entry_config_value_honors_present_blank_options() -> None:
    entry = SimpleNamespace(data={"maintenance_token": "old"}, options={"maintenance_token": ""})

    assert entry_config_value(entry, "maintenance_token", "") == ""


def test_entry_config_value_keeps_required_data_when_option_is_blank() -> None:
    entry = SimpleNamespace(
        data={"agent_host": "c300x.local", "agent_token": "stored"},
        options={"agent_host": "", "agent_token": ""},
    )

    assert entry_config_value(entry, "agent_host", "") == "c300x.local"
    assert entry_config_value(entry, "agent_token", "") == "stored"


def test_entry_config_value_uses_data_when_option_is_absent() -> None:
    entry = SimpleNamespace(data={"agent_host": "c300x.local"}, options={})

    assert entry_config_value(entry, "agent_host", "") == "c300x.local"


def test_entry_config_value_accepts_read_only_mapping_data() -> None:
    entry = SimpleNamespace(
        data=MappingProxyType({"agent_host": "c300x.local"}),
        options=MappingProxyType({}),
    )

    assert entry_config_value(entry, "agent_host", "") == "c300x.local"


def test_normalize_dashboard_entity_ids_deduplicates_and_normalizes() -> None:
    assert normalize_dashboard_entity_ids(" Switch.Kitchen, sensor.Temp switch.kitchen ") == (
        "switch.kitchen",
        "sensor.temp",
    )


def test_normalize_dashboard_entity_ids_drops_invalid_values_in_lenient_mode() -> None:
    assert normalize_dashboard_entity_ids(["media_player.tv", "switch.valid", "bad"]) == (
        "switch.valid",
    )


def test_normalize_dashboard_entity_ids_rejects_invalid_values_in_strict_mode() -> None:
    with pytest.raises(ValueError):
        normalize_dashboard_entity_ids("media_player.tv", strict=True)


def test_compact_error_text_is_one_line_and_bounded() -> None:
    err = RuntimeError(" first line\nsecond line " + ("x" * 40))

    assert compact_error_text(err, max_length=32) == "RuntimeError: first line seco..."


def test_latest_metadata_item_uses_time_then_text_then_id() -> None:
    latest = latest_metadata_item(
        [
            {"id": "a", "unix_time": 1, "iso_time": "2026-01-01T00:00:00"},
            {"id": "c", "unix_time": 2, "iso_time": "2026-01-01T00:00:00"},
            {"id": "b", "unix_time": 2, "iso_time": "2026-01-01T00:00:00"},
        ]
    )

    assert latest == {"id": "c", "unix_time": 2, "iso_time": "2026-01-01T00:00:00"}
    assert metadata_sort_key({}) == (0, "", "")


def test_metadata_sort_key_can_preserve_video_time_coercion() -> None:
    assert metadata_sort_key({"unix_time": "7"}, coerce_unix_time=True) == (7, "", "")
    assert metadata_sort_key({"unix_time": "7"}) == (0, "", "")


def test_localized_choice_supports_de_it_and_default_en() -> None:
    assert localized_choice("de-DE", de="de", it="it", en="en") == "de"
    assert localized_choice("it-IT", de="de", it="it", en="en") == "it"
    assert localized_choice("fr-FR", de="de", it="it", en="en") == "en"
