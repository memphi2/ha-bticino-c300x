"""Read-only dashboard and status payloads for the device display."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from homeassistant.core import HomeAssistant

from .alarm_state import (
    _alarm_commands_for_state,
    _alarm_delay_payload,
    _alarm_sensor_payload,
    _state_active_since,
)
from .capabilities import entry_device_ui_enabled_or_patch_active
from .const import (
    DASHBOARD_ACTION_DOMAIN,
    DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM,
    DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID,
    DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
    DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
    DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
    DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
)
from .dashboard_config import (
    _DASHBOARD_ACTION_PAGE,
    _DASHBOARD_BUTTON_ENTITY_DOMAINS,
    _DASHBOARD_CHOICE_ENTITY_DOMAINS,
    _DASHBOARD_DEFAULT_PAGE,
    _DASHBOARD_SLIDER_ENTITY_DOMAINS,
    _DASHBOARD_SUPPORTED_ENTITY_DOMAINS,
    _DASHBOARD_SWITCH_DOMAINS,
    _DASHBOARD_SWITCH_SERVICES,
    _DASHBOARD_TOGGLE_ENTITY_DOMAINS,
    _dashboard_first_attribute,
    _dashboard_float,
    configured_actions,
    configured_alarm_entity_id,
    configured_alarm_page_entity_id,
    configured_dashboard_entities,
    configured_dashboard_entity_display_overrides,
    configured_dashboard_prevent_return,
    configured_weather_entity_id,
)
from .dashboard_controls import entity_controls
from .dashboard_details import DETAIL_DOMAINS, entity_details
from .dashboard_entities import (
    dashboard_entity_custom_name_override,
    dashboard_entity_name_display_override,
    dashboard_entity_secondary_info_override,
)
from .dashboard_labels import (
    _BINARY_SENSOR_DEVICE_CLASS_COLORS,
    _BINARY_SENSOR_DEVICE_CLASS_LABELS_BY_LANGUAGE,
    _BINARY_SENSOR_DEVICE_CLASS_LABELS_EN,
    _DASHBOARD_COLOR_BAD,
    _DASHBOARD_COLOR_GOOD,
    _DASHBOARD_COLOR_NEUTRAL,
    _DASHBOARD_COLOR_WARNING,
    _DASHBOARD_ON_STATES,
    _DASHBOARD_STATE_LABELS_BY_LANGUAGE,
    _DASHBOARD_STATE_LABELS_EN,
)
from .dashboard_weather import async_dashboard_weather_payload
from .display_notifications import notification_payload
from .entry_types import BticinoC300XConfigEntry

dt_util: Any

try:
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - local test stubs
    dt_util = None


def _dashboard_language(hass: HomeAssistant | None) -> str:
    language = str(getattr(getattr(hass, "config", None), "language", "") or "").lower()
    if language.startswith("de"):
        return "de"
    if language.startswith("fr"):
        return "fr"
    if language.startswith("it"):
        return "it"
    return "en"


async def async_status(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry
) -> dict[str, Any]:
    """Return state data intended for the C300X UI."""

    device_ui_enabled = bool(entry_device_ui_enabled_or_patch_active(entry))
    actions = configured_actions(entry)
    dashboard_entities = configured_dashboard_entities(entry)
    alarm_entity_id = configured_alarm_entity_id(entry)
    language = _dashboard_language(hass)
    alarm: dict[str, Any] | None = None
    if device_ui_enabled and alarm_entity_id:
        state = hass.states.get(alarm_entity_id)
        active_since, active_since_label = _state_active_since(state)
        alarm = {
            "entity_id": alarm_entity_id,
            "state": state.state if state is not None else "unavailable",
            "active_since": active_since,
            "active_since_label": active_since_label,
            "commands": _alarm_commands_for_state(hass, alarm_entity_id, state),
        }
        alarm.update(_alarm_delay_payload(hass, alarm_entity_id, state))
        alarm.update(_alarm_sensor_payload(hass, alarm_entity_id, state))

    return {
        "ok": True,
        "entry_id": entry.entry_id,
        "title": entry.title,
        "alarm": alarm,
        "alarm_page_entity": _alarm_page_entity(hass, entry, language)
        if device_ui_enabled
        else None,
        "alarm_configured": alarm is not None,
        "dashboard_available": device_ui_enabled
        and (
            bool(actions)
            or bool(dashboard_entities)
            or configured_weather_entity_id(entry) is not None
            or bool(notification_payload(entry))
        ),
        "preventReturnToHomepage": configured_dashboard_prevent_return(entry),
        "device_ui_enabled": device_ui_enabled,
        "actions": sorted(actions.keys()) if device_ui_enabled else [],
    }


async def async_dashboard_payload(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> dict[str, Any]:
    """Return data in the c300x-dashboard `/homeassistant` JSON shape."""

    device_ui_enabled = bool(entry_device_ui_enabled_or_patch_active(entry))
    prevent_return = configured_dashboard_prevent_return(entry)
    if not device_ui_enabled:
        return {
            "preventReturnToHomepage": prevent_return,
            "refreshInterval": 0,
            "data": {"pages": []},
        }
    language = _dashboard_language(hass)
    pages: dict[str, dict[str, Any]] = {}
    main_page = _dashboard_page(pages, _DASHBOARD_DEFAULT_PAGE)
    badges = [{"state": "HA\nonline", "color": "#58d68d"}]

    alarm_entity_id = configured_alarm_entity_id(entry)
    if alarm_entity_id is not None:
        alarm_state = hass.states.get(alarm_entity_id)
        badges.append(
            {
                "state": "Alarm\n"
                + _dashboard_alarm_state(
                    alarm_state.state if alarm_state is not None else "unavailable",
                    language,
                )
            }
        )

    badges.append({"state": _dashboard_datetime_label()})
    weather = await async_dashboard_weather_payload(
        hass,
        configured_weather_entity_id(entry),
        language,
    )
    if weather is not None:
        main_page["weather"] = weather

    main_page["badges"] = badges
    entity_display_overrides = configured_dashboard_entity_display_overrides(entry)
    for index, entity_id in enumerate(configured_dashboard_entities(entry), start=1):
        dashboard_item = _dashboard_item_for_entity(
            hass,
            entity_id,
            index * 10,
            name_display=dashboard_entity_name_display_override(
                entity_display_overrides,
                entity_id,
                DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
            ),
            custom_name=dashboard_entity_custom_name_override(
                entity_display_overrides,
                entity_id,
            ),
            secondary_info=dashboard_entity_secondary_info_override(
                entity_display_overrides,
                entity_id,
                DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
            ),
            language=language,
        )
        if dashboard_item is None:
            continue
        layout = entity_display_overrides.get(entity_id, {})
        if "page" in layout:
            dashboard_item["_page"] = layout["page"]
        if "order" in layout:
            dashboard_item["_order"] = int(layout["order"])
        # Absent keys mean "automatic": the display keeps the type's own size.
        if "width" in layout:
            dashboard_item["tile_width"] = layout["width"]
        if "height" in layout:
            dashboard_item["tile_height"] = layout["height"]
        page = _dashboard_page(pages, dashboard_item.get("_page"))
        page["items"].append(dashboard_item)

    for action_id, action in configured_actions(entry).items():
        dashboard_item = _dashboard_item_for_action(
            hass,
            action_id,
            action,
            language=language,
        )
        if dashboard_item is None:
            continue
        page = _dashboard_page(pages, dashboard_item.get("_page"))
        page["items"].append(dashboard_item)

    return {
        "preventReturnToHomepage": prevent_return,
        "refreshInterval": 0,
        "notifications": notification_payload(entry),
        "data": {
            "pages": [
                _finalize_dashboard_page(page)
                for page in pages.values()
                if _dashboard_page_has_content(page)
            ]
        },
    }


def _dashboard_alarm_state(state: Any, language: str) -> str:
    return _dashboard_state_label(state, language)


def _dashboard_datetime_label() -> str:
    """Return the compact date/time badge for the device dashboard."""

    now_func = getattr(dt_util, "now", None) if dt_util is not None else None
    now = now_func() if callable(now_func) else datetime.now()
    return now.strftime("%d.%m.\n%H:%M")


def _alarm_page_entity(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    language: str,
) -> dict[str, Any] | None:
    entity_id = configured_alarm_page_entity_id(entry)
    if entity_id is None:
        return None
    overrides = configured_dashboard_entity_display_overrides(entry)
    item = _dashboard_item_for_entity(
        hass,
        entity_id,
        0,
        name_display=dashboard_entity_name_display_override(overrides, entity_id),
        custom_name=dashboard_entity_custom_name_override(overrides, entity_id),
        secondary_info=dashboard_entity_secondary_info_override(overrides, entity_id),
        language=language,
    )
    if item is None:
        return {
            "kind": "entity",
            "domain": DASHBOARD_ACTION_DOMAIN,
            "entity_id": entity_id,
            "name": entity_id,
            "state_label": "unavailable",
            "color": _DASHBOARD_COLOR_WARNING,
        }
    payload = dict(item)
    payload["kind"] = str(payload.pop("_kind", "entity"))
    payload.pop("_page", None)
    payload.pop("_order", None)
    return payload


def _dashboard_page(
    pages: dict[str, dict[str, Any]],
    title: Any,
) -> dict[str, Any]:
    page_title = _dashboard_text(title, _DASHBOARD_ACTION_PAGE, 60)
    if page_title not in pages:
        pages[page_title] = {
            "title": page_title,
            "badges": [],
            "items": [],
            "weather": None,
        }
    return pages[page_title]


def _dashboard_item_for_entity(
    hass: HomeAssistant,
    entity_id: str,
    order: int,
    *,
    name_display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    custom_name: str = "",
    secondary_info: str = DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    language: str = "en",
) -> dict[str, Any] | None:
    """Return a dashboard item for one directly selected HA entity."""

    return dashboard_item_for_state(
        hass, entity_id, hass.states.get(entity_id), order,
        name_display=name_display, custom_name=custom_name,
        secondary_info=secondary_info, language=language,
    )


def dashboard_item_for_state(
    hass: HomeAssistant,
    entity_id: str,
    state: Any,
    order: int = 0,
    *,
    name_display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    custom_name: str = "",
    secondary_info: str = DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
    language: str = "en",
) -> dict[str, Any] | None:
    """Render a snapshot without looking up newer state during an event comparison."""
    domain = entity_id.split(".", 1)[0]
    if domain not in _DASHBOARD_SUPPORTED_ENTITY_DOMAINS:
        return None

    name = _entity_name(
        entity_id,
        state,
        display=name_display,
        custom_name=custom_name,
    )
    item: dict[str, Any] = {
        "domain": DASHBOARD_ACTION_DOMAIN,
        "entity_id": entity_id,
        "name": name,
        "state_label": _entity_secondary_label(
            state,
            entity_id,
            secondary_info,
            language=language,
        ),
        "_page": _DASHBOARD_ACTION_PAGE,
        "_order": order,
    }
    unit = str(getattr(getattr(getattr(hass, "config", None), "units", None), "temperature_unit", ""))
    if domain in DETAIL_DOMAINS:
        item["details"] = entity_details(
            entity_id, state, _entity_state_label(state, entity_id=entity_id, language=language), unit,
        )
        item["available"] = state is not None and state.state not in {"unknown", "unavailable"}
    if domain in {"light", "cover", "climate", "fan", "number", "input_number", "select", "input_select"}:
        item["controls"] = entity_controls(entity_id, state, unit)
        item["available"] = state is not None and state.state not in {"unknown", "unavailable"}
        if domain == "climate" and state is not None:
            item["current_temperature"] = state.attributes.get("current_temperature")
            item["temperature_unit"] = unit
        if domain in {"cover", "climate"}:
            item["_kind"] = "entity"
            return item
    if domain in _DASHBOARD_TOGGLE_ENTITY_DOMAINS:
        item["_kind"] = "switch"
        item["state"] = _dashboard_state_is_on(state.state if state else None)
        return item
    if domain in _DASHBOARD_BUTTON_ENTITY_DOMAINS:
        item["_kind"] = "button"
        item["state_label"] = _button_secondary_label(
            state,
            entity_id,
            secondary_info,
            language=language,
        )
        return item
    if domain in _DASHBOARD_SLIDER_ENTITY_DOMAINS:
        item["_kind"] = "slider"
        item.update(_dashboard_slider_payload(state))
        return item
    if domain in _DASHBOARD_CHOICE_ENTITY_DOMAINS:
        item["_kind"] = "choice"
        item.update(_dashboard_choice_payload(state))
        return item
    item["_kind"] = "entity"
    item["state"] = _dashboard_state_is_on(state.state if state else None)
    color = _entity_state_color(state, entity_id=entity_id)
    if color is not None:
        item["color"] = color
    return item


def _dashboard_item_for_action(
    hass: HomeAssistant,
    action_id: str,
    action: dict[str, Any],
    *,
    language: str = "en",
) -> dict[str, Any] | None:
    dashboard = action.get("dashboard")
    if not isinstance(dashboard, dict):
        dashboard = {}

    kind = _dashboard_kind(action, dashboard)
    page = _dashboard_text(dashboard.get("page"), _DASHBOARD_ACTION_PAGE, 60)
    order = _dashboard_int(dashboard.get("order"), 1000)
    name = _dashboard_text(
        dashboard.get("name") or action.get("name"),
        action_id,
        80,
    )

    if kind == "image":
        source = _dashboard_image_source(hass, action, dashboard)
        if not source:
            return None
        image = {
            "source": source,
            "width": _dashboard_int(dashboard.get("width"), 220),
            "height": _dashboard_int(dashboard.get("height"), 120),
            "_kind": "image",
            "_page": page,
            "_order": order,
        }
        if name:
            image["name"] = name
        return image

    item: dict[str, Any] = {
        "domain": DASHBOARD_ACTION_DOMAIN,
        "entity_id": action_id,
        "name": name,
        "_kind": kind,
        "_page": page,
        "_order": order,
    }
    state = _dashboard_action_state(hass, action, dashboard)
    if kind == "switch":
        item["state"] = _dashboard_state_is_on(state.state if state else None)
    if kind == "button":
        item["state_label"] = _dashboard_text(dashboard.get("state_label"), "", 60)
    elif state is not None:
        item["state_label"] = _dashboard_text(
            dashboard.get("state_label"),
            _dashboard_state_label(state.state, language),
            60,
        )
    return item


def _dashboard_kind(action: dict[str, Any], dashboard: dict[str, Any]) -> str:
    item_type = dashboard.get("type")
    if item_type in {"button", "image", "switch"}:
        return str(item_type)
    if (
        action.get("domain") in _DASHBOARD_SWITCH_DOMAINS
        and action.get("service") in _DASHBOARD_SWITCH_SERVICES
    ):
        return "switch"
    if dashboard.get("source"):
        return "image"
    return "button"


def _dashboard_action_state(
    hass: HomeAssistant,
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> Any | None:
    entity_id = _dashboard_state_entity_id(action, dashboard)
    return hass.states.get(entity_id) if entity_id else None


def _dashboard_state_entity_id(
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> str | None:
    for source in (
        dashboard.get("state_entity_id"),
        dashboard.get("entity_id"),
        (action.get("target") or {}).get("entity_id")
        if isinstance(action.get("target"), dict)
        else None,
        (action.get("data") or {}).get("entity_id")
        if isinstance(action.get("data"), dict)
        else None,
    ):
        entity_id = _first_entity_id(source)
        if entity_id:
            return entity_id
    return None


def _dashboard_image_source(
    hass: HomeAssistant,
    action: dict[str, Any],
    dashboard: dict[str, Any],
) -> str | None:
    source = dashboard.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip()
    state = _dashboard_action_state(hass, action, dashboard)
    if state is not None and isinstance(state.state, str) and state.state.strip():
        return state.state.strip()
    return None


def _first_entity_id(value: Any) -> str | None:
    if isinstance(value, str) and "." in value:
        return value.strip()
    if isinstance(value, list):
        for item in value:
            entity_id = _first_entity_id(item)
            if entity_id:
                return entity_id
    return None


def _dashboard_state_is_on(value: Any) -> bool:
    return str(value or "").lower() in _DASHBOARD_ON_STATES


def _dashboard_state_label(value: Any, language: str = "en") -> str:
    raw = str(value or "unknown").lower()
    labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(
        language, _DASHBOARD_STATE_LABELS_EN
    )
    return labels.get(raw, str(value or "unknown"))


def _entity_name(
    entity_id: str,
    state: Any | None,
    *,
    display: str = DASHBOARD_ENTITY_NAME_DISPLAY_FRIENDLY_NAME,
    custom_name: str = "",
) -> str:
    if display == DASHBOARD_ENTITY_NAME_DISPLAY_CUSTOM and custom_name.strip():
        return _dashboard_text(custom_name, entity_id, 80)
    if display == DASHBOARD_ENTITY_NAME_DISPLAY_ENTITY_ID:
        return _dashboard_text(entity_id, entity_id, 80)
    attributes = getattr(state, "attributes", None)
    if isinstance(attributes, dict):
        name = attributes.get("friendly_name")
        if isinstance(name, str) and name.strip():
            return _dashboard_text(name, entity_id, 80)
    object_id = entity_id.split(".", 1)[-1].replace("_", " ")
    return _dashboard_text(object_id.title(), entity_id, 80)


def _entity_secondary_label(
    state: Any | None,
    entity_id: str,
    secondary_info: str,
    *,
    language: str = "en",
    fallback: str | None = None,
) -> str:
    if fallback is None:
        fallback = _dashboard_state_label("unknown", language)
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_NONE:
        return ""
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_ENTITY_ID:
        return _dashboard_text(entity_id, entity_id, 60)
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED:
        return _state_time_label(state, "last_changed")
    if secondary_info == DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED:
        return _state_time_label(state, "last_updated")
    return _entity_state_label(
        state,
        entity_id=entity_id,
        fallback=fallback,
        language=language,
    )


def _button_secondary_label(
    state: Any | None,
    entity_id: str,
    secondary_info: str,
    *,
    language: str = "en",
) -> str:
    if secondary_info in {
        DASHBOARD_ENTITY_SECONDARY_INFO_STATE,
        DASHBOARD_ENTITY_SECONDARY_INFO_LAST_CHANGED,
        DASHBOARD_ENTITY_SECONDARY_INFO_LAST_UPDATED,
        DASHBOARD_ENTITY_SECONDARY_INFO_NONE,
    }:
        return ""
    return _entity_secondary_label(
        state,
        entity_id,
        secondary_info,
        language=language,
        fallback="",
    )


def _entity_state_label(
    state: Any | None,
    *,
    entity_id: str | None = None,
    language: str = "en",
    fallback: str = "",
) -> str:
    if not fallback:
        fallback = _dashboard_state_label("unknown", language)
    if state is None:
        return "Offline"
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    state_value = str(state.state or "unknown")
    if str(entity_id or getattr(state, "entity_id", "")).startswith("binary_sensor."):
        return _binary_sensor_state_label(
            state_value,
            attributes,
            fallback=fallback,
            language=language,
        )
    label = _dashboard_state_label(state_value, language)
    unit = attributes.get("unit_of_measurement")
    labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(
        language, _DASHBOARD_STATE_LABELS_EN
    )
    if unit and state_value.lower() not in labels:
        label = f"{state_value} {unit}"
    if label == "unknown" and fallback:
        return fallback
    return _dashboard_text(label, fallback, 60)


def _binary_sensor_state_label(
    state_value: str,
    attributes: dict[str, Any],
    *,
    language: str = "en",
    fallback: str,
) -> str:
    raw = state_value.lower()
    if raw in {"unknown", "unavailable"}:
        return _dashboard_state_label(raw, language)
    device_labels = _BINARY_SENSOR_DEVICE_CLASS_LABELS_BY_LANGUAGE.get(
        language,
        _BINARY_SENSOR_DEVICE_CLASS_LABELS_EN,
    )
    labels = device_labels.get(str(attributes.get("device_class") or "").lower())
    if labels is not None and raw in {"off", "on"}:
        return labels[1] if raw == "on" else labels[0]
    state_labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(
        language,
        _DASHBOARD_STATE_LABELS_EN,
    )
    return _dashboard_state_label(raw, language) if raw in state_labels else fallback


def _entity_state_color(
    state: Any | None,
    *,
    entity_id: str | None = None,
) -> str | None:
    if state is None:
        return _DASHBOARD_COLOR_WARNING
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    raw = str(state.state or "unknown").lower()
    if str(entity_id or getattr(state, "entity_id", "")).startswith("binary_sensor."):
        return _binary_sensor_state_color(raw, attributes)
    return _raw_state_color(raw)


def _binary_sensor_state_color(
    raw: str,
    attributes: dict[str, Any],
) -> str:
    if raw in {"unknown", "unavailable"}:
        return _DASHBOARD_COLOR_WARNING
    if raw in {"off", "on"}:
        colors = _BINARY_SENSOR_DEVICE_CLASS_COLORS.get(
            str(attributes.get("device_class") or "").lower()
        )
        if colors is not None:
            return colors[1] if raw == "on" else colors[0]
        return _DASHBOARD_COLOR_BAD if raw == "on" else _DASHBOARD_COLOR_GOOD
    return _raw_state_color(raw) or _DASHBOARD_COLOR_NEUTRAL


def _raw_state_color(raw: str) -> str | None:
    if raw in {"closed", "disarmed", "idle", "locked", "off", "ok", "safe"}:
        return _DASHBOARD_COLOR_GOOD
    if raw in {
        "on",
        "open",
        "problem",
        "triggered",
        "unsafe",
        "unlocked",
        "violated",
    }:
        return _DASHBOARD_COLOR_BAD
    if raw in {"unknown", "unavailable"}:
        return _DASHBOARD_COLOR_WARNING
    return None


def _state_time_label(state: Any | None, attribute: str) -> str:
    value = getattr(state, attribute, None)
    if value is None:
        return ""
    as_local = getattr(dt_util, "as_local", None) if dt_util is not None else None
    display_time = as_local(value) if callable(as_local) else value
    if hasattr(display_time, "strftime"):
        return cast(str, display_time.strftime("%d.%m. %H:%M"))
    return ""


def _dashboard_slider_payload(state: Any | None) -> dict[str, Any]:
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    value = _dashboard_float(getattr(state, "state", None), 0.0) or 0.0
    minimum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "min",
            "native_min",
            "native_min_value",
        ),
        0.0,
    )
    maximum = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "max",
            "native_max",
            "native_max_value",
        ),
        100.0,
    )
    step = _dashboard_float(
        _dashboard_first_attribute(
            attributes,
            "step",
            "native_step",
            "native_step_value",
        ),
        1.0,
    )
    return {
        "value": value,
        "min": 0.0 if minimum is None else minimum,
        "max": 100.0 if maximum is None else maximum,
        "step": 1.0 if step is None or step <= 0 else step,
    }


def _dashboard_choice_payload(state: Any | None) -> dict[str, Any]:
    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    raw_options = attributes.get("options")
    if not isinstance(raw_options, list):
        raw_options = []
    value = "" if state is None else str(state.state or "")
    return {
        "value": value,
        "options": [
            {
                "label": _dashboard_text(option, "", 80),
                "value": option,
            }
            for option in raw_options
            if isinstance(option, str) and option.strip()
        ][:12],
    }


def _dashboard_text(value: Any, fallback: str, max_length: int) -> str:
    if isinstance(value, str):
        text = " ".join(value.split())
        if text:
            return text[:max_length]
    return fallback[:max_length]


def _dashboard_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return fallback
    return max(parsed, 0)


def _finalize_dashboard_page(page: dict[str, Any]) -> dict[str, Any]:
    finalized = {
        "title": page.get("title") or _DASHBOARD_ACTION_PAGE,
    }
    if badges := list(page.get("badges") or []):
        finalized["badges"] = badges
    if items := _finalize_dashboard_items(page.get("items")):
        finalized["items"] = items
    if isinstance(page.get("weather"), dict):
        finalized["weather"] = page["weather"]
    if page.get("flow"):
        finalized["flow"] = page["flow"]
    return finalized


def _finalize_dashboard_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = []
    for item in sorted(
        items,
        key=lambda value: (
            _dashboard_int(
                value.get("_order") if isinstance(value, dict) else None, 1000
            ),
            str(
                (
                    value.get("name")
                    or value.get("entity_id")
                    or value.get("source")
                    or ""
                )
                if isinstance(value, dict)
                else ""
            ),
        ),
    ):
        if not isinstance(item, dict):
            continue
        cleaned = dict(item)
        if "_kind" in cleaned and "kind" not in cleaned:
            cleaned["kind"] = str(cleaned["_kind"])
        cleaned.pop("_kind", None)
        cleaned.pop("_order", None)
        cleaned.pop("_page", None)
        result.append(cleaned)
    return result


def _dashboard_page_has_content(page: dict[str, Any]) -> bool:
    return any(
        bool(page.get(key))
        for key in (
            "badges",
            "items",
            "weather",
            "flow",
        )
    )
