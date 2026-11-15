from __future__ import annotations

import asyncio
import types
from typing import Any
from unittest.mock import AsyncMock

import pytest
from test_executor import FakeEntry, FakeHass, FakeState, FakeStates, run

from custom_components.bticino_c300x import (
    dashboard,
    dashboard_energy_data,
    dashboard_energy_updates,
)
from custom_components.bticino_c300x.config_flow_dashboard_pages import (
    dashboard_pages_input,
    dashboard_pages_schema,
)
from custom_components.bticino_c300x.const import (
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PAGES,
    CONF_DEVICE_UI_ENABLED,
    CONF_ENERGY_PAGE,
)
from custom_components.bticino_c300x.dashboard_energy import (
    ENERGY_VIEWS,
    EnergyDay,
    EnergyMeter,
    EnergySources,
    normalize_energy_page,
)

SOURCES = EnergySources(
    grid_from=(EnergyMeter("sensor.grid", "sensor.grid_cost"),),
    solar=(EnergyMeter("sensor.pv"),),
    grid_power=("sensor.grid_power",),
)
ENERGY_ON = {"enabled": True, "position": 2, "views": list(ENERGY_VIEWS)}


@pytest.fixture(autouse=True)
def _no_kept_statistics():
    dashboard_energy_data._DAY_CACHE.clear()
    yield
    dashboard_energy_data._DAY_CACHE.clear()


@pytest.mark.parametrize(("stored", "expected"), [
    (None, {"enabled": False, "position": 2, "views": list(ENERGY_VIEWS)}),
    ({"enabled": True}, ENERGY_ON),
    ({"enabled": "yes", "position": "x", "views": ["bogus"]},
     {"enabled": False, "position": 2, "views": list(ENERGY_VIEWS)}),
    ({"enabled": True, "position": 0, "views": ["balance", "now"]},
     {"enabled": True, "position": 1, "views": ["now", "balance"]}),
    ({"enabled": True, "position": 9.0}, {**ENERGY_ON, "position": 9}),
    (["now"], {"enabled": False, "position": 2, "views": list(ENERGY_VIEWS)}),
])
def test_stored_energy_page_is_off_by_default_and_second(stored, expected) -> None:
    assert normalize_energy_page(stored) == expected


def test_statistics_are_sorted_into_local_hours_and_costs() -> None:
    hourly = {
        "sensor.grid": [
            {"start": 0.0, "end": 3600.0, "change": 1.5},
            {"start": 3600.0, "end": 7200.0, "change": 0.5},
            {"start": 7200.0, "end": 10800.0, "change": None},
        ],
        "sensor.grid_cost": [{"start": 0.0, "end": 3600.0, "change": 0.45}],
        "sensor.pv": [],
    }
    recent = {
        "sensor.grid": [{"start": 7200.0, "end": 7500.0, "change": 0.25},
                        {"start": 7500.0, "end": 7800.0, "change": 0.25}],
        "sensor.grid_cost": [{"start": 7200.0, "end": 7500.0, "change": 0.05}],
    }

    day = dashboard_energy_data.energy_day_from_statistics(
        SOURCES, (hourly, recent), lambda timestamp: int(timestamp // 3600) + 1,
    )

    assert day.hours["sensor.grid"][:5] == [0.0, 1.5, 0.5, 0.5, 0.0]
    assert "sensor.pv" not in day.hours and "sensor.grid_cost" not in day.hours
    assert day.costs == {"sensor.grid_cost": 0.5}


def _entry(energy: Any = None, **options: Any) -> FakeEntry:
    if energy is not None:
        options[CONF_ENERGY_PAGE] = energy
    return FakeEntry(data={CONF_DEVICE_UI_ENABLED: True}, options=options)


def _energy_hass(states: dict[str, FakeState] | None = None) -> FakeHass:
    hass = FakeHass(states=FakeStates(states or {}))
    hass.config = types.SimpleNamespace(language="de", currency="EUR", components={"energy"})
    return hass


def test_no_energy_page_without_the_switch_or_without_energy_in_home_assistant(monkeypatch) -> None:
    read = AsyncMock()
    monkeypatch.setattr(dashboard_energy_data, "_async_read_energy_day", read)

    assert run(dashboard_energy_data.async_energy_dashboard_page(_energy_hass(), _entry(), "de")) is None
    assert run(dashboard_energy_data.async_energy_dashboard_page(FakeHass(), _entry(ENERGY_ON), "de")) is None
    read.assert_not_awaited()


def test_page_combines_kept_statistics_with_current_power(monkeypatch) -> None:
    day = EnergyDay(hours={"sensor.grid": [1.0] + [0.0] * 23, "sensor.pv": [0.5] + [0.0] * 23},
                    costs={"sensor.grid_cost": 0.3})
    read = AsyncMock(return_value=day)
    monkeypatch.setattr(dashboard_energy_data, "_async_read_energy_day", read)
    monkeypatch.setattr(dashboard_energy_data, "async_configured_energy_sources",
                        AsyncMock(return_value=SOURCES))
    clock = [1000.0]
    monkeypatch.setattr(dashboard_energy_data, "monotonic", lambda: clock[0])
    hass = _energy_hass({"sensor.grid_power": FakeState("0.4", attributes={"unit_of_measurement": "kW"})})
    entry = _entry({**ENERGY_ON, "views": ["now", "balance"]})

    page = run(dashboard_energy_data.async_energy_dashboard_page(hass, entry, "de"))

    assert page["title"] == "Energie"
    assert [view["id"] for view in page["energy"]["views"]] == ["now", "balance"]
    assert page["energy"]["nodes"]["grid"] == {
        "label": "Netz", "color": "#8fd0ff", "lines": ["1 kWh"], "power": "400 W", "flow": 1,
    }
    assert page["energy"]["balance"][-1] == {"label": "Kosten heute", "value": "0,30 €", "color": "#b0b8c0"}
    # The display asks on every event: the statistics are read once per five minutes.
    hass.states.values["sensor.grid_power"] = FakeState("50")
    clock[0] += 299.0
    again = run(dashboard_energy_data.async_energy_dashboard_page(hass, entry, "de"))
    assert again["energy"]["nodes"]["grid"]["power"] == "50 W"
    assert read.await_count == 1
    clock[0] += 2.0
    run(dashboard_energy_data.async_energy_dashboard_page(hass, entry, "de"))
    assert read.await_count == 2


def test_failed_statistics_read_keeps_today_but_never_shows_another_day(monkeypatch) -> None:
    from homeassistant.util import dt as dt_util

    day = EnergyDay(hours={"sensor.grid": [2.0] + [0.0] * 23})
    read = AsyncMock(side_effect=[day, RuntimeError("database busy"), RuntimeError("database busy")])
    monkeypatch.setattr(dashboard_energy_data, "_async_read_energy_day", read)
    monkeypatch.setattr(dashboard_energy_data, "async_configured_energy_sources",
                        AsyncMock(return_value=SOURCES))
    clock = [1000.0]
    monkeypatch.setattr(dashboard_energy_data, "monotonic", lambda: clock[0])
    hass, entry = _energy_hass(), _entry(ENERGY_ON)

    def grid_line() -> str:
        page = run(dashboard_energy_data.async_energy_dashboard_page(hass, entry, "de"))
        return page["energy"]["nodes"]["grid"]["lines"][0]

    assert grid_line() == "2 kWh"
    clock[0] += 400.0
    assert grid_line() == "2 kWh"
    tomorrow = dt_util.start_of_local_day() + dt_util.dt.timedelta(days=1)
    monkeypatch.setattr(dt_util, "start_of_local_day", lambda: tomorrow)
    clock[0] += 400.0
    assert grid_line() == "0 kWh"
    assert read.await_count == 3


def _payload_pages(monkeypatch, energy_setting: Any, position_pages: int = 3) -> list[str]:
    names = ["C300X", "Wohnen", "Keller"][:position_pages]
    states = {f"sensor.s{index}": FakeState("1", attributes={"friendly_name": f"S{index}"})
              for index in range(position_pages)}
    entry = _entry(
        energy_setting,
        **{
            CONF_DASHBOARD_ENTITIES: list(states),
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                entity_id: {"page": names[index]} for index, entity_id in enumerate(states)
            },
            CONF_DASHBOARD_PAGES: [{"name": name, "order": index + 1} for index, name in enumerate(names)],
        },
    )
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(
        return_value={"title": "Energie", "energy": {"views": []}}
        if normalize_energy_page(energy_setting)["enabled"] else None
    ))
    result = run(dashboard.async_dashboard_payload(FakeHass(states=FakeStates(states)), entry))
    return [page["title"] for page in result["data"]["pages"]]


@pytest.mark.parametrize(("position", "expected"), [
    (1, ["Energie", "C300X", "Wohnen", "Keller"]),
    (2, ["C300X", "Energie", "Wohnen", "Keller"]),
    (4, ["C300X", "Wohnen", "Keller", "Energie"]),
    (9, ["C300X", "Wohnen", "Keller", "Energie"]),
])
def test_energy_page_takes_its_position_among_the_shown_pages(monkeypatch, position, expected) -> None:
    assert _payload_pages(monkeypatch, {**ENERGY_ON, "position": position}) == expected


def test_energy_page_position_counts_a_page_the_display_leaves_out(monkeypatch) -> None:
    # The status page is configured first but has nothing to show. The form
    # numbers it all the same, so position 3 means "after Wohnen".
    names = ["C300X", "Wohnen", "Keller"]
    states = {f"sensor.s{index}": FakeState("1", attributes={"friendly_name": f"S{index}"})
              for index in (1, 2)}
    entry = _entry(
        {**ENERGY_ON, "position": 3},
        **{
            CONF_DASHBOARD_ENTITIES: list(states),
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.s1": {"page": "Wohnen"}, "sensor.s2": {"page": "Keller"},
            },
            CONF_DASHBOARD_PAGES: [{"name": name, "order": index + 1} for index, name in enumerate(names)],
        },
    )
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(
        return_value={"title": "Energie", "energy": {"views": []}}
    ))

    result = run(dashboard.async_dashboard_payload(FakeHass(states=FakeStates(states)), entry))

    assert [page["title"] for page in result["data"]["pages"]] == ["Wohnen", "Energie", "Keller"]


def test_energy_page_position_counts_a_configured_page_without_tiles(monkeypatch) -> None:
    # "Garten" is configured second but has no tile, so it never becomes a
    # page. The form numbers it all the same: position 3 means "before Keller".
    names = ["C300X", "Garten", "Keller"]
    states = {f"sensor.s{index}": FakeState("1", attributes={"friendly_name": f"S{index}"})
              for index in (1, 2)}
    entry = _entry(
        {**ENERGY_ON, "position": 3},
        **{
            CONF_DASHBOARD_ENTITIES: list(states),
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {
                "sensor.s1": {"page": "C300X"}, "sensor.s2": {"page": "Keller"},
            },
            CONF_DASHBOARD_PAGES: [{"name": name, "order": index + 1} for index, name in enumerate(names)],
        },
    )
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(
        return_value={"title": "Energie", "energy": {"views": []}}
    ))

    result = run(dashboard.async_dashboard_payload(FakeHass(states=FakeStates(states)), entry))

    assert [page["title"] for page in result["data"]["pages"]] == ["C300X", "Energie", "Keller"]


def test_the_display_learns_which_decimal_sign_home_assistant_writes(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(return_value=None))
    german = FakeHass()
    german.config = types.SimpleNamespace(language="de")
    english = FakeHass()
    english.config = types.SimpleNamespace(language="en-GB")

    assert run(dashboard.async_dashboard_payload(german, _entry()))["decimalComma"] is True
    assert run(dashboard.async_dashboard_payload(english, _entry()))["decimalComma"] is False


def test_a_shortened_choice_list_shortens_its_texts_too() -> None:
    options = [f"option_{index:04d}" for index in range(2000)]
    control = {"kind": "choice", "options": list(options), "labels": [f"Text {o}" for o in options]}
    payload = {"data": {"pages": [{"items": [{"kind": "detail", "controls": [control]}]}]}}

    dashboard._fit_dashboard_response(_entry(), payload)

    assert len(control["options"]) < 2000
    assert len(control["labels"]) == len(control["options"])


def test_display_pages_are_unchanged_without_the_energy_page(monkeypatch) -> None:
    assert _payload_pages(monkeypatch, None) == ["C300X", "Wohnen", "Keller"]
    assert _payload_pages(monkeypatch, {**ENERGY_ON, "enabled": False}) == ["C300X", "Wohnen", "Keller"]


def test_energy_page_reaches_the_display_as_its_own_page(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "async_energy_dashboard_page", AsyncMock(
        return_value={"title": "Energie", "energy": {"views": [{"id": "now", "label": "Jetzt"}]}}
    ))

    result = run(dashboard.async_dashboard_payload(FakeHass(), _entry(ENERGY_ON)))

    # No other page has content: the energy page alone is shown.
    assert result["data"]["pages"] == [
        {"title": "Energie", "energy": {"views": [{"id": "now", "label": "Jetzt"}]}},
    ]


SAVED = {
    CONF_DASHBOARD_ENTITIES: ["sensor.a", "sensor.b"],
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: {"sensor.a": {"page": "C300X"}, "sensor.b": {"page": "Wohnen"}},
    CONF_DASHBOARD_PAGES: [{"name": "C300X", "order": 1}, {"name": "Wohnen", "order": 2}],
}


def _post(energy: dict[str, Any] | None, **positions: int) -> dict[str, Any]:
    post: dict[str, Any] = {
        "page_1": {"entities": ["sensor.a"], "position": positions.get("status", 1)},
        "page_2": {"name": "Wohnen", "entities": ["sensor.b"], "position": positions.get("second", 2)},
    }
    if energy is not None:
        post["energy_page"] = energy
    return post


def _section_defaults(schema: Any, key: str) -> dict[str, Any]:
    section = next(value for marker, value in schema.schema.items() if str(marker) == key)
    defaults: dict[str, Any] = {"collapsed": section.options["collapsed"]}
    for marker in section.schema.schema:
        suggested = (marker.description or {}).get("suggested_value")
        defaults[str(marker)] = suggested if suggested is not None else (
            marker.default() if callable(getattr(marker, "default", None)) else None
        )
    return defaults


def test_pages_form_offers_the_energy_page_switched_off_at_position_two() -> None:
    schema = dashboard_pages_schema(SAVED)

    assert _section_defaults(schema, "energy_page") == {
        "collapsed": True, "enabled": False, "position": 2, "views": list(ENERGY_VIEWS),
    }
    assert _section_defaults(schema, "page_2")["position"] == 2


def test_saving_the_form_unchanged_keeps_the_energy_page_off() -> None:
    saved, errors = dashboard_pages_input(SAVED, _post({"enabled": False, "position": 2}))

    assert errors == {}
    assert saved[CONF_ENERGY_PAGE] == {"enabled": False, "position": 2, "views": list(ENERGY_VIEWS)}
    assert saved[CONF_DASHBOARD_PAGES] == SAVED[CONF_DASHBOARD_PAGES]


def test_switched_on_the_energy_page_is_second_before_the_page_with_the_same_position() -> None:
    saved, errors = dashboard_pages_input(SAVED, _post({"enabled": True, "position": 2, "views": ["now"]}))

    assert errors == {}
    assert saved[CONF_ENERGY_PAGE] == {"enabled": True, "position": 2, "views": ["now"]}
    # The other pages stay numbered among themselves.
    assert saved[CONF_DASHBOARD_PAGES] == SAVED[CONF_DASHBOARD_PAGES]
    # Shown again, every page has the position it has on the display.
    schema = dashboard_pages_schema(saved)
    assert _section_defaults(schema, "page_1")["position"] == 1
    assert _section_defaults(schema, "energy_page") == {
        "collapsed": False, "enabled": True, "position": 2, "views": ["now"],
    }
    assert _section_defaults(schema, "page_2")["position"] == 3
    # Saving that form again changes nothing.
    again, _ = dashboard_pages_input(saved, _post({"enabled": True, "position": 2, "views": ["now"]}, second=3))
    assert again[CONF_ENERGY_PAGE] == saved[CONF_ENERGY_PAGE]
    assert again[CONF_DASHBOARD_PAGES] == saved[CONF_DASHBOARD_PAGES]


@pytest.mark.parametrize(("energy_position", "second", "expected"), [
    (1, 2, 1), (3, 2, 3), (9, 2, 3), (None, 2, 2), (2, 1, 2),
])
def test_energy_page_position_counts_among_the_used_pages(energy_position, second, expected) -> None:
    energy = {"enabled": True}
    if energy_position is not None:
        energy["position"] = energy_position

    saved, errors = dashboard_pages_input(SAVED, _post(energy, second=second, status=2 if second == 1 else 1))

    assert errors == {}
    assert saved[CONF_ENERGY_PAGE]["position"] == expected


def test_a_post_without_the_energy_section_keeps_the_saved_energy_page() -> None:
    saved, errors = dashboard_pages_input({**SAVED, CONF_ENERGY_PAGE: {**ENERGY_ON, "position": 3}}, _post(None))

    assert errors == {}
    assert saved[CONF_ENERGY_PAGE] == {**ENERGY_ON, "position": 3}


class _Helpers:
    """Stand-ins for Home Assistant's event helpers, driven by the test."""

    def __init__(self, monkeypatch) -> None:
        from homeassistant.helpers import event

        self.tracked: list[str] = []
        self.power_callback: Any = None
        self.tick: Any = None
        self.delayed: list[tuple[float, Any]] = []
        self.cancelled: list[str] = []

        def track_state(_hass, entities, action):
            self.tracked = list(entities)
            self.power_callback = action
            return lambda: self.cancelled.append("power")

        def track_interval(_hass, action, interval):
            self.tick = action
            self.interval = interval.total_seconds()
            return lambda: self.cancelled.append("tick")

        def call_later(_hass, delay, action):
            self.delayed.append((delay, action))
            return lambda: self.cancelled.append("delayed")

        monkeypatch.setattr(event, "async_track_state_change_event", track_state)
        monkeypatch.setattr(event, "async_track_time_interval", track_interval)
        monkeypatch.setattr(event, "async_call_later", call_later)


def test_power_changes_wake_the_display_at_most_every_ten_seconds(monkeypatch) -> None:
    helpers = _Helpers(monkeypatch)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources",
                        AsyncMock(return_value=SOURCES))
    clock = [100.0]
    monkeypatch.setattr(dashboard_energy_updates, "monotonic", lambda: clock[0])
    woken: list[float] = []

    stop = asyncio.run(dashboard_energy_updates.async_track_energy_page_updates(
        FakeHass(), _entry(ENERGY_ON), lambda: woken.append(clock[0]),
    ))

    assert helpers.tracked == ["sensor.grid_power"] and helpers.interval == 300.0
    helpers.power_callback(None)
    assert woken == [100.0]
    clock[0] = 103.0
    helpers.power_callback(None)
    helpers.power_callback(None)
    # One delayed wake-up for the whole burst, at the end of the ten seconds.
    assert woken == [100.0] and [delay for delay, _ in helpers.delayed] == [7.0]
    clock[0] = 110.0
    helpers.delayed[0][1](None)
    assert woken == [100.0, 110.0]
    clock[0] = 125.0
    helpers.power_callback(None)
    assert woken == [100.0, 110.0, 125.0]
    stop()
    assert sorted(helpers.cancelled) == ["power", "tick"]


def test_statistics_tick_wakes_the_display_and_follows_a_changed_energy_setup(monkeypatch) -> None:
    helpers = _Helpers(monkeypatch)
    sources = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources", sources)
    woken: list[int] = []

    async def scenario() -> None:
        await dashboard_energy_updates.async_track_energy_page_updates(
            FakeHass(), _entry(ENERGY_ON), lambda: woken.append(1),
        )
        sources.return_value = EnergySources(
            grid_from=SOURCES.grid_from, grid_power=("sensor.new_power",),
        )
        await helpers.tick(None)

    asyncio.run(scenario())

    assert woken == [1]
    assert helpers.tracked == ["sensor.new_power"] and helpers.cancelled == ["power"]


def test_a_tick_that_finishes_after_the_stop_does_nothing(monkeypatch) -> None:
    """An unload can land while a tick waits for the energy setup."""

    helpers = _Helpers(monkeypatch)
    sources = AsyncMock(return_value=SOURCES)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources", sources)
    woken: list[int] = []

    async def scenario() -> None:
        stop = await dashboard_energy_updates.async_track_energy_page_updates(
            FakeHass(), _entry(ENERGY_ON), lambda: woken.append(1),
        )

        async def changed_setup(*_args: Any) -> EnergySources:
            stop()
            return EnergySources(grid_from=SOURCES.grid_from, grid_power=("sensor.new_power",))

        sources.side_effect = changed_setup
        await helpers.tick(None)

    asyncio.run(scenario())

    assert woken == [] and "sensor.new_power" not in helpers.tracked


def test_nothing_is_tracked_without_an_energy_page(monkeypatch) -> None:
    helpers = _Helpers(monkeypatch)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources",
                        AsyncMock(return_value=EnergySources()))

    stop = asyncio.run(dashboard_energy_updates.async_track_energy_page_updates(
        FakeHass(), _entry(), lambda: None,
    ))

    assert stop is None and helpers.tick is None and helpers.power_callback is None


def test_the_tick_runs_before_home_assistant_has_any_energy_source(monkeypatch) -> None:
    # The page is switched on first and the Energy setup follows later, or the
    # energy integration loads after this one: no reload must be needed.
    helpers = _Helpers(monkeypatch)
    sources = AsyncMock(return_value=EnergySources())
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources", sources)
    woken: list[int] = []

    async def scenario() -> Any:
        stop = await dashboard_energy_updates.async_track_energy_page_updates(
            FakeHass(), _entry(ENERGY_ON), lambda: woken.append(1),
        )
        assert stop is not None and helpers.tick is not None
        await helpers.tick(None)
        assert woken == [], "no page yet: the display is left alone"
        sources.return_value = SOURCES
        await helpers.tick(None)
        return stop

    asyncio.run(scenario())

    assert woken == [1]
    assert helpers.tracked == ["sensor.grid_power"]


def test_the_tick_reads_fresh_statistics(monkeypatch) -> None:
    helpers = _Helpers(monkeypatch)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources",
                        AsyncMock(return_value=SOURCES))
    order: list[str] = []
    monkeypatch.setattr(dashboard_energy_updates, "forget_energy_day",
                        lambda entry_id: order.append(f"forget {entry_id}"))

    async def scenario() -> None:
        await dashboard_energy_updates.async_track_energy_page_updates(
            FakeHass(), _entry(ENERGY_ON), lambda: order.append("wake"),
        )
        await helpers.tick(None)

    asyncio.run(scenario())

    # The kept day is as old as the tick interval, give or take the delivery
    # delay: without dropping it every second wake-up showed the old figures.
    assert order == ["forget entry-1", "wake"]


def test_a_power_change_the_display_cannot_show_does_not_wake_it(monkeypatch) -> None:
    helpers = _Helpers(monkeypatch)
    monkeypatch.setattr(dashboard_energy_updates, "async_configured_energy_sources",
                        AsyncMock(return_value=SOURCES))
    woken: list[int] = []
    asyncio.run(dashboard_energy_updates.async_track_energy_page_updates(
        FakeHass(), _entry(ENERGY_ON), lambda: woken.append(1),
    ))

    def change(old: str, new: str) -> None:
        def state(value: str) -> Any:
            return types.SimpleNamespace(state=value, attributes={"unit_of_measurement": "W"})
        helpers.power_callback(types.SimpleNamespace(data={"old_state": state(old), "new_state": state(new)}))

    change("850.2", "850.4")
    change("1234", "1232")
    change("unavailable", "unknown")
    assert woken == []
    change("850.4", "851")
    assert woken == [1]

