"""Wakes the display when its energy page has something new to show.

Power sensors change every few seconds. The display fetches all its pages on
each wake-up, so a change is passed on at most once per
``ENERGY_POWER_MIN_INTERVAL_SECONDS``; the last change of a burst is never
lost. The meter figures come from statistics, which Home Assistant writes
every five minutes, so one wake-up per such interval keeps them current. The
same tick notices a changed Energy setup, also one that only gets its first
source after the page was switched on. A power change that leaves the shown
text as it is wakes nothing. With the energy page switched off nothing here
runs at all.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .dashboard_config import configured_energy_page
from .dashboard_energy import (
    ENERGY_DAY_VIEWS,
    ENERGY_LIVE_VIEWS,
    ENERGY_VIEW_CONSUMERS,
    ENERGY_VIEW_NOW,
    ENERGY_VIEW_POWER,
    EnergySources,
    format_power,
    power_watts,
)
from .dashboard_energy_consumers import consumer_power_watts
from .dashboard_energy_data import (
    ENERGY_STATISTICS_MAX_AGE_SECONDS,
    async_configured_energy_sources,
    expire_energy_day,
    forget_energy_day,
)
from .dashboard_energy_power import forget_power_history
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
        self._sources = EnergySources()
        self._unsub_power: Callable[[], None] | None = None
        self._unsub_tick: Callable[[], None] | None = None
        self._unsub_delayed: Callable[[], None] | None = None
        self._last_notify = 0.0
        self._shown = False
        self._stopped = False

    async def async_start(self) -> bool:
        """Start tracking; returns False when the energy page is switched off."""

        from homeassistant.helpers.event import async_track_time_interval

        if not self._active_views():
            return False
        sources = await async_configured_energy_sources(self._hass, self._entry)
        views = self._active_views()
        if self._stopped or not views:
            return False
        self._sources = sources
        self._shown = sources.any
        self._track_power(frozenset(sources.live_power_entities(views)))
        self._unsub_tick = async_track_time_interval(
            self._hass, self._async_tick,
            timedelta(seconds=ENERGY_STATISTICS_MAX_AGE_SECONDS),
        )
        return True

    @callback
    def stop(self) -> None:
        """Stop tracking and drop the kept statistics."""

        if self._stopped:
            return
        self._stopped = True
        for name in ("_unsub_power", "_unsub_tick", "_unsub_delayed"):
            unsubscribe = getattr(self, name)
            setattr(self, name, None)
            if unsubscribe is not None:
                unsubscribe()
        forget_energy_day(self._entry.entry_id)
        forget_power_history(self._entry.entry_id)

    def _active_views(self) -> list[str]:
        if self._stopped:
            return []
        settings = configured_energy_page(self._entry)
        views: list[str] = settings["views"] if settings["enabled"] else []
        if not views:
            self.stop()
        else:
            if ENERGY_VIEW_POWER not in views:
                forget_power_history(self._entry.entry_id)
            if not any(view in ENERGY_DAY_VIEWS for view in views):
                forget_energy_day(self._entry.entry_id)
            entities = frozenset(self._sources.live_power_entities(views))
            if entities != self._power_entities:
                self._track_power(entities)
            if not any(view in ENERGY_LIVE_VIEWS for view in views) and self._unsub_delayed is not None:
                self._unsub_delayed()
                self._unsub_delayed = None
        return views

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
        if self._stopped or not self._active_views():
            return
        sources = await async_configured_energy_sources(self._hass, self._entry)
        views = self._active_views()
        if self._stopped or not views:
            # Stopped while waiting: nothing is tracked or woken any more.
            return
        self._sources = sources
        entities = frozenset(sources.live_power_entities(views))
        if entities != self._power_entities:
            self._track_power(entities)
        was_shown, self._shown = self._shown, sources.any
        if not (was_shown or self._shown):
            return
        # The kept day is about as old as this interval: read it anew.
        if any(view in ENERGY_DAY_VIEWS for view in views):
            expire_energy_day(self._entry.entry_id)
        self._send()

    @callback
    def _handle_power_change(self, event: Any) -> None:
        from homeassistant.helpers.event import async_call_later

        if self._stopped:
            return
        views = self._active_views()
        if not any(view in ENERGY_LIVE_VIEWS for view in views):
            return
        event_data = getattr(event, "data", {})
        entity_id = event_data.get("entity_id") if isinstance(event_data, dict) else None
        if entity_id is not None and entity_id not in self._power_entities:
            return
        consumer = ENERGY_VIEW_CONSUMERS in views and any(
            source.entity_id == entity_id for source in self._sources.consumers
        )
        unchanged = _same_power_text(event, exact=consumer)
        if consumer and ENERGY_VIEW_NOW in views and entity_id in self._sources.power_entities:
            unchanged = unchanged and _same_power_text(event)
        if self._unsub_delayed is not None or unchanged:
            return
        wait = ENERGY_POWER_MIN_INTERVAL_SECONDS - (monotonic() - self._last_notify)
        if wait <= 0:
            self._send()
            return
        self._unsub_delayed = async_call_later(self._hass, wait, self._handle_delayed)

    @callback
    def _handle_delayed(self, _now: Any = None) -> None:
        self._unsub_delayed = None
        if self._stopped or not any(view in ENERGY_LIVE_VIEWS for view in self._active_views()):
            return
        self._send()

    def _send(self) -> None:
        if self._stopped:
            return
        self._last_notify = monotonic()
        self._notify()


def _same_power_text(event: Any, *, exact: bool = False) -> bool:
    """Ignore unchanged live values; Consumers ranking needs exact watts."""

    data = getattr(event, "data", None)
    if not isinstance(data, dict) or "new_state" not in data:
        return False
    converter = consumer_power_watts if exact else power_watts
    old = converter(data.get("old_state"))
    new = converter(data["new_state"])
    if old is None or new is None:
        return old is None and new is None
    if exact:
        old_name = (getattr(data.get("old_state"), "attributes", {}) or {}).get("friendly_name")
        new_name = (getattr(data["new_state"], "attributes", {}) or {}).get("friendly_name")
        if old_name != new_name:
            return False
        return old == new
    return format_power(old, "en") == format_power(new, "en")


async def async_track_energy_page_updates(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, notify: Callable[[], None],
) -> Callable[[], None] | None:
    """Start the energy page updates of an entry; returns how to stop them."""

    updates = EnergyPageUpdates(hass, entry, notify)
    return updates.stop if await updates.async_start() else None
