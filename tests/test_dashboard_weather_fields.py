"""The weather data holds exactly what the display reads.

`title`, `forecast`, `sun` and `badge` were built and sent with every
dashboard answer although the display reads none of them: it draws the two
forecast tiles from `forecast_1`/`forecast_2` and the sun times from
`sunrise`/`sunset`.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from homeassistant.core import State

from custom_components.bticino_c300x.dashboard_weather import dashboard_weather_payload

ROOT = Path(__file__).resolve().parents[1]


def _display_fields() -> set[str]:
    source = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(encoding="utf-8")
    body = source.split("function applyWeather(pageItem, source) {", 1)[1].split("\n}\n", 1)[0]
    return set(re.findall(r"\bsource\.([a-z_0-9]+)", body))


def _hass(*states: State) -> SimpleNamespace:
    known = {state.entity_id: state for state in states}
    return SimpleNamespace(states=SimpleNamespace(get=known.get))


def test_weather_data_has_only_the_fields_the_display_reads():
    fields = _display_fields()
    assert {"available", "condition_key", "forecast_1", "sunrise", "color"} <= fields

    present = dashboard_weather_payload(
        _hass(State("weather.home", "sunny", {"temperature": 21, "humidity": 40})),
        "weather.home", "en",
    )
    missing = dashboard_weather_payload(_hass(), "weather.home", "en")

    assert present is not None and missing is not None
    assert set(present) == fields
    assert set(missing) == fields
