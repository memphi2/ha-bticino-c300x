from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from custom_components.bticino_c300x.dashboard_entities import (
    normalize_dashboard_entity_display_overrides,
    normalize_dashboard_entity_ids,
)
from custom_components.bticino_c300x.entry_config import (
    entry_config_value,
    normalized_update_options,
)
from custom_components.bticino_c300x.error_text import compact_error_text
from custom_components.bticino_c300x.message_metadata import (
    latest_metadata_item,
    localized_choice,
    metadata_sort_key,
)


def test_entry_config_value_honors_present_blank_options() -> None:
    entry = SimpleNamespace(data={"maintenance_token": "old"}, options={"maintenance_token": ""})

    assert entry_config_value(entry, "maintenance_token", "") == ""


def test_dashboard_entity_display_overrides_validate_modes() -> None:
    assert normalize_dashboard_entity_display_overrides(
        {
            "sensor.temperature": {
                "name": "custom",
                "custom_name": "Outside",
                "secondary": "none",
            }
        },
        strict=True,
    ) == {
        "sensor.temperature": {
            "name": "custom",
            "custom_name": "Outside",
            "secondary": "none",
        }
    }

    with pytest.raises(ValueError, match="invalid dashboard entity display name mode"):
        normalize_dashboard_entity_display_overrides(
            {"sensor.temperature": {"name": "bad"}},
            strict=True,
        )
    with pytest.raises(ValueError, match="missing dashboard entity custom name"):
        normalize_dashboard_entity_display_overrides(
            {"sensor.temperature": {"name": "custom"}},
            strict=True,
        )
    with pytest.raises(ValueError, match="invalid dashboard entity secondary info mode"):
        normalize_dashboard_entity_display_overrides(
            {"sensor.temperature": {"secondary": "bad"}},
            strict=True,
        )


def test_dashboard_entity_display_overrides_drop_invalid_lenient_values() -> None:
    assert normalize_dashboard_entity_display_overrides("bad") == {}
    assert normalize_dashboard_entity_display_overrides(
        {
            "media_player.tv": {"name": "entity_id"},
            "sensor.temperature": "bad",
            "sensor.humidity": {"name": "bad", "secondary": "bad"},
        }
    ) == {}


def test_dashboard_entity_display_overrides_reject_invalid_strict_values() -> None:
    with pytest.raises(ValueError, match="invalid dashboard entity display overrides"):
        normalize_dashboard_entity_display_overrides("bad", strict=True)
    with pytest.raises(ValueError, match="invalid dashboard entity"):
        normalize_dashboard_entity_display_overrides(
            {"media_player.tv": {"name": "entity_id"}},
            strict=True,
        )
    with pytest.raises(ValueError, match="invalid dashboard entity display override"):
        normalize_dashboard_entity_display_overrides(
            {"sensor.temperature": "bad"},
            strict=True,
        )


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


def test_entry_config_value_keeps_non_blank_data_for_whitespace_option() -> None:
    entry = SimpleNamespace(
        data={"agent_host": "c300x.local", "agent_token": 123},
        options={"agent_host": "   ", "agent_token": "   "},
    )

    assert entry_config_value(entry, "agent_host", "") == "c300x.local"
    assert entry_config_value(entry, "agent_token", "") == 123


def test_entry_config_value_uses_default_for_whitespace_non_required_option() -> None:
    entry = SimpleNamespace(
        data={"maintenance_token": "stored"},
        options={"maintenance_token": "   "},
    )

    assert entry_config_value(entry, "maintenance_token", "default") == "default"


def test_entry_config_value_uses_default_for_non_mapping_data() -> None:
    entry = SimpleNamespace(data=None, options={})

    assert entry_config_value(entry, "agent_host", "default") == "default"


def test_normalized_update_options_removes_blank_required_overrides() -> None:
    assert normalized_update_options(
        {"agent_host": "c300x.local", "agent_token": "stored"},
        {"agent_host": "", "agent_token": "   ", "maintenance_token": ""},
    ) == {"maintenance_token": ""}


def test_normalize_dashboard_entity_ids_deduplicates_and_normalizes() -> None:
    assert normalize_dashboard_entity_ids(" Switch.Kitchen, sensor.Temp switch.kitchen ") == (
        "switch.kitchen",
        "sensor.temp",
    )


def test_normalize_dashboard_entity_ids_drops_invalid_values_in_lenient_mode() -> None:
    assert normalize_dashboard_entity_ids(["media_player.tv", "switch.valid", "bad"]) == (
        "switch.valid",
    )
    assert normalize_dashboard_entity_ids(object()) == ()
    assert normalize_dashboard_entity_ids([None, "", "sensor.valid"]) == ("sensor.valid",)


def test_normalize_dashboard_entity_ids_rejects_invalid_values_in_strict_mode() -> None:
    with pytest.raises(ValueError):
        normalize_dashboard_entity_ids("media_player.tv", strict=True)
    with pytest.raises(ValueError):
        normalize_dashboard_entity_ids(object(), strict=True)


def test_compact_error_text_is_one_line_and_bounded() -> None:
    err = RuntimeError(" first line\nsecond line " + ("x" * 40))

    assert compact_error_text(err, max_length=32) == "RuntimeError: first line seco..."


def test_compact_error_text_returns_exception_name_for_empty_message() -> None:
    assert compact_error_text(RuntimeError()) == "RuntimeError"
    assert compact_error_text(RuntimeError("RuntimeError")) == "RuntimeError"


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
    assert metadata_sort_key({"unix_time": "bad"}, coerce_unix_time=True) == (0, "", "")


def test_localized_choice_supports_de_it_and_default_en() -> None:
    assert localized_choice("de-DE", de="de", it="it", fr="fr", en="en") == "de"
    assert localized_choice("it-IT", de="de", it="it", fr="fr", en="en") == "it"
    assert localized_choice("fr-FR", de="de", it="it", fr="fr", en="en") == "fr"
    assert localized_choice("es-ES", de="de", it="it", fr="fr", en="en") == "en"
