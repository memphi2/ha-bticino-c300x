"""Wakes the display when its energy page has something new to show.

Power sensors change every few seconds. The display fetches all its pages on
each wake-up, so a change is passed on at most once per
``ENERGY_POWER_MIN_INTERVAL_SECONDS``; the last change of a burst is never
lost. The meter figures come from statistics, which Home Assistant writes
every five minutes, so one wake-up per such interval keeps them current. The
same tick notices a changed Energy setup. Without an energy page nothing here
runs at all.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .dashboard_energy_data import (
    ENERGY_STATISTICS_MAX_AGE_SECONDS,
    async_configured_energy_sources,
    forget_energy_day,
)
from .entry_types import BticinoC300XConfigEntry

ENERGY_POWER_MIN_INTERVAL_SECONDS = 10.0


class EnergyPageUpdates:
    """Tracks the power sensors and the statistics interval of one entry."""

    def __init__(
        self, hass: HomeAssistant, entry: BticinoC300XConfigEntry, notify: Callable[[], None],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._notify = notify
        self._power_entities: frozenset[str] = frozenset()
        self._unsub_power: Callable[[], None] | None = None
        self._unsub_tick: Callable[[], None] | None = None
        self._unsub_delayed: Callable[[], None] | None = None
        self._last_notify = 0.0

    async def async_start(self) -> bool:
        """Start tracking; returns False when there is no energy page."""

        from homeassistant.helpers.event import async_track_time_interval

        sources = await async_configured_energy_sources(self._hass, self._entry)
        if not sources.any:
            return False
        self._track_power(frozenset(sources.power_entities))
        self._unsub_tick = async_track_time_interval(
            self._hass, self._async_tick,
            timedelta(seconds=ENERGY_STATISTICS_MAX_AGE_SECONDS),
        )
        return True

    @callback
    def stop(self) -> None:
        """Stop tracking and drop the kept statistics."""

        for name in ("_unsub_power", "_unsub_tick", "_unsub_delayed"):
            unsubscribe = getattr(self, name)
            setattr(self, name, None)
            if unsubscribe is not None:
                unsubscribe()
        forget_energy_day(self._entry.entry_id)

    def _track_power(self, entities: frozenset[str]) -> None:
        from homeassistant.helpers.event import async_track_state_change_event

        if self._unsub_power is not None:
            self._unsub_power()
            self._unsub_power = None
        self._power_entities = entities
        if entities:
            self._unsub_power = async_track_state_change_event(
                self._hass, sorted(entities), self._handle_power_change,
            )

    async def _async_tick(self, _now: Any = None) -> None:
        sources = await async_configured_energy_sources(self._hass, self._entry)
        entities = frozenset(sources.power_entities)
        if entities != self._power_entities:
            self._track_power(entities)
        self._send()

    @callback
    def _handle_power_change(self, _event: Any) -> None:
        from homeassistant.helpers.event import async_call_later

        if self._unsub_delayed is not None:
            return
        wait = ENERGY_POWER_MIN_INTERVAL_SECONDS - (monotonic() - self._last_notify)
        if wait <= 0:
            self._send()
            return
        self._unsub_delayed = async_call_later(self._hass, wait, self._handle_delayed)

    @callback
    def _handle_delayed(self, _now: Any = None) -> None:
        self._unsub_delayed = None
        self._send()

    def _send(self) -> None:
        self._last_notify = monotonic()
        self._notify()


async def async_track_energy_page_updates(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, notify: Callable[[], None],
) -> Callable[[], None] | None:
    """Start the energy page updates of an entry; returns how to stop them."""

    updates = EnergyPageUpdates(hass, entry, notify)
    return updates.stop if await updates.async_start() else None
