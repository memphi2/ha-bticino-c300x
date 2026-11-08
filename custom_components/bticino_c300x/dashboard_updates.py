"""Filter selected-entity events using the same projection as the display payload."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .dashboard import _dashboard_language, dashboard_item_for_state
from .dashboard_config import configured_dashboard_entity_display_overrides
from .dashboard_entities import (
    dashboard_entity_custom_name_override,
    dashboard_entity_name_display_override,
    dashboard_entity_secondary_info_override,
)
from .entry_types import BticinoC300XConfigEntry


def dashboard_state_event_changes_display(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, data: dict[str, Any],
) -> bool:
    """Keep availability, capabilities, names and configured timestamps observable."""
    if "old_state" not in data or "new_state" not in data:
        return True
    entity_id = data["entity_id"]
    overrides = configured_dashboard_entity_display_overrides(entry)

    def project(state: Any) -> dict[str, Any] | None:
        return dashboard_item_for_state(
            hass, entity_id, state,
            name_display=dashboard_entity_name_display_override(overrides, entity_id),
            custom_name=dashboard_entity_custom_name_override(overrides, entity_id),
            secondary_info=dashboard_entity_secondary_info_override(overrides, entity_id),
            language=_dashboard_language(hass),
        )

    return project(data["old_state"]) != project(data["new_state"])
