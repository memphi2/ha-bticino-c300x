"""Weather payload helpers for the C300X display dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

try:
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - local test stubs
    dt_util = None

from .dashboard_labels import (
    _DASHBOARD_STATE_LABELS_BY_LANGUAGE,
    _DASHBOARD_STATE_LABELS_EN,
    _WEATHER_STATE_LABELS_BY_LANGUAGE,
    _WEATHER_STATE_LABELS_EN,
    _WEATHER_TITLE_BY_LANGUAGE,
)

_WEATHER_SUN_LABELS = {
    "de": ("Auf", "Unter"),
    "en": ("Rise", "Set"),
    "fr": ("Lever", "Coucher"),
    "it": ("Alba", "Tramonto"),
}


async def async_dashboard_weather_payload(
    hass: HomeAssistant,
    entity_id: str | None,
    language: str,
) -> dict[str, Any] | None:
    """Return weather data for the dashboard, including HA forecast service data."""

    return dashboard_weather_payload(
        hass,
        entity_id,
        language,
        forecast_items=await _async_weather_forecast_items(hass, entity_id),
    )


def dashboard_weather_payload(
    hass: HomeAssistant,
    entity_id: str | None,
    language: str,
    *,
    forecast_items: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Return weather data for the first dashboard page."""

    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        title = _localized_weather_title(language)
        return {
            "available": False,
            "title": title,
            "condition": "Offline",
            "condition_key": "unavailable",
            "temperature": "",
            "humidity": "",
            "wind": "",
            "forecast": "",
            "sun": _weather_sun(hass, language),
            "updated": "",
            "badge": f"{title}\nOffline",
            "color": "#f1c40f",
        }

    attributes = getattr(state, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}
    condition = _weather_state_label(state.state, language)
    condition_key = str(state.state or "unknown").lower()
    temperature = _weather_temperature(attributes)
    humidity = _weather_humidity(attributes)
    wind = _weather_wind(attributes)
    title = _dashboard_text(attributes.get("friendly_name"), _localized_weather_title(language), 40)
    updated = _weather_updated_label(state)
    return {
        "available": state.state not in {"unknown", "unavailable"},
        "title": title,
        "condition": condition,
        "condition_key": condition_key,
        "temperature": temperature,
        "humidity": humidity,
        "wind": wind,
        "forecast": _weather_forecast(
            attributes,
            language,
            forecast_items=forecast_items,
        ),
        "sun": _weather_sun(hass, language),
        "updated": updated,
        "badge": f"{condition}\n{temperature or title}",
        "color": _weather_color(state.state),
    }


def _localized_weather_title(language: str) -> str:
    return _WEATHER_TITLE_BY_LANGUAGE.get(language, _WEATHER_TITLE_BY_LANGUAGE["en"])


def _weather_state_label(value: Any, language: str) -> str:
    raw = str(value or "unknown").lower()
    labels = _WEATHER_STATE_LABELS_BY_LANGUAGE.get(language, _WEATHER_STATE_LABELS_EN)
    return labels.get(raw, _dashboard_state_label(raw, language))


def _weather_temperature(attributes: dict[str, Any]) -> str:
    value = attributes.get("temperature")
    if value in (None, ""):
        return ""
    unit = str(attributes.get("temperature_unit") or attributes.get("unit_of_measurement") or "C")
    return f"{value} {unit}"


def _weather_humidity(attributes: dict[str, Any]) -> str:
    value = attributes.get("humidity")
    if value in (None, ""):
        return ""
    return f"{value}%"


def _weather_wind(attributes: dict[str, Any]) -> str:
    value = attributes.get("wind_speed")
    if value in (None, ""):
        return ""
    unit = str(attributes.get("wind_speed_unit") or "")
    suffix = f" {unit}" if unit else ""
    return f"{value}{suffix}"


async def _async_weather_forecast_items(
    hass: HomeAssistant,
    entity_id: str | None,
) -> list[Any] | None:
    if entity_id is None or not hasattr(hass, "services"):
        return None
    for forecast_type in ("hourly", "daily"):
        try:
            response = await hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": forecast_type},
                blocking=True,
                return_response=True,
            )
        except (TypeError, ValueError):
            return None
        except Exception:
            continue
        forecast = _weather_service_forecast_items(response, entity_id)
        if forecast:
            return forecast
    return None


def _weather_service_forecast_items(response: Any, entity_id: str) -> list[Any]:
    if not isinstance(response, dict):
        return []
    entity_payload = response.get(entity_id)
    if isinstance(entity_payload, dict):
        forecast = entity_payload.get("forecast")
        if isinstance(forecast, list):
            return forecast
    forecast = response.get("forecast")
    return forecast if isinstance(forecast, list) else []


def _weather_forecast(
    attributes: dict[str, Any],
    language: str,
    *,
    forecast_items: list[Any] | None = None,
) -> str:
    forecast = forecast_items if forecast_items is not None else _weather_forecast_items(attributes)
    if not forecast:
        return ""
    unit = str(attributes.get("temperature_unit") or attributes.get("unit_of_measurement") or "C")
    labels: list[str] = []
    for item in forecast[:2]:
        if not isinstance(item, dict):
            continue
        condition = _weather_state_label(item.get("condition"), language)
        temperature = _weather_forecast_temperature(item, unit)
        time_label = _weather_time_label(
            item.get("datetime") or item.get("native_datetime") or item.get("time")
        )
        parts = [part for part in (time_label, condition, temperature) if part]
        if parts:
            labels.append(" ".join(parts))
    return _dashboard_text(" | ".join(labels), "", 86)


def _weather_forecast_items(attributes: dict[str, Any]) -> list[Any]:
    for key in ("forecast", "forecasts"):
        value = attributes.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("forecast")
            if isinstance(nested, list):
                return nested
            for nested in value.values():
                if isinstance(nested, list):
                    return nested
    return []


def _weather_forecast_temperature(item: dict[str, Any], fallback_unit: str) -> str:
    value = item.get("temperature")
    if value in (None, ""):
        value = item.get("templow")
    if value in (None, ""):
        return ""
    unit = str(item.get("temperature_unit") or item.get("unit_of_measurement") or fallback_unit)
    return f"{value} {unit}"


def _weather_sun(hass: HomeAssistant, language: str) -> str:
    sun_state = hass.states.get("sun.sun")
    attributes = getattr(sun_state, "attributes", None)
    if not isinstance(attributes, dict):
        return ""
    sunrise = _weather_time_label(attributes.get("next_rising"))
    sunset = _weather_time_label(attributes.get("next_setting"))
    sunrise_label, sunset_label = _WEATHER_SUN_LABELS.get(language, _WEATHER_SUN_LABELS["en"])
    if sunrise and sunset:
        return f"{sunrise_label} {sunrise}   {sunset_label} {sunset}"
    if sunrise:
        return f"{sunrise_label} {sunrise}"
    if sunset:
        return f"{sunset_label} {sunset}"
    return ""


def _weather_time_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    display_time = value
    if isinstance(value, str):
        parse_datetime = getattr(dt_util, "parse_datetime", None) if dt_util is not None else None
        display_time = parse_datetime(value) if callable(parse_datetime) else None
        if display_time is None:
            try:
                display_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return _dashboard_text(value, "", 16)
    as_local = getattr(dt_util, "as_local", None) if dt_util is not None else None
    display_time = as_local(display_time) if callable(as_local) else display_time
    if hasattr(display_time, "strftime"):
        return display_time.strftime("%H:%M")
    return _dashboard_text(display_time, "", 16)


def _weather_updated_label(state: Any) -> str:
    last_changed = getattr(state, "last_changed", None)
    if last_changed is None:
        return ""
    return _weather_time_label(last_changed)


def _weather_color(value: Any) -> str:
    raw = str(value or "unknown").lower()
    if raw in {"sunny", "clear-night", "partlycloudy"}:
        return "#f1c40f"
    if raw in {"rainy", "pouring", "lightning-rainy", "snowy-rainy"}:
        return "#5dade2"
    if raw in {"unknown", "unavailable"}:
        return "#f1c40f"
    return "#58d68d"


def _dashboard_state_label(value: Any, language: str = "en") -> str:
    raw = str(value or "unknown").lower()
    labels = _DASHBOARD_STATE_LABELS_BY_LANGUAGE.get(language, _DASHBOARD_STATE_LABELS_EN)
    return labels.get(raw, raw.replace("_", " ").title())


def _dashboard_text(value: Any, fallback: str, max_length: int) -> str:
    text = str(value).strip() if value not in (None, "") else fallback
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."
