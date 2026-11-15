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

from dataclasses import dataclass, field
from typing import Any

ENERGY_VIEW_NOW = "now"
ENERGY_VIEW_TODAY = "today"
ENERGY_VIEW_BALANCE = "balance"
ENERGY_VIEWS = (ENERGY_VIEW_NOW, ENERGY_VIEW_TODAY, ENERGY_VIEW_BALANCE)
ENERGY_PAGE_DEFAULT_POSITION = 2

# Light tones: the display background is a saturated blue.
COLOR_SOLAR = "#ff9800"
COLOR_GRID = "#8fd0ff"
COLOR_EXPORT = "#c9a6ff"
COLOR_BATTERY = "#4db6ac"
COLOR_HOME = "#58d68d"
COLOR_COST = "#b0b8c0"

# The sums table of the Today view has room for this many rows.
_MAX_SUM_ROWS = 8

_LABELS = {
    "en": {
        "title": "Energy", "now": "Now", "today": "Today", "balance": "Balance",
        "solar": "Solar", "grid": "Grid", "home": "Home", "battery": "Battery",
        "export": "Export", "charge": "Battery charge", "discharge": "Battery discharge",
        "grid_total": "Grid total", "self_use": "Solar used at home",
        "autarky": "Self-sufficiency", "net_grid": "Net from grid", "cost": "Cost today",
        "other_grid": "Other meters",
    },
    "de": {
        "title": "Energie", "now": "Jetzt", "today": "Heute", "balance": "Bilanz",
        "solar": "PV", "grid": "Netz", "home": "Haus", "battery": "Batterie",
        "export": "Einspeisung", "charge": "Batterie laden", "discharge": "Batterie entladen",
        "grid_total": "Netz gesamt", "self_use": "PV-Eigenverbrauch",
        "autarky": "Autarkiegrad", "net_grid": "Netto vom Netz", "cost": "Kosten heute",
        "other_grid": "Weitere Zähler",
    },
    "fr": {
        "title": "Énergie", "now": "Maintenant", "today": "Aujourd'hui", "balance": "Bilan",
        "solar": "Solaire", "grid": "Réseau", "home": "Maison", "battery": "Batterie",
        "export": "Injection", "charge": "Charge batterie", "discharge": "Décharge batterie",
        "grid_total": "Réseau total", "self_use": "Autoconsommation",
        "autarky": "Autonomie", "net_grid": "Net du réseau", "cost": "Coût du jour",
        "other_grid": "Autres compteurs",
    },
    "it": {
        "title": "Energia", "now": "Ora", "today": "Oggi", "balance": "Bilancio",
        "solar": "Solare", "grid": "Rete", "home": "Casa", "battery": "Batteria",
        "export": "Immissione", "charge": "Carica batteria", "discharge": "Scarica batteria",
        "grid_total": "Rete totale", "self_use": "Autoconsumo",
        "autarky": "Autosufficienza", "net_grid": "Netto dalla rete", "cost": "Costo di oggi",
        "other_grid": "Altri contatori",
    },
}

_POWER_FACTORS = {"w": 1.0, "kw": 1000.0, "mw": 1_000_000.0, "gw": 1_000_000_000.0}


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
            add("grid_from", meter(source.get("stat_energy_from"), source.get("stat_cost"), name))
            add("grid_to", meter(source.get("stat_energy_to"), source.get("stat_compensation"), name))
            add("grid_power", _text(source.get("stat_rate")))
            # Format of Home Assistant before the unified grid connection.
            for flow in source.get("flow_from") or ():
                if isinstance(flow, dict):
                    add("grid_from", meter(flow.get("stat_energy_from"), flow.get("stat_cost"), flow.get("name")))
            for flow in source.get("flow_to") or ():
                if isinstance(flow, dict):
                    add("grid_to", meter(flow.get("stat_energy_to"), flow.get("stat_compensation"), flow.get("name")))
            for power in source.get("power") or ():
                if isinstance(power, dict):
                    add("grid_power", _text(power.get("stat_rate")))
        elif kind == "solar":
            add("solar", meter(source.get("stat_energy_from"), None, name))
            add("solar_power", _text(source.get("stat_rate")))
        elif kind == "battery":
            add("battery_from", meter(source.get("stat_energy_from"), None, name))
            add("battery_to", meter(source.get("stat_energy_to"), None, name))
            add("battery_power", _text(source.get("stat_rate")))
    return EnergySources(**{key: tuple(values) for key, values in groups.items()})


def power_watts(state: Any) -> float | None:
    """Return a power sensor's state in watts, or None when it has none."""

    try:
        value = float(getattr(state, "state", None))
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    attributes = getattr(state, "attributes", None)
    unit = str((attributes or {}).get("unit_of_measurement") or "W").strip().lower()
    factor = _POWER_FACTORS.get(unit)
    return None if factor is None else value * factor


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
    return text if language == "en" else text.replace(".", ",")


def format_energy(value: float, language: str) -> str:
    """Return an amount of energy in kWh."""

    return f"{format_number(value, language)} kWh"


def format_power(watts: float, language: str) -> str:
    """Return a power in W below one kilowatt and in kW above."""

    if abs(watts) < 1000:
        return f"{format_number(round(watts), language, 0)} W"
    return f"{format_number(watts / 1000, language)} kW"


def _sum_power(entities: tuple[str, ...], power: dict[str, float | None]) -> float | None:
    """Return the summed power, or None unless every sensor has a value."""

    if not entities:
        return None
    total = 0.0
    for entity_id in entities:
        value = power.get(entity_id)
        if value is None:
            return None
        total += value
    return total


def _direction(watts: float | None) -> int:
    """Return 1 toward the home, -1 away from it, 0 when idle or unknown."""

    if watts is None or abs(watts) < 1:
        return 0
    return 1 if watts > 0 else -1


def energy_views(value: Any) -> tuple[str, ...]:
    """Return the selected views in display order; none selected means all."""

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

    if not sources.any:
        return None
    labels = _LABELS.get(language, _LABELS["en"])
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
    grid_power = _sum_power(sources.grid_power, power)
    solar_power = _sum_power(sources.solar_power, power)
    battery_power = _sum_power(sources.battery_power, power)
    # The home's power is only known when every kind of source reports its own.
    known = [
        value for present, value in (
            (has_grid, grid_power), (bool(sources.solar), solar_power), (has_battery, battery_power),
        ) if present
    ]
    home_power = None if any(value is None for value in known) else max(0.0, sum(known))  # type: ignore[arg-type]

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
        series = [{"color": COLOR_GRID, "values": [round(value, 3) for value in grid_in]}]
        if sources.solar:
            series.append({"color": COLOR_SOLAR, "values": [round(value, 3) for value in solar]})
        if has_battery:
            series.append({"color": COLOR_BATTERY, "values": [round(value, 3) for value in discharge]})
        stacked = [sum(entry["values"][hour] for entry in series) for hour in range(24)]
        page["hours"] = {
            "max": round(max(stacked), 3),
            "label": format_energy(max(stacked), language),
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
    spent = sum(day.costs.get(meter.cost_stat, 0.0) for meter in sources.grid_from if meter.cost_stat)
    earned = sum(day.costs.get(meter.cost_stat, 0.0) for meter in sources.grid_to if meter.cost_stat)
    return spent - earned


def _format_cost(value: float, language: str, currency: str) -> str:
    amount = f"{round(value, 2) + 0.0:.2f}"
    if language != "en":
        amount = amount.replace(".", ",")
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
        earned = [day.costs[meter.cost_stat] for meter in sources.grid_to
                  if meter.cost_stat and meter.cost_stat in day.costs]
        rows.append(row(labels["export"], -totals["out"], COLOR_EXPORT,
                        -sum(earned) if earned else None))
    tail: list[dict[str, Any]] = []
    if len(sources.grid_from) != 1 or not sources.grid_from[0].name:
        spent = [day.costs[meter.cost_stat] for meter in sources.grid_from
                 if meter.cost_stat and meter.cost_stat in day.costs]
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
        costs = [value for value in map(meter_cost, merged) if value is not None]
        rows.append(row(labels["other_grid"], sum(day.total(meter) for meter in merged),
                        COLOR_GRID, sum(costs) if costs else None))
    return rows + tail
