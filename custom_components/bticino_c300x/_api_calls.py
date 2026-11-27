"""Normalize the agent's outdoor unit and call answers (agent API 2)."""

from __future__ import annotations

import re
from typing import Any

from .agent_contracts import (
    Call,
    CallsPayload,
    DoorContact,
    OutdoorUnit,
    OutdoorUnitsPayload,
)
from .api_errors import C300XAgentApiResponseError

# The agent's own limits: a where of digits and '#', a call id of
# <8 hex>-<sequence>.
_UNIT_ID = re.compile(r"^[0-9][0-9_]{0,22}$")
_WHERE = re.compile(r"^[0-9][0-9#]{0,22}$")
_CALL_ID = re.compile(r"^[0-9a-f]{8}-[0-9]{1,10}$")
_CALL_STATES = frozenset({"ringing", "answered", "viewing", "ended"})
_DOOR_STATES = frozenset({"open", "closed"})


def valid_unit_id(value: Any) -> str | None:
    """Return the unit id when it has the agent's form."""

    return value if isinstance(value, str) and _UNIT_ID.fullmatch(value) else None


def valid_call_id(value: Any) -> str | None:
    """Return the call id when it has the agent's form."""

    return value if isinstance(value, str) and _CALL_ID.fullmatch(value) else None


def _text(value: Any, limit: int = 64) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _door_contact(value: Any) -> DoorContact | None:
    """``door``: null without a contact, else ``{"state": open|closed|null, "age_ms"}``."""

    if not isinstance(value, dict):
        return None
    state = value.get("state")
    age = value.get("age_ms")
    return DoorContact(
        state=state if state in _DOOR_STATES else None,
        age_ms=age if isinstance(age, int) and not isinstance(age, bool) and age >= 0 else None,
    )


def normalize_outdoor_units(data: Any) -> OutdoorUnitsPayload:
    """Return the units the agent reports; malformed entries are skipped."""

    if not isinstance(data, dict) or not isinstance(data.get("units"), list):
        raise C300XAgentApiResponseError("device agent returned malformed outdoor units")
    units: list[OutdoorUnit] = []
    for item in data["units"]:
        if not isinstance(item, dict):
            continue
        unit_id = valid_unit_id(item.get("id"))
        where = item.get("where")
        if unit_id is None or not isinstance(where, str) or not _WHERE.fullmatch(where):
            continue
        if any(unit.id == unit_id for unit in units):
            continue
        action_where = _text(item.get("action_where"), 24) or where.split("#", 1)[0]
        units.append(OutdoorUnit(
            id=unit_id,
            where=where,
            action_where=action_where,
            lock_where=_text(item.get("lock_where"), 24) or action_where,
            name=_text(item.get("name")),
            source=_text(item.get("source"), 16) or "seen",
            default=item.get("default") is True,
            door=_door_contact(item.get("door")),
        ))
    default_unit = valid_unit_id(data.get("default_unit"))
    if default_unit is None or all(unit.id != default_unit for unit in units):
        default_unit = next((unit.id for unit in units if unit.default), None)
    return OutdoorUnitsPayload(
        raw=data, units=tuple(units), default_unit=default_unit,
        archive=_text(data.get("archive"), 16),
    )


def normalize_call(item: Any) -> Call | None:
    """Return one call of the agent, or None when it is malformed."""

    if not isinstance(item, dict):
        return None
    call_id = valid_call_id(item.get("call_id"))
    state = item.get("state")
    if call_id is None or state not in _CALL_STATES:
        return None
    return Call(
        call_id=call_id,
        kind="view" if item.get("kind") == "view" else "ring",
        state=state,
        unit=valid_unit_id(item.get("unit")),
        attribution=_text(item.get("attribution"), 24) or "pending",
        answered_by=_text(item.get("answered_by"), 16) or None,
        end_reason=_text(item.get("end_reason") or item.get("reason"), 24) or None,
    )


def normalize_calls(data: Any) -> CallsPayload:
    """Return the agent's calls, newest first."""

    if not isinstance(data, dict) or not isinstance(data.get("calls"), list):
        raise C300XAgentApiResponseError("device agent returned malformed calls")
    calls = tuple(call for call in map(normalize_call, data["calls"]) if call is not None)
    current = valid_call_id(data.get("current_call_id"))
    return CallsPayload(
        raw=data,
        boot_id=_text(data.get("boot_id"), 16),
        current_call_id=current if any(call.call_id == current for call in calls) else None,
        calls=calls,
    )
