"""Energy page of the display, built from Home Assistant's own Energy setup.

Nothing is configured twice: the meters, power sensors, names and prices are
the ones set under Settings > Dashboards > Energy. A kind of source that is
not set up there is left out of the page.

Home Assistant does all the arithmetic and sends the display finished texts
and plain numbers, so the display only places them. Sign convention, as in
Home Assistant's own Energy tables: energy supplied to the home is positive,
energy leaving it (grid export, battery charging) is negative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, TypedDict

from .dashboard_controls import finite_number
from .dashboard_energy_charts import chart_axis
from .dashboard_labels import ENERGY_LABELS_BY_LANGUAGE, decimal_text

ENERGY_VIEW_NOW = "now"
ENERGY_VIEW_TODAY = "today"
ENERGY_VIEW_POWER = "power"
ENERGY_VIEW_BALANCE = "balance"
ENERGY_VIEWS = (ENERGY_VIEW_NOW, ENERGY_VIEW_TODAY, ENERGY_VIEW_POWER, ENERGY_VIEW_BALANCE)
ENERGY_PAGE_DEFAULT_POSITION = 2

# Light tones: the display background is a saturated blue.
COLOR_SOLAR = "#ffe066"
COLOR_GRID = "#f5f8ff"
COLOR_EXPORT = "#e0aaff"
COLOR_BATTERY = "#69f0ae"
COLOR_HOME = "#ff9a8b"
COLOR_COST = "#e3e9f1"

# The sums table of the Today view has room for this many rows.
_MAX_SUM_ROWS = 8

# Spelled as Home Assistant spells them: "mW" and "MW" differ only in case.
_POWER_FACTORS = {"mW": 0.001, "W": 1.0, "kW": 1000.0, "MW": 1_000_000.0, "GW": 1_000_000_000.0}


class _EnergyBarSeries(TypedDict):
    """One colored series of hourly energy values."""

    color: str
    values: list[float]


@dataclass(frozen=True, slots=True)
class EnergyMeter:
    """One energy meter with its optional cost statistic and name."""

    stat: str
    cost_stat: str | None = None
    name: str = ""


@dataclass(frozen=True, slots=True)
class EnergySources:
    """The sources of Home Assistant's Energy setup the page can show."""

    grid_from: tuple[EnergyMeter, ...] = ()
    grid_to: tuple[EnergyMeter, ...] = ()
    solar: tuple[EnergyMeter, ...] = ()
    battery_from: tuple[EnergyMeter, ...] = ()
    battery_to: tuple[EnergyMeter, ...] = ()
    grid_power: tuple[str, ...] = ()
    solar_power: tuple[str, ...] = ()
    battery_power: tuple[str, ...] = ()
    grid_power_complete: bool = True

    @property
    def any(self) -> bool:
        """Return whether there is anything to show."""

        return bool(self.grid_from or self.grid_to or self.solar
                    or self.battery_from or self.battery_to)

    @property
    def energy_stats(self) -> set[str]:
        """Return the statistic ids of all energy meters."""

        return {
            meter.stat
            for group in (self.grid_from, self.grid_to, self.solar,
                          self.battery_from, self.battery_to)
            for meter in group
        }

    @property
    def cost_stats(self) -> set[str]:
        """Return the statistic ids of all cost and compensation totals."""

        return {
            meter.cost_stat
            for meter in (*self.grid_from, *self.grid_to)
            if meter.cost_stat
        }

    @property
    def power_entities(self) -> set[str]:
        """Return the entity ids of all power sensors."""

        return {*self.grid_power, *self.solar_power, *self.battery_power}


@dataclass(slots=True)
class EnergyDay:
    """What the meters counted today, per local hour, and what it cost."""

    hours: dict[str, list[float]] = field(default_factory=dict)
    costs: dict[str, float] = field(default_factory=dict)

    def hourly(self, meters: tuple[EnergyMeter, ...]) -> list[float]:
        """Return the summed hourly values of several meters."""

        total = [0.0] * 24
        for meter in meters:
            for hour, value in enumerate(self.hours.get(meter.stat, ())):
                total[hour] += value
        return total

    def total(self, meter: EnergyMeter) -> float:
        """Return what one meter counted today."""

        return sum(self.hours.get(meter.stat, ()))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def energy_sources(
    preferences: Any, cost_sensors: Any = None,
) -> EnergySources:
    """Return the sources from Home Assistant's Energy preferences.

    A meter whose costs Home Assistant works out from a price has no cost
    statistic of its own in the preferences; ``cost_sensors`` maps such a
    meter to the cost sensor Home Assistant created for it.
    """

    generated = cost_sensors if isinstance(cost_sensors, dict) else {}
    groups: dict[str, list[Any]] = {
        "grid_from": [], "grid_to": [], "solar": [], "battery_from": [],
        "battery_to": [], "grid_power": [], "solar_power": [], "battery_power": [],
    }
    grid_power_complete = True

    def meter(stat: Any, cost: Any, name: Any) -> EnergyMeter | None:
        stat_id = _text(stat)
        if not stat_id:
            return None
        return EnergyMeter(stat_id, _text(cost) or _text(generated.get(stat_id)) or None, _text(name))

    def add(group: str, value: Any) -> None:
        if value and value not in groups[group]:
            groups[group].append(value)

    sources = preferences.get("energy_sources") if isinstance(preferences, dict) else None
    for source in sources if isinstance(sources, list) else ():
        if not isinstance(source, dict):
            continue
        kind = source.get("type")
        name = source.get("name")
        if kind == "grid":
            grid_from = [meter(source.get("stat_energy_from"), source.get("stat_cost"), name)]
            grid_to = [meter(source.get("stat_energy_to"), source.get("stat_compensation"), name)]
            grid_power = [_text(source.get("stat_rate"))]
            # Format of Home Assistant before the unified grid connection.
            for flow in source.get("flow_from") or ():
                if isinstance(flow, dict):
                    grid_from.append(meter(flow.get("stat_energy_from"), flow.get("stat_cost"), flow.get("name")))
            for flow in source.get("flow_to") or ():
                if isinstance(flow, dict):
                    grid_to.append(meter(flow.get("stat_energy_to"), flow.get("stat_compensation"), flow.get("name")))
            for power in source.get("power") or ():
                if isinstance(power, dict):
                    grid_power.append(_text(power.get("stat_rate")))
            # Coverage belongs to the connection, not to its tariff meter count.
            if any(grid_from + grid_to) and not any(grid_power):
                grid_power_complete = False
            for group, values in (("grid_from", grid_from), ("grid_to", grid_to),
                                  ("grid_power", grid_power)):
                for value in values:
                    add(group, value)
        elif kind == "solar":
            add("solar", meter(source.get("stat_energy_from"), None, name))
            add("solar_power", _text(source.get("stat_rate")))
        elif kind == "battery":
            add("battery_from", meter(source.get("stat_energy_from"), None, name))
            add("battery_to", meter(source.get("stat_energy_to"), None, name))
            add("battery_power", _text(source.get("stat_rate")))
    return EnergySources(
        **{key: tuple(values) for key, values in groups.items()},
        grid_power_complete=grid_power_complete,
    )


def power_watts(state: Any) -> float | None:
    """Return a power sensor's state in watts, or None when it has none."""

    value = finite_number(getattr(state, "state", None))
    if value is None:
        return None
    attributes = getattr(state, "attributes", None)
    unit = str((attributes or {}).get("unit_of_measurement") or "W").strip()
    factor = _POWER_FACTORS.get(unit)
    watts = None if factor is None else value * factor
    return watts if watts is not None and math.isfinite(watts) else None


def format_number(value: float, language: str, digits: int | None = None) -> str:
    """Return a number the way the display language writes it.

    Without ``digits`` small values keep two decimals and large ones none, so
    the text stays short enough for a circle of the flow picture.
    """

    if digits is None:
        magnitude = abs(value)
        digits = 2 if magnitude < 10 else 1 if magnitude < 100 else 0
    text = f"{value:.{digits}f}"
    if digits and "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "-0.0"):
        text = "0"
    return decimal_text(text, language)


def format_energy(value: float, language: str) -> str:
    """Return an amount of energy in kWh."""

    return f"{format_number(value, language)} kWh"


def format_power(watts: float, language: str) -> str:
    """Return a power in W below one kilowatt and in kW above."""

    if abs(round(watts)) < 1000:
        return f"{format_number(round(watts), language, 0)} W"
    return f"{format_number(watts / 1000, language)} kW"


def _sum_power(entities: tuple[str, ...], power: dict[str, float | None]) -> float | None:
    """Return the summed power, or None unless every sensor has a value."""

    if not entities:
        return None
    total = 0.0
    for entity_id in entities:
        value = power.get(entity_id)
        if value is None or not math.isfinite(value):
            return None
        total += value
    return total if math.isfinite(total) else None


def _direction(watts: float | None) -> int:
    """Return 1 toward the home, -1 away from it, 0 when idle or unknown."""

    if watts is None or abs(watts) < 1:
        return 0
    return 1 if watts > 0 else -1


def energy_views(value: Any) -> tuple[str, ...]:
    """Return selected views in display order, preserving an explicit all-off."""

    if isinstance(value, (list, tuple)) and not value:
        return ()
    chosen = [view for view in ENERGY_VIEWS if isinstance(value, (list, tuple)) and view in value]
    return tuple(chosen) or ENERGY_VIEWS


def normalize_energy_page(value: Any) -> dict[str, Any]:
    """Return the stored settings of the energy page, complete and valid.

    The page is off unless switched on. Its position counts among all pages
    of the display, 1 being the first; the default puts it second.
    """

    data = value if isinstance(value, dict) else {}
    try:
        position = int(float(data.get("position", ENERGY_PAGE_DEFAULT_POSITION)))
    except (TypeError, ValueError, OverflowError):
        position = ENERGY_PAGE_DEFAULT_POSITION
    return {
        "enabled": data.get("enabled") is True,
        "position": max(1, position),
        "views": list(energy_views(data.get("views"))),
    }


def source_power_watts(
    sources: EnergySources, power: dict[str, float | None],
) -> dict[str, float | None]:
    """Aggregate live or historical samples with identical coverage rules."""

    has_grid = bool(sources.grid_from or sources.grid_to)
    has_battery = bool(sources.battery_from or sources.battery_to)
    grid = _sum_power(sources.grid_power, power) if sources.grid_power_complete else None
    solar = (_sum_power(sources.solar_power, power)
             if len(sources.solar_power) >= len(sources.solar) else None)
    batteries = max(len(sources.battery_from), len(sources.battery_to))
    battery = (_sum_power(sources.battery_power, power)
               if len(sources.battery_power) >= batteries else None)
    values = {key: watts for key, present, watts in (
        ("grid", has_grid, grid), ("solar", bool(sources.solar), solar),
        ("battery", has_battery, battery),
    ) if present}
    known = [value for value in values.values() if value is not None]
    total = sum(known)
    values["home"] = (
        max(0.0, total) if values and len(known) == len(values) and math.isfinite(total)
        else None
    )
    return values


def energy_page(
    sources: EnergySources,
    day: EnergyDay,
    power: dict[str, float | None],
    *,
    language: str = "en",
    views: Any = None,
    currency: str = "",
) -> dict[str, Any] | None:
    """Return the display page for one day, or None without any source."""

    if not sources.any or not energy_views(views):
        return None
    labels = ENERGY_LABELS_BY_LANGUAGE.get(language, ENERGY_LABELS_BY_LANGUAGE["en"])
    shown = energy_views(views)

    grid_in = day.hourly(sources.grid_from)
    grid_out = day.hourly(sources.grid_to)
    solar = day.hourly(sources.solar)
    discharge = day.hourly(sources.battery_from)
    charge = day.hourly(sources.battery_to)
    total_in, total_out, total_solar = sum(grid_in), sum(grid_out), sum(solar)
    total_discharge, total_charge = sum(discharge), sum(charge)
    # A meter that counts late can push the day's use below zero.
    total_used = max(0.0, total_in + total_solar + total_discharge - total_out - total_charge)

    has_grid = bool(sources.grid_from or sources.grid_to)
    has_battery = bool(sources.battery_from or sources.battery_to)
    powers = source_power_watts(sources, power)
    grid_power, solar_power = powers.get("grid"), powers.get("solar")
    battery_power, home_power = powers.get("battery"), powers.get("home")

    page: dict[str, Any] = {
        "views": [{"id": view, "label": labels[view]} for view in shown],
    }

    if ENERGY_VIEW_NOW in shown:
        nodes: dict[str, Any] = {}

        def node(key: str, color: str, lines: list[str], watts: float | None, toward_home: int) -> None:
            entry: dict[str, Any] = {"label": labels[key], "color": color, "lines": lines}
            if watts is not None:
                entry["power"] = format_power(abs(watts), language)
            entry["flow"] = toward_home
            nodes[key] = entry

        if sources.solar:
            node("solar", COLOR_SOLAR, [format_energy(total_solar, language)],
                 solar_power, _direction(solar_power))
        if has_grid:
            lines = [format_energy(total_in, language)] if sources.grid_from else []
            if sources.grid_to:
                lines.append(format_energy(-total_out, language))
            node("grid", COLOR_GRID, lines, grid_power, _direction(grid_power))
        if has_battery:
            lines = [format_energy(total_discharge, language)] if sources.battery_from else []
            if sources.battery_to:
                lines.append(format_energy(-total_charge, language))
            node("battery", COLOR_BATTERY, lines, battery_power, _direction(battery_power))
        node("home", COLOR_HOME, [format_energy(total_used, language)],
             home_power, _direction(home_power))
        page["nodes"] = nodes

    if ENERGY_VIEW_TODAY in shown:
        # A meter correction can make an hour negative; a bar cannot be.
        series: list[_EnergyBarSeries] = [
            {"color": color, "values": [round(max(0.0, value), 3) for value in values]}
            for present, color, values in (
                (sources.grid_from, COLOR_GRID, grid_in),
                (sources.solar, COLOR_SOLAR, solar),
                (sources.battery_from, COLOR_BATTERY, discharge),
            ) if present
        ]
        stacked = [sum(entry["values"][hour] for entry in series) for hour in range(24)]
        page["hours"] = {
            "max": round(max(stacked), 3),
            "label": format_energy(max(stacked), language),
            "axis": chart_axis(0.0, max(stacked), language, "kWh"),
            "series": series,
        }
        page["sums"] = _sum_rows(sources, day, labels, language, currency, {
            "solar": total_solar, "discharge": total_discharge, "charge": total_charge,
            "out": total_out, "in": total_in,
        })

    if ENERGY_VIEW_BALANCE in shown:
        rows: list[dict[str, Any]] = []
        if sources.solar and total_solar > 0:
            ratio = max(0.0, min(1.0, (total_solar - min(total_out, total_solar)) / total_solar))
            rows.append(_ratio_row(labels["self_use"], ratio, COLOR_SOLAR, language))
        if has_grid and total_used > 0:
            ratio = max(0.0, min(1.0, 1 - total_in / total_used))
            rows.append(_ratio_row(labels["autarky"], ratio, COLOR_HOME, language))
        if has_grid:
            net = total_in - total_out
            share = max(0.0, min(1.0, net / total_used)) if total_used > 0 else 0.0
            rows.append({
                "label": labels["net_grid"], "value": format_energy(net, language),
                "ratio": round(share, 3), "color": COLOR_GRID if net >= 0 else COLOR_EXPORT,
            })
        cost = _total_cost(sources, day)
        if cost is not None:
            rows.append({
                "label": labels["cost"], "value": _format_cost(cost, language, currency),
                "color": COLOR_COST,
            })
        page["balance"] = rows

    return {"title": labels["title"], "energy": page}


def _ratio_row(label: str, ratio: float, color: str, language: str) -> dict[str, Any]:
    return {
        "label": label,
        "value": f"{format_number(ratio * 100, language, 0)} %",
        "ratio": round(ratio, 3),
        "color": color,
    }


def _total_cost(sources: EnergySources, day: EnergyDay) -> float | None:
    """Return today's cost less the compensation, or None without any price."""

    if not sources.cost_stats:
        return None
    return sum(_costs(day, sources.grid_from)) - sum(_costs(day, sources.grid_to))


def _costs(day: EnergyDay, meters: tuple[EnergyMeter, ...] | list[EnergyMeter]) -> list[float]:
    """Return the known costs of some meters; a meter without a price has none."""

    return [day.costs[meter.cost_stat] for meter in meters
            if meter.cost_stat and meter.cost_stat in day.costs]


def _format_cost(value: float, language: str, currency: str) -> str:
    amount = decimal_text(f"{round(value, 2) + 0.0:.2f}", language)
    return f"{amount} {currency}".strip()


def _sum_rows(
    sources: EnergySources,
    day: EnergyDay,
    labels: dict[str, str],
    language: str,
    currency: str,
    totals: dict[str, float],
) -> list[dict[str, Any]]:
    """Return the rows of the Today table, most important first."""

    def row(label: str, value: float, color: str, cost: float | None = None) -> dict[str, Any]:
        entry = {"label": label, "value": format_energy(value, language), "color": color}
        if cost is not None:
            entry["cost"] = _format_cost(cost, language, currency)
        return entry

    def meter_cost(meter: EnergyMeter) -> float | None:
        return day.costs.get(meter.cost_stat) if meter.cost_stat else None

    rows: list[dict[str, Any]] = []
    if sources.solar:
        rows.append(row(labels["solar"], totals["solar"], COLOR_SOLAR))
    if sources.battery_from:
        rows.append(row(labels["discharge"], totals["discharge"], COLOR_BATTERY))
    if sources.battery_to:
        rows.append(row(labels["charge"], -totals["charge"], COLOR_BATTERY))
    if sources.grid_to:
        earned = _costs(day, sources.grid_to)
        rows.append(row(labels["export"], -totals["out"], COLOR_EXPORT,
                        -sum(earned) if earned else None))
    tail: list[dict[str, Any]] = []
    if len(sources.grid_from) != 1 or not sources.grid_from[0].name:
        spent = _costs(day, sources.grid_from)
        if sources.grid_from:
            tail.append(row(labels["grid_total"], totals["in"], COLOR_GRID,
                            sum(spent) if spent else None))
    named = [meter for meter in sources.grid_from if len(sources.grid_from) > 1 or meter.name]
    room = _MAX_SUM_ROWS - len(rows) - len(tail)
    if len(named) > room:
        # The meters that do not fit are shown as one row, so the sums add up.
        kept, merged = named[: max(0, room - 1)], named[max(0, room - 1):]
    else:
        kept, merged = named, []
    for meter in kept:
        rows.append(row(meter.name or meter.stat, day.total(meter), COLOR_GRID, meter_cost(meter)))
    if merged:
        costs = _costs(day, merged)
        rows.append(row(labels["other_grid"], sum(day.total(meter) for meter in merged),
                        COLOR_GRID, sum(costs) if costs else None))
    return rows + tail
