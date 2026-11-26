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
        """The answered call, else the newest ringing one (the agent's rule)."""

        live = [call for call in self.calls.values() if call.kind == "ring" and call.state in _LIVE]
        answered = [call for call in live if call.state == "answered"]
        if answered:
            return answered[-1]
        ringing = [call for call in live if call.state == "ringing"]
        return ringing[-1] if ringing else None

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
            if known is not None:
                return None
            call = Call(call_id=call_id, kind="ring", state="ringing", unit=unit,
                        attribution=str(data.get("attribution") or "pending"),
                        answered_by=None, end_reason=None)
        elif event_type == "call_view_started":
            call = known or Call(call_id=call_id, kind="view", state="viewing", unit=unit,
                                 attribution="caller_frame", answered_by=None, end_reason=None)
        elif known is None:
            return None
        elif event_type == "call_caller_identified":
            if known.unit is not None:
                return None
            call = replace(known, unit=unit,
                           attribution=str(data.get("attribution") or known.attribution))
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

    def clear_calls(self) -> None:
        """The agent restarted: its calls are gone."""

        self.calls.clear()


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
            }
            for unit in payload.units
        ],
    }
