"""Bounded, readable chart axes prepared in HA rather than on the display."""

from __future__ import annotations

import math
from typing import Any

from .dashboard_labels import decimal_text


def chart_axis(low: float, high: float, language: str, unit: str) -> dict[str, Any]:
    """Include zero and provide at most five evenly spaced, rounded ticks.

    Positions and bounds retain the input unit. Only labels share a scaled
    display unit, so a small and a large series can never use different scales.
    """

    low = min(0.0, low) if math.isfinite(low) else 0.0
    high = max(0.0, high) if math.isfinite(high) else 0.0
    if high <= low:
        high = 1.0
    span = high - low
    if not math.isfinite(span):
        return chart_axis(0.0, 1.0, language, unit)
    target = max(span / 3, 1e-12)
    magnitude = 10.0 ** math.floor(math.log10(target))
    step = next(factor * magnitude for factor in (1, 2, 2.5, 5, 10)
                if factor * magnitude >= target)
    bottom, top = math.floor(low / step), math.ceil(high / step)
    count = top - bottom
    lower, upper = bottom * step, top * step
    if not math.isfinite(lower) or not math.isfinite(upper):
        return chart_axis(0.0, 1.0, language, unit)
    maximum = max(abs(lower), abs(upper))
    divisor, shown_unit = 1.0, unit
    if unit == "W" and maximum >= 1_000_000:
        divisor, shown_unit = 1_000_000.0, "MW"
    elif unit == "W" and maximum >= 1000:
        divisor, shown_unit = 1000.0, "kW"
    elif unit == "kWh" and maximum >= 1000:
        divisor, shown_unit = 1000.0, "MWh"
    shown_step = step / divisor
    digits = max(0, min(6, -math.floor(math.log10(shown_step)) + 1))

    def label(value: float) -> str:
        value = value / divisor + 0.0
        if shown_step < 0.000001:
            text = f"{value:.2g}"
        else:
            text = f"{value:.{digits}f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
        return decimal_text(text, language)

    return {
        "min": lower, "max": upper, "unit": shown_unit,
        "ticks": [
            {"value": (bottom + index) * step,
             "label": label((bottom + index) * step), "position": index / count}
            for index in range(count + 1)
        ],
    }
