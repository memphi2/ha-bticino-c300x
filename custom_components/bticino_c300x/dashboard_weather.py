"""Weather payload helpers for the C300X display dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta
from time import monotonic
from typing import Any, cast

from homeassistant.core import HomeAssistant

from .dashboard_labels import (
    _DASHBOARD_STATE_LABELS_BY_LANGUAGE,
    _DASHBOARD_STATE_LABELS_EN,
    _WEATHER_STATE_LABELS_BY_LANGUAGE,
    _WEATHER_STATE_LABELS_EN,
    _WEATHER_TITLE_BY_LANGUAGE,
)

dt_util: Any
try:
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - local test stubs
    dt_util = None

_FORECAST_TYPE_KEY = "_c300x_forecast_type"
_FORECAST_CACHE_KEY = "bticino_c300x_dashboard_weather_forecast"
_FORECAST_CACHE_TTL_SECONDS = 300.0
_EMPTY_FORECAST = {
    "time": "",
    "condition": "",
    "condition_key": "",
    "temperature": "",
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
            "forecast_1": dict(_EMPTY_FORECAST),
            "forecast_2": dict(_EMPTY_FORECAST),
            "sun": "",
            "sunrise": "",
            "sunset": "",
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
    title = _localized_weather_title(language)
    updated = _weather_updated_label(state)
    forecast_entries = _weather_forecast_entries(
        attributes,
        language,
        forecast_items=forecast_items,
    )
    sunrise, sunset = _weather_sun_times(hass)
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
        "forecast_1": forecast_entries[0],
        "forecast_2": forecast_entries[1],
        "sun": _weather_sun_text(sunrise, sunset),
        "sunrise": sunrise,
        "sunset": sunset,
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
    cache = _weather_forecast_cache(hass)
    state = hass.states.get(entity_id) if hasattr(hass, "states") else None
    state_revision = _weather_state_revision(state)
    for forecast_type in ("hourly", "daily"):
        cached = _cached_weather_forecast(
            cache,
            entity_id,
            forecast_type,
            state_revision,
        )
        if cached is not None:
            return cached
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
            tagged = _tag_forecast_items(forecast, forecast_type)
            _store_weather_forecast_cache(
                cache,
                entity_id,
                forecast_type,
                state_revision,
                tagged,
            )
            return tagged
    return None


def _weather_forecast_cache(hass: HomeAssistant) -> dict[tuple[str, str], dict[str, Any]]:
    data = getattr(hass, "data", None)
    if not isinstance(data, dict):
        return {}
    cache = data.setdefault(_FORECAST_CACHE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        data[_FORECAST_CACHE_KEY] = cache
    return cache


def _weather_state_revision(state: Any) -> str:
    if state is None:
        return ""
    parts = (
        getattr(state, "state", ""),
        getattr(state, "last_updated", None),
        getattr(state, "last_changed", None),
    )
    return "|".join(str(part or "") for part in parts)


def _cached_weather_forecast(
    cache: dict[tuple[str, str], dict[str, Any]],
    entity_id: str,
    forecast_type: str,
    state_revision: str,
) -> list[Any] | None:
    cached = cache.get((entity_id, forecast_type))
    if not isinstance(cached, dict):
        return None
    if cached.get("state_revision") != state_revision:
        return None
    expires_at = cached.get("expires_at")
    if not isinstance(expires_at, (float, int)) or expires_at < monotonic():
        return None
    forecast = cached.get("forecast")
    return list(forecast) if isinstance(forecast, list) else None


def _store_weather_forecast_cache(
    cache: dict[tuple[str, str], dict[str, Any]],
    entity_id: str,
    forecast_type: str,
    state_revision: str,
    forecast: list[Any],
) -> None:
    cache[(entity_id, forecast_type)] = {
        "expires_at": monotonic() + _FORECAST_CACHE_TTL_SECONDS,
        "state_revision": state_revision,
        "forecast": list(forecast),
    }


def _tag_forecast_items(forecast: list[Any], forecast_type: str) -> list[Any]:
    tagged: list[Any] = []
    for item in forecast:
        if isinstance(item, dict):
            tagged_item = dict(item)
            tagged_item[_FORECAST_TYPE_KEY] = forecast_type
            tagged.append(tagged_item)
        else:
            tagged.append(item)
    return tagged


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


def _weather_forecast_entries(
    attributes: dict[str, Any],
    language: str,
    *,
    forecast_items: list[Any] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    forecast = forecast_items if forecast_items is not None else _weather_forecast_items(attributes)
    unit = str(attributes.get("temperature_unit") or attributes.get("unit_of_measurement") or "C")
    entries: list[dict[str, str]] = []
    for item in forecast:
        if len(entries) >= 2:
            break
        if not isinstance(item, dict):
            continue
        condition_key = str(item.get("condition") or "").lower()
        entries.append(
            {
                "time": _weather_forecast_time_label(
                    item.get("datetime") or item.get("native_datetime") or item.get("time"),
                    item.get(_FORECAST_TYPE_KEY),
                ),
                "condition": _weather_state_label(condition_key, language),
                "condition_key": condition_key,
                "temperature": _weather_forecast_temperature(item, unit),
            }
        )
    while len(entries) < 2:
        entries.append(dict(_EMPTY_FORECAST))
    return (entries[0], entries[1])


def _weather_forecast_items(attributes: dict[str, Any]) -> list[Any]:
    for key in ("forecast", "forecasts"):
        value = attributes.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = value.get("forecast")
            if isinstance(nested, list):
                return nested
            for forecast_type in ("hourly", "daily"):
                typed_nested = value.get(forecast_type)
                if isinstance(typed_nested, list):
                    return _tag_forecast_items(typed_nested, forecast_type)
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


def _weather_sun_text(sunrise: str, sunset: str) -> str:
    if sunrise and sunset:
        return f"{sunrise}   {sunset}"
    return sunrise or sunset


def _weather_sun_times(hass: HomeAssistant) -> tuple[str, str]:
    sun_state = hass.states.get("sun.sun")
    attributes = getattr(sun_state, "attributes", None)
    if not isinstance(attributes, dict):
        return ("", "")
    sunrise = _weather_time_label(attributes.get("next_rising"))
    sunset = _weather_time_label(attributes.get("next_setting"))
    return (sunrise, sunset)


def _weather_time_label(value: Any) -> str:
    display_time = _weather_display_datetime(value)
    if display_time is None:
        return ""
    if isinstance(display_time, datetime):
        return display_time.strftime("%H:%M")
    return _dashboard_text(display_time, "", 16)


def _weather_forecast_time_label(value: Any, forecast_type: Any) -> str:
    display_time = _weather_display_datetime(value)
    if display_time is None:
        return ""
    if not isinstance(display_time, datetime):
        return _dashboard_text(display_time, "", 16)
    if forecast_type == "hourly":
        next_time = display_time + timedelta(hours=1)
        return f"{display_time.strftime('%H:%M')}-{next_time.strftime('%H:%M')}"
    if forecast_type == "daily":
        return f"{display_time.day}.{display_time.month}."
    return display_time.strftime("%H:%M")


def _weather_display_datetime(value: Any) -> datetime | str | None:
    if value in (None, ""):
        return None
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
    return cast(datetime | str | None, display_time)


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
