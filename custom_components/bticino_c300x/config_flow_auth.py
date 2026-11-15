"""Read-only credential validation and entry-bound authentication flows."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import C300XAgentApi, build_agent_base_url
from .api_errors import C300XAgentApiAuthError, C300XAgentApiError
from .config_flow_features import current_connection_options
from .config_flow_identity import (
    entry_uses_manual_setup_unique_id,
    stable_unique_id_from_setup_data,
)
from .config_flow_input import _agent_auth_input, _agent_auth_schema, _key_or_saved
from .config_schemas import reconfigure_connection_schema
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_CALLBACK_BASE_URL,
    CONF_MAINTENANCE_TOKEN,
    DEFAULT_AGENT_PORT,
)

_KEYS = (CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN)


async def async_validate_connection(
    hass: Any, connection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Require authenticated reads before saving credentials; never mutate an agent."""

    api = C300XAgentApi(
        async_get_clientsession(hass),
        build_agent_base_url(connection[CONF_AGENT_HOST], connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        connection.get(CONF_AGENT_TOKEN, ""),
        connection.get(CONF_MAINTENANCE_TOKEN, ""),
    )
    try:
        setup = await api.async_validate_setup()
        await api.async_list_event_subscriptions()
        if connection.get(CONF_MAINTENANCE_TOKEN):
            await api.async_validate_maintenance_auth()
    except C300XAgentApiAuthError as err:
        return {}, {
            "base": "invalid_maintenance_auth" if err.maintenance else "invalid_auth"
        }
    except C300XAgentApiError:
        return {}, {"base": "cannot_connect"}
    return dict(setup), {}


class AuthFlowSteps:
    """Share setup validation and reauth without expanding the main wizard."""

    _setup_unique_id: str | None

    def _show_agent_auth(self: Any, errors: dict[str, str]) -> ConfigFlowResult:
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="agent_auth",
            data_schema=_agent_auth_schema(self._setup_agent_needs_token),
            errors=errors,
        ))

    async def async_step_agent_auth(
        self: Any, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if not self._setup_connection:
            return cast(ConfigFlowResult, await self.async_step_user())
        errors: dict[str, str] = {}
        if user_input is not None:
            auth_data, errors = _agent_auth_input(
                user_input, require_agent_token=self._setup_agent_needs_token,
            )
            if not errors:
                candidate = {**self._setup_connection, **auth_data}
                setup, errors = await async_validate_connection(self.hass, candidate)
                if not errors:
                    self._setup_connection = candidate
                    unique_id = stable_unique_id_from_setup_data(setup)
                    if unique_id is not None:
                        self._setup_unique_id = unique_id
                        self._async_abort_duplicate_setup_flows(unique_id)
                    return cast(ConfigFlowResult, await self.async_step_user_features())
        return cast(ConfigFlowResult, self._show_agent_auth(errors))

    def _show_reconfigure_auth(self: Any, errors: dict[str, str]) -> ConfigFlowResult:
        connection = self._reconfigure_connection
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="reconfigure",
            data_schema=reconfigure_connection_schema(
                connection[CONF_AGENT_HOST],
                connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT),
                "", "", connection.get(CONF_CALLBACK_BASE_URL, ""),
            ),
            errors=errors,
        ))

    async def async_step_reauth(
        self: Any, entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Never use supplied entry data as a new endpoint or identity."""
        self._get_reauth_entry()
        return cast(ConfigFlowResult, await self.async_step_reauth_confirm())

    async def async_step_reauth_confirm(
        self: Any, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            connection = current_connection_options(entry)
            keys = {key: _key_or_saved(user_input, connection, key) for key in _KEYS}
            setup, errors = await async_validate_connection(
                self.hass, {**connection, **keys},
            )
            if not errors and current_connection_options(entry) != connection:
                # An options flow can change the target while the probe awaits.
                # Never save credentials validated for the previous endpoint.
                errors["base"] = "cannot_connect"
            if not errors:
                identity = stable_unique_id_from_setup_data(setup)
                if (
                    identity is not None
                    and not entry_uses_manual_setup_unique_id(entry)
                    and entry.unique_id is not None
                    and identity != entry.unique_id
                ):
                    return cast(ConfigFlowResult, self.async_abort(reason="reauth_wrong_device"))
                options = {key: value for key, value in entry.options.items() if key not in _KEYS}
                changed = options != dict(entry.options) or any(
                    entry.data.get(key) != value for key, value in keys.items()
                )
                # Loaded entries already reload via their update listener. Failed
                # setup has no listener, and unchanged keys do not notify it.
                needs_reload = not entry.update_listeners or not changed
                result = self.async_update_and_abort(
                    entry, data_updates=keys, options=options,
                )
                if needs_reload:
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return cast(ConfigFlowResult, result)
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="reauth_confirm", data_schema=_agent_auth_schema(False), errors=errors,
        ))
