"""Read-only credential validation and entry-bound authentication flows."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import C300XAgentApi, build_agent_base_url
from .api_errors import C300XAgentApiAuthError, C300XAgentApiError
from .config_flow_c100x import C100XOptInSteps
from .config_flow_entry_update import (
    async_ensure_entry_reload,
    async_update_reconfigured_entry,
)
from .config_flow_features import current_connection_options
from .config_flow_identity import (
    entry_connection_matches_discovery,
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
from .discovery import discovery_matches_entry
from .runtime_auth import REAUTH_MAINTENANCE

_KEYS = (CONF_AGENT_TOKEN, CONF_MAINTENANCE_TOKEN)
_REJECTED_KEY = {"invalid_auth": CONF_AGENT_TOKEN, "invalid_maintenance_auth": CONF_MAINTENANCE_TOKEN}


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


async def async_validate_entry_connection(
    hass: Any, entry: Any, connection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate credentials and bind a replacement endpoint to the same device."""

    saved = current_connection_options(entry)
    saved_id = getattr(entry, "unique_id", None)
    expected = saved_id
    if entry_uses_manual_setup_unique_id(entry) or expected is None:
        expected = None
        if not entry_connection_matches_discovery(entry, connection):
            original, errors = await async_validate_connection(hass, saved)
            if errors:
                return {}, errors
            expected = stable_unique_id_from_setup_data(original)
            if expected is None:
                return {}, {"base": "cannot_connect"}
    setup, errors = await async_validate_connection(hass, connection)
    if not errors and (
        saved != current_connection_options(entry)
        or saved_id != getattr(entry, "unique_id", None)
    ):
        return {}, {"base": "cannot_connect"}
    if not errors and expected is not None:
        actual = stable_unique_id_from_setup_data(setup)
        if actual is None:
            return {}, {"base": "cannot_connect"}
        if not discovery_matches_entry(actual, expected):
            return {}, {"base": "wrong_device"}
    return setup, errors


class AuthFlowSteps(C100XOptInSteps):
    """Share setup validation and reauth without expanding the main wizard."""

    _setup_unique_id: str | None

    def _setup_identity_error(self: Any, setup: dict[str, Any]) -> dict[str, str]:
        identity = stable_unique_id_from_setup_data(setup)
        if self._setup_unique_id is not None:
            if identity is None:
                return {"base": "cannot_connect"}
            if not discovery_matches_entry(identity, self._setup_unique_id):
                return {"base": "wrong_device"}
        self._setup_unique_id = identity
        return {}

    async def _async_validate_setup_identity(self: Any) -> dict[str, str]:
        setup, errors = await async_validate_connection(self.hass, self._setup_connection)
        return errors or cast(dict[str, str], self._setup_identity_error(setup))

    def _async_update_reconfigured_entry(
        self: Any, entry: Any, data_updates: dict[str, Any], clear_keys: frozenset[str],
    ) -> ConfigFlowResult:
        return async_update_reconfigured_entry(
            self, entry, data_updates, clear_keys, force_reload=True,
        )

    def _note_setup_rejection(self: Any, errors: dict[str, str], candidate: dict[str, Any]) -> None:
        """Remember the key value the device rejected, per field.

        A check that got past a key accepted it: a rejected maintenance key
        means the access key was accepted, and a passed check accepts both.
        """
        base = errors.get("base", "")
        rejected = dict(getattr(self, "_setup_rejected", {}))
        if not errors:
            rejected.clear()
        elif base == "invalid_maintenance_auth":
            rejected.pop(CONF_AGENT_TOKEN, None)
        key = _REJECTED_KEY.get(base)
        if key is not None:
            rejected[key] = candidate.get(key)
        self._setup_rejected = rejected

    def _setup_retry_keys(self: Any) -> dict[str, Any] | None:
        """Keys an empty retry field keeps.

        After an SSH installation the generated keys are kept: they were never
        shown. After the final check, an empty field keeps the key entered
        last, unless the device rejected that very key, so a rejected key can
        be removed and a key typed on an earlier retry is not lost.
        """
        if self._setup_bootstrapped:
            return cast(dict[str, Any], self._setup_connection)
        if self._setup_pending_features is None:
            return None
        rejected = getattr(self, "_setup_rejected", {})
        return {key: value for key, value in self._setup_connection.items()
                if key not in rejected or rejected[key] != value}

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
                saved=self._setup_retry_keys(),
            )
            if not errors:
                candidate = {**self._setup_connection, **auth_data}
                setup, errors = await async_validate_connection(self.hass, candidate)
                self._note_setup_rejection(errors, candidate)
                if not errors and self._c100x_opt_in_missing(setup):
                    # A Classe 100X is experimental: set up only when asked for.
                    return cast(ConfigFlowResult, await self._async_ask_c100x_opt_in("agent_auth", user_input))
                if not errors:
                    errors = self._setup_identity_error(setup)
                if errors and self._setup_pending_features is not None and not self._setup_bootstrapped:
                    # Keys typed on this retry stay for the next one.
                    self._setup_connection = candidate
                if not errors:
                    self._setup_connection = candidate
                    # The model decides the C100X display defaults.
                    self._setup_agent_info.clear()
                    self._setup_agent_info.update(setup)
                    unique_id = stable_unique_id_from_setup_data(setup)
                    if unique_id is not None:
                        self._setup_unique_id = unique_id
                        self._async_abort_duplicate_setup_flows(unique_id)
                    if self._setup_pending_features is not None:
                        return cast(ConfigFlowResult, await self._async_create_setup_entry(self._setup_pending_features))
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
        self._reauth_maintenance = entry_data.get(REAUTH_MAINTENANCE) is True
        return cast(ConfigFlowResult, await self.async_step_reauth_confirm())

    async def async_step_reauth_confirm(
        self: Any, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            connection = current_connection_options(entry)
            keys = {key: _key_or_saved(user_input, connection, key) for key in _KEYS}
            if getattr(self, "_reauth_maintenance", False) and not keys[CONF_MAINTENANCE_TOKEN]:
                # Without a key nothing would be checked and the rejection would return.
                errors = {CONF_MAINTENANCE_TOKEN: "required"}
            else:
                _, errors = await async_validate_entry_connection(
                    self.hass, entry, {**connection, **keys},
                )
            if errors.get("base") == "wrong_device":
                return cast(ConfigFlowResult, self.async_abort(reason="reauth_wrong_device"))
            if not errors and current_connection_options(entry) != connection:
                # An options flow can change the target while the probe awaits.
                # Never save credentials validated for the previous endpoint.
                errors["base"] = "cannot_connect"
            if not errors:
                options = {key: value for key, value in entry.options.items() if key not in _KEYS}
                changed = options != dict(entry.options) or any(
                    entry.data.get(key) != value for key, value in keys.items()
                )
                had_listeners = bool(entry.update_listeners)
                result = self.async_update_and_abort(
                    entry, data_updates=keys, options=options,
                )
                async_ensure_entry_reload(self.hass, entry, changed=changed, had_listeners=had_listeners, force=True)
                return cast(ConfigFlowResult, result)
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="reauth_confirm", data_schema=_agent_auth_schema(False), errors=errors,
        ))
