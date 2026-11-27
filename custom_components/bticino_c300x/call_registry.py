"""The station's outdoor units and calls as Home Assistant knows them.

The agent owns calls (docs/dev/multi-outdoor-units.md). This registry mirrors
its answers and events so entities and services can name a unit's state and
the current call without asking the station.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ._api_calls import valid_call_id, valid_unit_id
from .agent_contracts import Call, CallsPayload, OutdoorUnit, OutdoorUnitsPayload
from .const import DOMAIN

SIGNAL_CALLS_CHANGED = f"{DOMAIN}_calls_changed"
SIGNAL_OUTDOOR_UNITS_CHANGED = f"{DOMAIN}_outdoor_units_changed"

# Calls the registry keeps: the agent keeps at most eight, ended ones 60 s.
_MAX_CALLS = 8
_LIVE = frozenset({"ringing", "answered", "viewing"})


@dataclass(slots=True)
class C300XCallRegistry:
    """Units and calls of one station."""

    units: dict[str, OutdoorUnit] = field(default_factory=dict)
    default_unit: str | None = None
    # Newest last.
    calls: dict[str, Call] = field(default_factory=dict)
    loaded: bool = False
    # Units whose doorbell event entity listens; a ring of another unit waits
    # in waiting_rings until its entity is added.
    ring_listeners: set[str] = field(default_factory=set)
    waiting_rings: dict[str, list[str]] = field(default_factory=dict)
    # Units whose doorbell event fired for the latest press of each call.
    rung: dict[str, set[str]] = field(default_factory=dict)

    # --- units ---------------------------------------------------------------

    def set_units(self, payload: OutdoorUnitsPayload) -> bool:
        """Take the agent's unit list; true when ids, names or default changed."""

        units = {unit.id: unit for unit in payload.units}
        changed = units != self.units or payload.default_unit != self.default_unit
        self.units = units
        self.default_unit = payload.default_unit
        self.loaded = True
        return changed

    def unit(self, unit_id: str | None) -> OutdoorUnit | None:
        return self.units.get(unit_id) if unit_id is not None else None

    def unit_name(self, unit_id: str | None) -> str | None:
        """The station's name of the unit, None when it has none."""

        unit = self.unit(unit_id)
        return unit.name or None if unit is not None else None

    # --- calls ---------------------------------------------------------------

    def set_calls(self, payload: CallsPayload) -> None:
        """Replace the mirror with the agent's list (newest first there)."""

        self.calls = {call.call_id: call for call in reversed(payload.calls)}

    @property
    def current_call(self) -> Call | None:
        """The answered ring, else the newest ringing one, else the live view (the agent's rule).

        A view is current only without a live ring: it can be hung up, not answered.
        """

        live = [call for call in self.calls.values() if call.state in _LIVE]
        for kind, state in (("ring", "answered"), ("ring", "ringing"), ("view", "viewing")):
            matches = [call for call in live if (call.kind, call.state) == (kind, state)]
            if matches:
                return matches[-1]
        return None

    @property
    def current_call_id(self) -> str | None:
        call = self.current_call
        return call.call_id if call is not None else None

    def has_other_live_call(self, call_id: str) -> bool:
        return any(other.state in _LIVE for other in self.calls.values() if other.call_id != call_id)

    def call(self, call_id: str | None) -> Call | None:
        return self.calls.get(call_id) if call_id is not None else None

    def unit_call(self, unit_id: str) -> Call | None:
        """The live call of one unit, answered before ringing before viewing."""

        live = [call for call in self.calls.values() if call.unit == unit_id and call.state in _LIVE]
        for state in ("answered", "ringing", "viewing"):
            matches = [call for call in live if call.state == state]
            if matches:
                return matches[-1]
        return None

    def unit_state(self, unit_id: str) -> tuple[str, str | None]:
        """``idle``, ``ringing``, ``answered`` or ``viewing`` with its call id."""

        call = self.unit_call(unit_id)
        return ("idle", None) if call is None else (call.state, call.call_id)

    def current_unit(self) -> str | None:
        """The unit of the current call, else the default unit."""

        call = self.current_call
        if call is not None and call.unit is not None:
            return call.unit
        return self.default_unit

    def apply_event(self, event_type: str, data: dict[str, Any]) -> Call | None:
        """Mirror one agent event; returns the call it changed."""

        call_id = valid_call_id(data.get("call_id"))
        if call_id is None:
            return None
        unit = valid_unit_id(data.get("unit"))
        known = self.calls.get(call_id)
        if event_type == "doorbell_pressed":
            attribution = str(data.get("attribution") or "pending")
            if known is not None:
                # Pressed again during the same ring session: the same call, in
                # its state (an answered call stays answered); it rings again.
                call = known if unit is None or attribution == "pending" else replace(
                    known, unit=unit, attribution=attribution)
            else:
                call = Call(call_id=call_id, kind="ring", state="ringing", unit=unit,
                            attribution=attribution, answered_by=None, end_reason=None)
        elif event_type == "call_view_started":
            call = known or Call(call_id=call_id, kind="view", state="viewing", unit=unit,
                                 attribution="caller_frame", answered_by=None, end_reason=None)
        elif known is None:
            return None
        elif event_type == "call_caller_identified":
            # A caller frame after the default fallback moves the call to its unit.
            attribution = str(data.get("attribution") or known.attribution)
            if unit is None or (unit, attribution) == (known.unit, known.attribution):
                return None
            call = replace(known, unit=unit, attribution=attribution)
        elif event_type == "call_answered":
            call = replace(known, state="answered",
                           answered_by=str(data.get("answered_by") or "") or None)
        elif event_type == "call_ended":
            call = replace(known, state="ended", end_reason=str(data.get("reason") or "") or None)
        else:
            return None
        self.calls.pop(call_id, None)
        self.calls[call_id] = call
        while len(self.calls) > _MAX_CALLS:
            self.calls.pop(next(iter(self.calls)))
        return call

    def unit_ring(self, event_type: str, call: Call) -> str | None:
        """The unit whose doorbell event this call event fires, once per unit and press.

        Only a unit the agent named rings: never while it still waits for the
        caller frame, so the default unit does not ring for another unit's
        visitor. A unit without a listening event entity keeps the ring
        until take_waiting_rings.
        """

        if event_type == "doorbell_pressed":
            # Every press of a ring session rings again, as in 3.0.0.
            self.rung.pop(call.call_id, None)
        elif event_type != "call_caller_identified":
            return None
        if call.kind != "ring" or call.unit is None or call.attribution == "pending":
            return None
        rung = self.rung.setdefault(call.call_id, set())
        if call.unit in rung:
            return None
        rung.add(call.unit)
        for call_id in [call_id for call_id in self.rung if call_id not in self.calls]:
            del self.rung[call_id]
        if call.unit not in self.ring_listeners:
            waiting = [call_id for call_id in self.waiting_rings.get(call.unit, []) if call_id != call.call_id]
            self.waiting_rings[call.unit] = [*waiting[-(_MAX_CALLS - 1):], call.call_id]
        return call.unit

    def take_waiting_rings(self, unit_id: str) -> list[Call]:
        """The live calls that rang this unit before its event entity listened."""

        waiting = self.waiting_rings.pop(unit_id, [])
        calls = [self.calls.get(call_id) for call_id in waiting]
        return [call for call in calls if call is not None and call.unit == unit_id and call.state in _LIVE]

    def clear_calls(self) -> None:
        """The agent restarted: its calls are gone."""

        self.calls.clear()
        self.rung.clear()
        self.waiting_rings.clear()


def units_from_stored(raw: Any) -> OutdoorUnitsPayload | None:
    """Rebuild the last known unit list kept in the config entry."""

    from ._api_calls import normalize_outdoor_units
    from .api_errors import C300XAgentApiResponseError

    try:
        return normalize_outdoor_units(raw)
    except C300XAgentApiResponseError:
        return None


def units_to_stored(payload: OutdoorUnitsPayload) -> dict[str, Any]:
    """What the config entry keeps of the unit list, enough to set up offline."""

    return {
        "default_unit": payload.default_unit,
        "units": [
            {
                "id": unit.id, "where": unit.where, "action_where": unit.action_where,
                "lock_where": unit.lock_where, "name": unit.name, "source": unit.source,
                "default": unit.default,
                # The contact, not its state: that is unknown until the agent reports it.
                "door": {"state": None, "age_ms": None} if unit.door is not None else None,
            }
            for unit in payload.units
        ],
    }
