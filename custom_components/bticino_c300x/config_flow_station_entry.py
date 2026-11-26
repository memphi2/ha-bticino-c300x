"""A setup whose agent install serves a station that already has an entry.

The keys of an installed agent exist only in the entry that installed it. A
setup that installs the agent again writes new keys, and which station it
reached is known only after the install: the duplicate check before it can
only compare addresses. When the station belongs to an existing entry, for
example one saved under an older address or a host name, that entry gets the
new keys and the address the setup used and is reloaded. No second entry is
created and no keys are lost.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback

from . import config_flow_agent
from .api_errors import C300XAgentApiError
from .config_flow_entry_update import async_ensure_entry_reload
from .config_flow_identity import (
    entry_uses_manual_setup_unique_id,
    stable_unique_id_from_setup_data,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_MAINTENANCE_TOKEN,
    DEFAULT_AGENT_PORT,
)
from .discovery import discovery_matches_entry
from .discovery_move import async_identity_proven, async_ipv4_addresses
from .entry_config import entry_config_value

KEYS = (CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN)
ENTRY_UPDATED = "reinstall_entry_updated"


async def async_station_entry(
    hass: Any,
    entries: Iterable[Any],
    unique_id: str | None,
    connection: dict[str, Any],
) -> Any | None:
    """Return the existing entry of the station that holds the keys of ``connection``.

    An entry under the station's identity is it. An entry under an address
    based identity (an older release) is it when its own address, resolved
    to IPv4, proves that identity with the keys just written. The proof
    request carries no key: an address that now belongs to another machine
    never gets one.
    """

    if unique_id is None:
        return None
    entries = list(entries)
    for entry in entries:
        if discovery_matches_entry(unique_id, getattr(entry, "unique_id", None)):
            return entry
    # The new agent listens on the port of this setup.
    port = int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    for entry in entries:
        host = str(entry_config_value(entry, CONF_AGENT_HOST, "") or "").strip()
        if not host or not entry_uses_manual_setup_unique_id(entry):
            continue
        for address in await async_ipv4_addresses(host):
            if await async_identity_proven(hass, address, port, unique_id, connection[CONF_AGENT_TOKEN]):
                return entry
    return None


def hand_keys_to_entry(
    hass: Any,
    entry: Any,
    connection: dict[str, Any],
    *,
    unique_id: str | None,
    display_pending: bool,
) -> None:
    """Save the keys on the station and the address that reached it in the entry."""

    data = {key: connection[key] for key in KEYS}
    data[CONF_AGENT_HOST] = connection[CONF_AGENT_HOST]
    data[CONF_AGENT_PORT] = int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    if display_pending:
        # As a reauth reinstall: the core Repair runs the display step it owes.
        data[CONF_DISPLAY_FOLLOWUP_PENDING] = entry.data.get(CONF_DISPLAY_FOLLOWUP_PENDING, False)
    updates: dict[str, Any] = {
        "data": {**entry.data, **data},
        # An option of the same name would hide the new value.
        "options": {key: value for key, value in entry.options.items() if key not in data},
    }
    if unique_id is not None and entry_uses_manual_setup_unique_id(entry):
        updates["unique_id"] = unique_id
    had_listeners = bool(entry.update_listeners)
    changed = hass.config_entries.async_update_entry(entry, **updates)
    async_ensure_entry_reload(hass, entry, changed=bool(changed), had_listeners=had_listeners, force=True)


class StationEntrySteps:
    """Setup steps that keep one entry per station across an agent install."""

    # The station, port and keys of an install that failed after it wrote them.
    _setup_written_keys: tuple[str, int, str, str] | None = None
    # The existing entry that got those keys (and the setup's address) then.
    # It is the station this setup installs, not a duplicate: the retry runs.
    _setup_keys_entry: str | None = None

    def _setup_install_endpoint(self: Any) -> tuple[str, int]:
        connection = self._setup_connection
        return str(connection[CONF_AGENT_HOST]), int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))

    def _setup_install_keys(self: Any) -> tuple[str, str]:
        """The keys an install writes: those a failed install left on this station, else new ones.

        A retry then replaces no keys, and nothing the station holds is lost.
        """

        kept = self._setup_written_keys
        if kept is not None and kept[:2] == self._setup_install_endpoint():
            return kept[2], kept[3]
        return secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    async def _async_keep_written_keys(self: Any, err: Exception, api_token: str, maintenance_token: str) -> None:
        """Keep the keys a failed install left on the station; the failure is still shown.

        The setup uses them again on its retry. An existing entry of the
        station gets them at once.
        """

        if not getattr(err, "keys_written", False):
            return
        self._setup_written_keys = (*self._setup_install_endpoint(), api_token, maintenance_token)
        connection = {**self._setup_connection, CONF_AGENT_TOKEN: api_token, CONF_MAINTENANCE_TOKEN: maintenance_token}
        try:
            setup = await config_flow_agent.async_agent_setup_data(self.hass, connection, api_token=api_token)
        except C300XAgentApiError:
            return
        unique_id = stable_unique_id_from_setup_data(setup)
        if unique_id is None:
            return
        entry = await async_station_entry(self.hass, self._async_current_entries(), unique_id, connection)
        if entry is not None:
            hand_keys_to_entry(self.hass, entry, connection, unique_id=unique_id, display_pending=False)
            self._setup_keys_entry = entry.entry_id

    async def _async_hand_keys_to_station_entry(
        self: Any, install_result: object,
    ) -> ConfigFlowResult | None:
        """End the setup at the existing entry of this station, which gets the keys."""

        if self._setup_unique_id is None:
            return None
        entry = await async_station_entry(
            self.hass, self._async_current_entries(), self._setup_unique_id, self._setup_connection,
        )
        if entry is None:
            return None
        hand_keys_to_entry(
            self.hass, entry, self._setup_connection, unique_id=self._setup_unique_id,
            display_pending=bool(getattr(install_result, "display_pending", False)),
        )
        return cast(ConfigFlowResult, self.async_abort(
            reason=ENTRY_UPDATED, description_placeholders={"name": str(getattr(entry, "title", "") or "")},
        ))

    @callback
    def _async_abort_duplicate_setup_flows(self: Any, unique_id: str) -> None:
        """Abort parallel discovery flows that target the same just-installed agent."""

        flow_manager = getattr(getattr(self.hass, "config_entries", None), "flow", None)
        if flow_manager is None:
            return
        for progress in self._async_in_progress(
            include_uninitialized=True,
            match_context={"unique_id": unique_id},
        ):
            flow_manager.async_abort(progress["flow_id"])
