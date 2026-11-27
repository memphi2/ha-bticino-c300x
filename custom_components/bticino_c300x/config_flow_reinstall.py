"""Reinstall the agent for an entry whose keys are lost.

The keys of an installed agent exist only in the entry that installed it. When
they are gone, the SSH installer writes the bundled agent again with newly
generated keys; the entry then stores them. What the station holds besides the
keys stays: the installer keeps the device-owned configuration sections and
changes no display page. Before it writes anything, the installer reads
which station the entry's address leads to: another station is left alone.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult

from .config_flow_entry_update import async_ensure_entry_reload
from .config_flow_features import current_connection_options
from .config_flow_input import _bootstrap_install_schema
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_MAINTENANCE_TOKEN,
    DEFAULT_AGENT_PORT,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_MODE_AUTO,
)
from .device_installer import (
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    async_ensure_installer_dependencies,
    async_install_device_agent,
)
from .entry_config import entry_config_value
from .factory_login import install_login, login_model
from .station_identity import WRONG_STATION

_LOGGER = logging.getLogger(__name__)
_KEYS = (CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN)


def entry_reinstall_request(
    entry: Any, user_input: dict[str, Any] | None,
) -> C300XDeviceInstallRequest:
    """The install request for the station of an existing entry."""

    model = login_model(getattr(getattr(entry, "runtime_data", None), "agent_info", None))
    return C300XDeviceInstallRequest(
        host=str(entry_config_value(entry, CONF_AGENT_HOST, "")).strip(),
        **install_login(user_input, model),
        # The entry exists: its station was accepted at setup.
        c100x_confirmed=True,
        station_id=str(getattr(entry, "unique_id", None) or ""),
        agent_port=int(entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        apply_gui_patch=False,
        device_activation_mode=str(entry_config_value(
            entry, CONF_DEVICE_ACTIVATION_MODE, DEVICE_ACTIVATION_MODE_AUTO,
        )),
        device_activation_stair_light_p=str(entry_config_value(
            entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_P,
        )),
        device_activation_stair_light_n=str(entry_config_value(
            entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, DEFAULT_STAIR_LIGHT_N,
        )),
        device_activations=tuple(entry_config_value(entry, CONF_DEVICE_ACTIVATIONS, []) or []),
    )


def _async_keep_keys(hass: Any, entry: Any, keys: dict[str, str]) -> None:
    """Save keys on the station in the entry and reload it, without ending the flow."""

    options = {key: value for key, value in entry.options.items() if key not in _KEYS}
    had_listeners = bool(entry.update_listeners)
    changed = hass.config_entries.async_update_entry(entry, data={**entry.data, **keys}, options=options)
    async_ensure_entry_reload(hass, entry, changed=bool(changed), had_listeners=had_listeners, force=True)


class ReinstallSteps:
    """Replace the lost keys of an entry through the SSH installer."""

    _reinstall_login_tried: bool = False

    async def async_step_reauth_reinstall(
        self: Any, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        # The factory login is tried first; the form asks only once it was refused.
        if user_input is not None or not self._reinstall_login_tried:
            self._reinstall_login_tried = True
            connection = current_connection_options(entry)
            keys = {key: secrets.token_urlsafe(32) for key in _KEYS}
            try:
                await async_ensure_installer_dependencies(self.hass)
                installed = await async_install_device_agent(
                    entry_reinstall_request(entry, user_input),
                    api_token=keys[CONF_AGENT_TOKEN],
                    maintenance_token=keys[CONF_MAINTENANCE_TOKEN],
                )
            except C300XDeviceInstallError as err:
                if err.reason == WRONG_STATION:
                    # The address leads to another station now; nothing was written on it.
                    return cast(ConfigFlowResult, self.async_abort(reason="reauth_wrong_device"))
                _LOGGER.warning("Reinstalling the device agent failed: %s", err.reason)
                errors["base"] = err.reason
                if err.keys_written and current_connection_options(entry) == connection:
                    # The station holds these keys now: the entry keeps them
                    # while the form shows what failed after they were written.
                    _async_keep_keys(self.hass, entry, keys)
            else:
                if current_connection_options(entry) != connection:
                    # The entry was pointed elsewhere while the install ran.
                    return cast(ConfigFlowResult, self.async_abort(reason="reauth_wrong_device"))
                # The station holds these keys now; the reloaded entry signs in with them.
                data = dict(keys)
                if getattr(installed, "display_pending", False):
                    data[CONF_DISPLAY_FOLLOWUP_PENDING] = entry.data.get(
                        CONF_DISPLAY_FOLLOWUP_PENDING, False,
                    )
                options = {key: value for key, value in entry.options.items() if key not in _KEYS}
                had_listeners = bool(entry.update_listeners)
                result = self.async_update_and_abort(entry, data_updates=data, options=options)
                async_ensure_entry_reload(
                    self.hass, entry, changed=True, had_listeners=had_listeners, force=True,
                )
                return cast(ConfigFlowResult, result)
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="reauth_reinstall", data_schema=_bootstrap_install_schema(), errors=errors,
            description_placeholders={"name": str(getattr(entry, "title", "") or "")},
        ))
