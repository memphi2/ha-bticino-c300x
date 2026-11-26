"""Home Assistant's config entry registry as the flows see it, without a running HA.

The flows' own duplicate and unique id checks (async_set_unique_id,
_abort_if_unique_id_configured, _async_current_entries) run unchanged
against it; only the registry and the flow manager are stand-ins.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntryState
from homeassistant.helpers.typing import UNDEFINED

from custom_components.bticino_c300x.const import DOMAIN

_UNSET: Any = object()


def entry(entry_id: str, unique_id: str, data: dict[str, Any], *, title: str = "Door",
          options: dict[str, Any] | None = None, runtime_data: Any = None, source: str = "user",
          disabled_by: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id=entry_id, title=title, unique_id=unique_id, data=dict(data), options=dict(options or {}),
        update_listeners=[], source=source, state=ConfigEntryState.LOADED, domain=DOMAIN,
        runtime_data=runtime_data, disabled_by=disabled_by,
    )


class FlowManager:
    """No other flow is in progress."""

    def __init__(self) -> None:
        self.aborted: list[str] = []

    def async_progress_by_handler(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def async_abort(self, flow_id: str) -> None:
        self.aborted.append(flow_id)


class ConfigEntries:
    """The entries of the integration; updates and reloads are recorded."""

    def __init__(self, entries: list[Any] | None = None) -> None:
        self.entries = list(entries or [])
        self.flow = FlowManager()
        self.reloaded: list[str] = []
        self.removed: list[str] = []

    def async_entries(self, domain: str | None = None, include_ignore: bool = True,
                      include_disabled: bool = True) -> list[Any]:
        # As HA: a user flow does not see ignored entries.
        return [
            item for item in self.entries
            if (include_ignore or getattr(item, "source", None) != SOURCE_IGNORE)
            and (include_disabled or not getattr(item, "disabled_by", None))
        ]

    async def async_remove(self, entry_id: str) -> dict[str, Any]:
        self.entries = [item for item in self.entries if item.entry_id != entry_id]
        self.removed.append(entry_id)
        return {"require_restart": False}

    def async_entry_for_domain_unique_id(self, domain: str, unique_id: str) -> Any:
        return next((item for item in self.entries if item.unique_id == unique_id), None)

    def async_get_entry(self, entry_id: str) -> Any:
        return next((item for item in self.entries if item.entry_id == entry_id), None)

    async_get_known_entry = async_get_entry

    def async_update_entry(self, entry: Any, *, data: Any = _UNSET, options: Any = _UNSET,
                           unique_id: Any = _UNSET, title: Any = _UNSET, **_kwargs: Any) -> bool:
        # HA passes UNDEFINED for what a flow's update leaves alone.
        unset = (_UNSET, UNDEFINED)
        before = (dict(entry.data), dict(entry.options), entry.unique_id, entry.title)
        if data not in unset:
            entry.data = dict(data)
        if options not in unset:
            entry.options = dict(options)
        if unique_id not in unset:
            # HA reports a unique id another entry holds already; later versions refuse it.
            assert all(item is entry or item.unique_id != unique_id for item in self.entries), unique_id
            entry.unique_id = unique_id
        if title not in unset:
            entry.title = title
        return before != (dict(entry.data), dict(entry.options), entry.unique_id, entry.title)

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


def hass(entries: list[Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(config_entries=ConfigEntries(entries), data={})


def attach(flow: Any, hass_: Any, *, source: str = "user", entry_id: str | None = None) -> Any:
    """Give a flow what the flow manager gives it before its first step."""

    flow.hass = hass_
    flow.handler = DOMAIN
    flow.flow_id = f"flow-{id(flow)}"
    flow.context = {"source": source, **({"entry_id": entry_id} if entry_id else {})}
    return flow
