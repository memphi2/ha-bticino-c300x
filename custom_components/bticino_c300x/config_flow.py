"""Config flow for BTicino C300X."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

try:
    from homeassistant.helpers import selector
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    selector = None

from .action import ActionValidationError, parse_actions_json
from .api import (
    C300XAgentApi,
    C300XAgentApiConnectionError,
    C300XAgentApiError,
    build_agent_base_url,
)
from .const import (
    ALARM_DOMAIN,
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_AGENT_USE_SSL,
    CONF_ALARM_ENTITY_ID,
    CONF_BOOTSTRAP_APPLY_GUI_PATCH,
    CONF_BOOTSTRAP_INSTALL_AGENT,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_UI_ENABLED,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_ROTATE_SHARED_SECRET,
    CONF_SHARED_SECRET,
    CONF_STAIR_LIGHT_ADDRESS,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    CONF_WEBHOOK_ID,
    DEFAULT_AGENT_PORT,
    DEFAULT_NAME,
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    DOMAIN,
    WEATHER_DOMAIN,
)
from .dashboard_entities import (
    DASHBOARD_ENTITY_DOMAINS,
    normalize_dashboard_entity_ids,
)
from .device_installer import (
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    async_install_device_agent,
)
from .entry_config import entry_config_value
from .mqtt_migration import async_migrate_legacy_mqtt_for_connection
from .validation_patterns import ENTITY_OBJECT_ID_RE, STAIR_LIGHT_ADDRESS_RE

_QML_PATCH_STATUS_CACHE_TTL = timedelta(seconds=30)
_QML_PATCH_STATUS_UNKNOWN = "unknown"
_QML_PATCH_STATUS_UNAVAILABLE = "unavailable"
_SETUP_VIDEO_ENABLED_DEFAULT = True
_RECONFIGURED_OPTION_KEYS = frozenset(
    {
        CONF_ACTIONS,
        CONF_AGENT_HOST,
        CONF_AGENT_PORT,
        CONF_AGENT_TOKEN,
        CONF_AGENT_USE_SSL,
        CONF_ALARM_ENTITY_ID,
        CONF_DASHBOARD_ENTITIES,
        CONF_DASHBOARD_PREVENT_RETURN,
        CONF_DEVICE_UI_ENABLED,
        CONF_MAINTENANCE_TOKEN,
        CONF_STAIR_LIGHT_ADDRESS,
        CONF_VIDEO_ENABLED,
        CONF_VIDEO_PORT,
        CONF_VIDEO_STREAM_PATH,
        CONF_WEATHER_ENTITY_ID,
    }
)


class BticinoC300XConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BTicino C300X."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize transient flow state."""

        super().__init__()
        self._setup_connection: dict[str, Any] = {}
        self._setup_unique_id: str | None = None
        self._setup_agent_needs_token = False
        self._setup_device_ui_default = True
        self._setup_gui_details_shown = False
        self._reconfigure_connection: dict[str, Any] = {}
        self._reconfigure_gui_details_shown = False

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Collect the C300X device address before agent auth/features."""

        errors: dict[str, str] = {}
        if user_input is not None:
            self._setup_connection, errors = _initial_connection_input(
                user_input,
                include_name=True,
            )
            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=_setup_connection_schema(
                        user_input.get(CONF_NAME, DEFAULT_NAME),
                        user_input.get(CONF_AGENT_HOST, ""),
                        int(user_input.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
                    ),
                    errors=errors,
                )

            await self._async_abort_if_manual_setup_duplicate()
            probe = await _async_probe_agent(self.hass, self._setup_connection)
            self._setup_agent_needs_token = probe == "auth_required"
            if probe == "missing":
                return await self.async_step_agent_missing()
            return await self.async_step_agent_auth()

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_connection_schema(
                DEFAULT_NAME,
                "",
                DEFAULT_AGENT_PORT,
            ),
            errors=errors,
        )

    async def async_step_agent_missing(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Offer an explicit one-shot native-agent bootstrap install."""

        if not self._setup_connection:
            return await self.async_step_user()

        if user_input is not None:
            if bool(user_input.get(CONF_BOOTSTRAP_INSTALL_AGENT, True)):
                return await self.async_step_bootstrap_install()
            self._setup_agent_needs_token = False
            return await self.async_step_agent_auth()

        return self.async_show_form(
            step_id="agent_missing",
            data_schema=_agent_missing_schema(),
            errors={},
        )

    async def async_step_bootstrap_install(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Install the native agent before collecting HA feature options."""

        if not self._setup_connection:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            await self._async_abort_if_manual_setup_duplicate()
            api_token = secrets.token_urlsafe(32)
            maintenance_token = secrets.token_urlsafe(32)
            request = C300XDeviceInstallRequest(
                host=self._setup_connection[CONF_AGENT_HOST],
                ssh_username=str(
                    user_input.get(CONF_BOOTSTRAP_SSH_USERNAME, "")
                ).strip(),
                ssh_password=str(user_input.get(CONF_BOOTSTRAP_SSH_PASSWORD, "")),
                agent_port=int(
                    self._setup_connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
                ),
                apply_gui_patch=bool(user_input.get(CONF_BOOTSTRAP_APPLY_GUI_PATCH, True)),
            )
            try:
                await async_install_device_agent(
                    request,
                    api_token=api_token,
                    maintenance_token=maintenance_token,
                )
            except C300XDeviceInstallError as err:
                errors["base"] = err.reason
            else:
                self._setup_connection[CONF_AGENT_TOKEN] = api_token
                self._setup_connection[CONF_MAINTENANCE_TOKEN] = maintenance_token
                self._setup_connection[CONF_STAIR_LIGHT_ADDRESS] = (
                    DEFAULT_STAIR_LIGHT_ADDRESS
                )
                probe = await _async_probe_agent(
                    self.hass,
                    self._setup_connection,
                    api_token=api_token,
                )
                if probe != "reachable":
                    errors["base"] = "device_install_verify_failed"
                else:
                    try:
                        await async_migrate_legacy_mqtt_for_connection(
                            self.hass,
                            self._setup_connection,
                            api_token=api_token,
                            maintenance_token=maintenance_token,
                        )
                    except C300XAgentApiError:
                        errors["base"] = "device_install_verify_failed"
                        return self.async_show_form(
                            step_id="bootstrap_install",
                            data_schema=_bootstrap_install_schema(),
                            errors=errors,
                        )
                    await self._async_adopt_agent_unique_id(api_token=api_token)
                    self._setup_agent_needs_token = False
                    self._setup_device_ui_default = request.apply_gui_patch
                    return await self.async_step_user_features()

        return self.async_show_form(
            step_id="bootstrap_install",
            data_schema=_bootstrap_install_schema(),
            errors=errors,
        )

    async def _async_abort_if_manual_setup_duplicate(self) -> None:
        """Abort duplicate manual setup before any device mutation can run."""

        await self.async_set_unique_id(_manual_setup_unique_id(self._setup_connection))
        self._abort_if_unique_id_configured()

    async def async_step_agent_auth(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Collect agent tokens after a reachable agent has been found."""

        if not self._setup_connection:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            auth_data, errors = _agent_auth_input(
                user_input,
                require_agent_token=self._setup_agent_needs_token,
            )
            if not errors:
                self._setup_connection.update(auth_data)
                await self._async_adopt_agent_unique_id(
                    api_token=auth_data[CONF_AGENT_TOKEN]
                )
                return await self.async_step_user_features()

        return self.async_show_form(
            step_id="agent_auth",
            data_schema=_agent_auth_schema(self._setup_agent_needs_token),
            errors=errors,
        )

    async def _async_adopt_agent_unique_id(self, *, api_token: str = "") -> None:
        """Use the agent's mDNS identity before creating the config entry."""

        unique_id = await _async_agent_stable_unique_id(
            self.hass,
            self._setup_connection,
            api_token=api_token,
        )
        if unique_id is None:
            return
        self._setup_unique_id = unique_id
        self._async_abort_duplicate_setup_flows(unique_id)

    @callback
    def _async_abort_duplicate_setup_flows(self, unique_id: str) -> None:
        """Abort parallel discovery flows that target the same just-installed agent."""

        flow_manager = getattr(getattr(self.hass, "config_entries", None), "flow", None)
        if flow_manager is None:
            return
        for progress in self._async_in_progress(
            include_uninitialized=True,
            match_context={"unique_id": unique_id},
        ):
            flow_manager.async_abort(progress["flow_id"])

    async def async_step_zeroconf(self, discovery_info: Any) -> config_entries.FlowResult:
        """Start setup from a C300X native-agent mDNS advertisement."""

        from .discovery import (
            discovery_connection_updates,
            discovery_display_name,
            discovery_matches_entry,
            discovery_unique_id,
        )

        properties = getattr(discovery_info, "properties", {}) or {}
        host = str(getattr(discovery_info, "host", "") or "").strip()
        port = int(getattr(discovery_info, "port", DEFAULT_AGENT_PORT) or DEFAULT_AGENT_PORT)
        try:
            connection = discovery_connection_updates(host, port)
        except (TypeError, ValueError):
            return self.async_abort(reason="cannot_connect")

        discovered_unique_id = discovery_unique_id(properties)
        unique_id = discovered_unique_id or DOMAIN
        self._setup_unique_id = unique_id
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates=connection)
        existing_entry_abort = (
            await self._async_abort_if_zeroconf_targets_existing_manual_entry(
                discovered_unique_id,
                connection,
                discovery_matches_entry=discovery_matches_entry,
            )
        )
        if existing_entry_abort is not None:
            return existing_entry_abort
        display_name = discovery_display_name(
            properties,
            getattr(discovery_info, "name", DEFAULT_NAME),
        )
        self.context["title_placeholders"] = {
            "name": display_name,
        }
        self._setup_connection = {
            CONF_NAME: display_name,
            CONF_AGENT_HOST: connection[CONF_AGENT_HOST],
            CONF_AGENT_PORT: connection[CONF_AGENT_PORT],
            CONF_AGENT_USE_SSL: False,
        }
        probe = await _async_probe_agent(self.hass, self._setup_connection)
        self._setup_agent_needs_token = probe == "auth_required"
        if probe == "missing":
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_agent_auth()

    async def _async_abort_if_zeroconf_targets_existing_manual_entry(
        self,
        discovered_unique_id: str | None,
        connection: dict[str, Any],
        *,
        discovery_matches_entry: Any,
    ) -> config_entries.FlowResult | None:
        """Merge a later mDNS identity into an existing manual setup entry."""

        if discovered_unique_id is None:
            return None
        current_entries = getattr(self, "_async_current_entries", None)
        if current_entries is None:
            return None

        for entry in current_entries():
            entry_unique_id = str(getattr(entry, "unique_id", "") or "")
            if discovery_matches_entry(discovered_unique_id, entry_unique_id):
                return None
            if not _entry_uses_manual_setup_unique_id(entry):
                continue
            if not await _async_discovery_targets_configured_entry(
                self.hass,
                entry,
                connection,
            ):
                continue
            self.hass.config_entries.async_update_entry(
                entry,
                unique_id=discovered_unique_id,
            )
            return self.async_abort(reason="already_configured")
        return None

    async def async_step_user_features(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Collect initial C300X feature settings."""

        if not self._setup_connection:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            if _needs_gui_details(
                user_input,
                details_shown=self._setup_gui_details_shown,
            ):
                self._setup_gui_details_shown = True
                return self.async_show_form(
                    step_id="user_features",
                    data_schema=_setup_features_schema(
                        user_input.get(CONF_ALARM_ENTITY_ID, ""),
                        user_input.get(CONF_WEATHER_ENTITY_ID, ""),
                        bool(
                            user_input.get(
                                CONF_VIDEO_ENABLED,
                                _SETUP_VIDEO_ENABLED_DEFAULT,
                            )
                        ),
                        int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
                        user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        ),
                        True,
                        str(user_input.get(CONF_ACTIONS_JSON, "")),
                        bool(user_input.get(CONF_DASHBOARD_PREVENT_RETURN, True)),
                        user_input.get(CONF_DASHBOARD_ENTITIES, []),
                    ),
                    errors=errors,
                )
            feature_data, errors = _feature_input(
                user_input,
                default_video_enabled=_SETUP_VIDEO_ENABLED_DEFAULT,
            )
            if errors:
                return self.async_show_form(
                    step_id="user_features",
                    data_schema=_setup_features_schema(
                        user_input.get(CONF_ALARM_ENTITY_ID, ""),
                        user_input.get(CONF_WEATHER_ENTITY_ID, ""),
                        bool(
                            user_input.get(
                                CONF_VIDEO_ENABLED,
                                _SETUP_VIDEO_ENABLED_DEFAULT,
                            )
                        ),
                        int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
                        user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        ),
                        bool(user_input.get(CONF_DEVICE_UI_ENABLED, False)),
                        str(user_input.get(CONF_ACTIONS_JSON, "")),
                        bool(user_input.get(CONF_DASHBOARD_PREVENT_RETURN, True)),
                        user_input.get(CONF_DASHBOARD_ENTITIES, []),
                    ),
                    errors=errors,
                )

            if self._setup_unique_id is not None:
                self._async_abort_duplicate_setup_flows(self._setup_unique_id)
                await self.async_set_unique_id(
                    self._setup_unique_id,
                    raise_on_progress=False,
                )
            else:
                await self.async_set_unique_id(
                    _manual_setup_unique_id(self._setup_connection)
                )
            self._abort_if_unique_id_configured()

            title = self._setup_connection.pop(CONF_NAME).strip() or DEFAULT_NAME
            return self.async_create_entry(
                title=title,
                data={
                    **self._setup_connection,
                    **feature_data,
                    CONF_WEBHOOK_ID: secrets.token_urlsafe(24),
                    CONF_SHARED_SECRET: secrets.token_urlsafe(32),
                    CONF_EVENT_WEBHOOK_ID: secrets.token_urlsafe(24),
                    CONF_EVENT_WEBHOOK_TOKEN: secrets.token_urlsafe(32),
                },
                options={
                    CONF_ACTIONS: feature_data[CONF_ACTIONS],
                    CONF_DASHBOARD_PREVENT_RETURN: feature_data[
                        CONF_DASHBOARD_PREVENT_RETURN
                    ],
                    CONF_DASHBOARD_ENTITIES: feature_data[CONF_DASHBOARD_ENTITIES],
                },
            )

        return self.async_show_form(
            step_id="user_features",
            data_schema=_setup_features_schema(
                "",
                "",
                _SETUP_VIDEO_ENABLED_DEFAULT,
                DEFAULT_VIDEO_PORT,
                DEFAULT_VIDEO_STREAM_PATH,
                self._setup_device_ui_default,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Reconfigure agent connection and maintenance settings."""

        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            self._reconfigure_connection, errors = _connection_input(
                user_input,
                include_rotate=True,
            )
            if errors:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_reconfigure_connection_schema(
                        user_input.get(CONF_AGENT_HOST, ""),
                        int(user_input.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
                        bool(user_input.get(CONF_AGENT_USE_SSL, False)),
                        str(user_input.get(CONF_AGENT_TOKEN, "")),
                        str(user_input.get(CONF_MAINTENANCE_TOKEN, "")),
                        str(user_input.get(
                            CONF_STAIR_LIGHT_ADDRESS,
                            DEFAULT_STAIR_LIGHT_ADDRESS,
                        )),
                    ),
                    errors=errors,
                )

            return await self.async_step_reconfigure_features()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_reconfigure_connection_schema_from_current(entry),
            errors=errors,
        )

    async def async_step_reconfigure_features(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Reconfigure alarm and video feature settings."""

        entry = self._get_reconfigure_entry()
        if not self._reconfigure_connection:
            self._reconfigure_connection = {
                **_current_connection_options(entry),
                CONF_ROTATE_SHARED_SECRET: False,
            }

        feature_defaults = _current_feature_options(entry)
        errors: dict[str, str] = {}
        if user_input is not None:
            if _needs_gui_details(
                user_input,
                details_shown=self._reconfigure_gui_details_shown,
            ):
                self._reconfigure_gui_details_shown = True
                return self.async_show_form(
                    step_id="reconfigure_features",
                    data_schema=_reconfigure_features_schema(
                        feature_defaults[CONF_ALARM_ENTITY_ID],
                        feature_defaults[CONF_WEATHER_ENTITY_ID],
                        bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
                        str(user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        )),
                        True,
                        _actions_json(feature_defaults[CONF_ACTIONS]),
                        bool(feature_defaults[CONF_DASHBOARD_PREVENT_RETURN]),
                        feature_defaults[CONF_DASHBOARD_ENTITIES],
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(entry)
                    ),
                )
            feature_input = _feature_input_defaults(user_input, feature_defaults)
            feature_data, errors = _feature_input(feature_input)
            if errors:
                return self.async_show_form(
                    step_id="reconfigure_features",
                    data_schema=_reconfigure_features_schema(
                        str(user_input.get(CONF_ALARM_ENTITY_ID, "")),
                        str(user_input.get(CONF_WEATHER_ENTITY_ID, "")),
                        bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
                        str(user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        )),
                        bool(user_input.get(CONF_DEVICE_UI_ENABLED, False)),
                        str(
                            user_input.get(
                                CONF_ACTIONS_JSON,
                                _actions_json(feature_defaults[CONF_ACTIONS]),
                            )
                        ),
                        bool(
                            user_input.get(
                                CONF_DASHBOARD_PREVENT_RETURN,
                                feature_defaults[CONF_DASHBOARD_PREVENT_RETURN],
                            )
                        ),
                        user_input.get(
                            CONF_DASHBOARD_ENTITIES,
                            feature_defaults[CONF_DASHBOARD_ENTITIES],
                        ),
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(entry)
                    ),
                )

            await self.async_set_unique_id(_reconfigure_unique_id(entry))
            self._abort_if_unique_id_mismatch()

            rotate = bool(self._reconfigure_connection.pop(CONF_ROTATE_SHARED_SECRET))
            data_updates = {**self._reconfigure_connection, **feature_data}
            if rotate:
                data_updates[CONF_SHARED_SECRET] = secrets.token_urlsafe(32)
                data_updates[CONF_EVENT_WEBHOOK_TOKEN] = secrets.token_urlsafe(32)

            _clear_reconfigured_option_overrides(self.hass, entry, data_updates)
            updater = getattr(self, "async_update_and_abort", None)
            if updater is not None:
                return updater(entry, data_updates=data_updates)
            return self.async_update_reload_and_abort(entry, data_updates=data_updates)

        return self.async_show_form(
            step_id="reconfigure_features",
            data_schema=_reconfigure_features_schema_from_current(entry),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                entry
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""

        return BticinoC300XOptionsFlow(config_entry)


class BticinoC300XOptionsFlow(config_entries.OptionsFlow):
    """Handle C300X options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._connection_options: dict[str, Any] = {}
        self._gui_details_shown = False

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Start the two-page options flow."""

        return await self.async_step_connection(user_input)

    async def async_step_connection(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Manage agent connection and token options."""

        errors: dict[str, str] = {}
        if user_input is not None:
            self._connection_options, errors = _connection_input(user_input)
            if not errors:
                return await self.async_step_features()

        return self.async_show_form(
            step_id="connection",
            data_schema=_options_connection_schema(self._config_entry),
            errors=errors,
        )

    async def async_step_features(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.FlowResult:
        """Manage integration feature and dashboard options."""

        if not self._connection_options:
            self._connection_options = _current_connection_options(self._config_entry)

        errors: dict[str, str] = {}
        if user_input is not None:
            device_ui_enabled = bool(user_input.get(CONF_DEVICE_UI_ENABLED, False))
            if _needs_gui_details(
                user_input,
                details_shown=self._gui_details_shown,
            ):
                self._gui_details_shown = True
                return self.async_show_form(
                    step_id="features",
                    data_schema=_options_features_schema(
                        self._config_entry,
                        device_ui_enabled=True,
                        video_enabled=bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        video_port=int(
                            user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
                        ),
                        video_stream_path=user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        ),
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(
                            self._config_entry
                        )
                    ),
                )
            feature_data, errors = _feature_input(user_input)
            if errors:
                return self.async_show_form(
                    step_id="features",
                    data_schema=_options_features_schema(
                        self._config_entry,
                        device_ui_enabled=device_ui_enabled,
                        video_enabled=bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        video_port=int(
                            user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
                        ),
                        video_stream_path=user_input.get(
                            CONF_VIDEO_STREAM_PATH,
                            DEFAULT_VIDEO_STREAM_PATH,
                        ),
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(
                            self._config_entry
                        )
                    ),
                )
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        **self._connection_options,
                        **feature_data,
                    },
                )

        return self.async_show_form(
            step_id="features",
            data_schema=_options_features_schema(self._config_entry),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                self._config_entry
            ),
        )


def _setup_connection_schema(
    default_name: str,
    default_agent_host: str,
    default_agent_port: int,
) -> vol.Schema:
    """Return the initial setup schema before auth and feature choices."""

    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=default_name): str,
            vol.Required(CONF_AGENT_HOST, default=default_agent_host): str,
            vol.Optional(CONF_AGENT_PORT, default=default_agent_port): int,
        }
    )


def _agent_missing_schema() -> vol.Schema:
    """Return the explicit agent-missing bootstrap choice schema."""

    return vol.Schema(
        {
            vol.Optional(CONF_BOOTSTRAP_INSTALL_AGENT, default=True): bool,
        }
    )


def _bootstrap_install_schema() -> vol.Schema:
    """Return the one-shot SSH bootstrap install schema."""

    return vol.Schema(
        {
            vol.Required(CONF_BOOTSTRAP_SSH_USERNAME): str,
            vol.Required(CONF_BOOTSTRAP_SSH_PASSWORD): _password_selector(),
            vol.Optional(CONF_BOOTSTRAP_APPLY_GUI_PATCH, default=True): bool,
        }
    )


def _agent_auth_schema(require_agent_token: bool) -> vol.Schema:
    """Return the agent token and device command defaults schema."""

    token_key = (
        vol.Required(CONF_AGENT_TOKEN, default="")
        if require_agent_token
        else vol.Optional(CONF_AGENT_TOKEN, default="")
    )
    return vol.Schema(
        {
            token_key: str,
            vol.Optional(CONF_MAINTENANCE_TOKEN, default=""): str,
            vol.Optional(
                CONF_STAIR_LIGHT_ADDRESS,
                default=DEFAULT_STAIR_LIGHT_ADDRESS,
            ): str,
        }
    )


def _reconfigure_unique_id(entry: config_entries.ConfigEntry) -> str:
    """Return the existing entry unique id for reconfigure flows."""

    return str(getattr(entry, "unique_id", None) or DOMAIN)


def _manual_setup_unique_id(connection: dict[str, Any]) -> str:
    """Return a deterministic unique id for manual setup flows."""

    host = _normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    port = int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    return f"{DOMAIN}:{host}:{port}" if host else DOMAIN


def _entry_uses_manual_setup_unique_id(config_entry: config_entries.ConfigEntry) -> bool:
    """Return true when an existing entry still uses the host-based setup ID."""

    unique_id = str(getattr(config_entry, "unique_id", "") or "")
    return unique_id == DOMAIN or unique_id.startswith(f"{DOMAIN}:")


async def _async_discovery_targets_configured_entry(
    hass: Any,
    config_entry: config_entries.ConfigEntry,
    connection: dict[str, Any],
) -> bool:
    """Return true when a discovery endpoint is the already configured agent."""

    if _entry_connection_matches_discovery(config_entry, connection):
        return True

    token = str(_config_default(config_entry, CONF_AGENT_TOKEN, "") or "").strip()
    if not token:
        return False
    probe_connection = {
        CONF_AGENT_HOST: connection[CONF_AGENT_HOST],
        CONF_AGENT_PORT: connection[CONF_AGENT_PORT],
        CONF_AGENT_USE_SSL: False,
    }
    return (
        await _async_probe_agent(
            hass,
            probe_connection,
            api_token=token,
        )
        == "reachable"
    )


def _entry_connection_matches_discovery(
    config_entry: config_entries.ConfigEntry,
    connection: dict[str, Any],
) -> bool:
    """Return true when host and port already match the discovery endpoint."""

    entry_host = _normalize_discovery_host(
        str(_config_default(config_entry, CONF_AGENT_HOST, "") or "")
    )
    discovery_host = _normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    if not entry_host or entry_host != discovery_host:
        return False
    return int(_config_default(config_entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)) == int(
        connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
    )


def _normalize_discovery_host(host: str) -> str:
    """Normalize a host name for local discovery comparisons."""

    return host.strip().lower().rstrip(".")


def _setup_features_schema(
    default_alarm_entity: str,
    default_weather_entity: str,
    default_video_enabled: bool,
    default_video_port: int,
    default_video_stream_path: str,
    default_device_ui_enabled: bool,
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = True,
    default_dashboard_entities: Any = None,
) -> vol.Schema:
    """Return the initial setup feature schema."""

    return vol.Schema(
        {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            **_setup_gui_dependent_feature_fields(
                default_alarm_entity,
                default_weather_entity,
                default_device_ui_enabled,
                default_actions_json,
                default_dashboard_prevent_return,
                default_dashboard_entities,
            ),
            vol.Optional(CONF_VIDEO_ENABLED, default=default_video_enabled): bool,
            vol.Optional(CONF_VIDEO_PORT, default=default_video_port): int,
            vol.Optional(
                CONF_VIDEO_STREAM_PATH,
                default=default_video_stream_path,
            ): str,
        }
    )


def _reconfigure_connection_schema(
    default_agent_host: str,
    default_agent_port: int,
    default_agent_use_ssl: bool,
    default_agent_token: str,
    default_maintenance_token: str,
    default_stair_light_address: str,
) -> vol.Schema:
    """Return the reconfigure connection schema."""

    return vol.Schema(
        {
            vol.Required(CONF_AGENT_HOST, default=default_agent_host): str,
            vol.Optional(CONF_AGENT_PORT, default=default_agent_port): int,
            vol.Optional(CONF_AGENT_USE_SSL, default=default_agent_use_ssl): bool,
            vol.Required(CONF_AGENT_TOKEN, default=default_agent_token): str,
            vol.Optional(
                CONF_MAINTENANCE_TOKEN,
                default=default_maintenance_token,
            ): str,
            vol.Optional(
                CONF_STAIR_LIGHT_ADDRESS,
                default=default_stair_light_address,
            ): str,
            vol.Optional(CONF_ROTATE_SHARED_SECRET, default=False): bool,
        }
    )


def _reconfigure_features_schema(
    default_alarm_entity: str,
    default_weather_entity: str,
    default_video_enabled: bool,
    default_video_port: int,
    default_video_stream_path: str,
    default_device_ui_enabled: bool,
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = True,
    default_dashboard_entities: Any = None,
) -> vol.Schema:
    """Return the reconfigure feature schema."""

    return vol.Schema(
        {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            **_setup_gui_dependent_feature_fields(
                default_alarm_entity,
                default_weather_entity,
                default_device_ui_enabled,
                default_actions_json,
                default_dashboard_prevent_return,
                default_dashboard_entities,
            ),
            vol.Optional(CONF_VIDEO_ENABLED, default=default_video_enabled): bool,
            vol.Optional(CONF_VIDEO_PORT, default=default_video_port): int,
            vol.Optional(
                CONF_VIDEO_STREAM_PATH,
                default=default_video_stream_path,
            ): str,
        }
    )


def _stair_light_address(value: Any) -> str:
    """Validate the OpenWebNet address segment used by the stair light command."""

    address = str(value or "").strip()
    if not STAIR_LIGHT_ADDRESS_RE.fullmatch(address):
        raise vol.Invalid("invalid staircase light address")
    return address


def _alarm_entity_id(value: Any) -> str:
    """Validate an optional alarm-control-panel entity ID."""

    return _optional_domain_entity_id(
        value,
        domain=ALARM_DOMAIN,
        error="invalid alarm entity",
    )


def _weather_entity_id(value: Any) -> str:
    """Validate an optional weather entity ID."""

    return _optional_domain_entity_id(
        value,
        domain=WEATHER_DOMAIN,
        error="invalid weather entity",
    )


def _optional_domain_entity_id(value: Any, *, domain: str, error: str) -> str:
    """Validate an optional HA entity ID for one domain."""

    entity_id = str(value or "").strip().lower()
    if not entity_id:
        return ""
    if not entity_id.startswith(f"{domain}."):
        raise vol.Invalid(error)
    object_id = entity_id.removeprefix(f"{domain}.")
    if not ENTITY_OBJECT_ID_RE.fullmatch(object_id):
        raise vol.Invalid(error)
    return entity_id


def _dashboard_entity_ids(value: Any) -> list[str]:
    """Validate selected entities for the simple C300X dashboard page."""

    try:
        return list(normalize_dashboard_entity_ids(value, strict=True))
    except ValueError as err:
        raise vol.Invalid("invalid dashboard entities") from err


def _non_empty_string(value: Any) -> str:
    """Validate non-empty setup strings."""

    text = str(value or "").strip()
    if not text:
        raise vol.Invalid("required")
    return text


def _agent_host(value: Any) -> str:
    """Validate the configured device-agent host."""

    host = str(value or "").strip()
    if not host:
        raise vol.Invalid("invalid agent host")
    return host


def _initial_connection_input(
    user_input: dict[str, Any],
    *,
    include_name: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the first setup page without asking for tokens."""

    errors: dict[str, str] = {}
    try:
        agent_host = _agent_host(user_input.get(CONF_AGENT_HOST, ""))
    except vol.Invalid:
        errors[CONF_AGENT_HOST] = "invalid_agent_host"
        agent_host = ""

    data: dict[str, Any] = {
        CONF_AGENT_HOST: agent_host,
        CONF_AGENT_PORT: int(user_input.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        CONF_AGENT_USE_SSL: False,
    }
    if include_name:
        data[CONF_NAME] = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip()
    return data, errors


def _agent_auth_input(
    user_input: dict[str, Any],
    *,
    require_agent_token: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate setup auth values after the agent has been detected."""

    errors: dict[str, str] = {}
    agent_token = str(user_input.get(CONF_AGENT_TOKEN, "")).strip()
    if require_agent_token and not agent_token:
        errors[CONF_AGENT_TOKEN] = "required"
    try:
        stair_light_address = _stair_light_address(
            user_input.get(CONF_STAIR_LIGHT_ADDRESS, DEFAULT_STAIR_LIGHT_ADDRESS)
        )
    except vol.Invalid:
        errors[CONF_STAIR_LIGHT_ADDRESS] = "invalid_stair_light_address"
        stair_light_address = DEFAULT_STAIR_LIGHT_ADDRESS
    return (
        {
            CONF_AGENT_TOKEN: agent_token,
            CONF_MAINTENANCE_TOKEN: str(
                user_input.get(CONF_MAINTENANCE_TOKEN, "")
            ).strip(),
            CONF_STAIR_LIGHT_ADDRESS: stair_light_address,
        },
        errors,
    )


def _connection_input(
    user_input: dict[str, Any],
    *,
    include_name: bool = False,
    include_rotate: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate common connection page input."""

    errors: dict[str, str] = {}
    try:
        agent_host = _agent_host(user_input.get(CONF_AGENT_HOST, ""))
    except vol.Invalid:
        errors[CONF_AGENT_HOST] = "invalid_agent_host"
        agent_host = ""
    agent_token = str(user_input.get(CONF_AGENT_TOKEN, "")).strip()
    try:
        stair_light_address = _stair_light_address(
            user_input.get(CONF_STAIR_LIGHT_ADDRESS, DEFAULT_STAIR_LIGHT_ADDRESS)
        )
    except vol.Invalid:
        errors[CONF_STAIR_LIGHT_ADDRESS] = "invalid_stair_light_address"
        stair_light_address = DEFAULT_STAIR_LIGHT_ADDRESS

    data: dict[str, Any] = {
        CONF_AGENT_HOST: agent_host,
        CONF_AGENT_PORT: int(user_input.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        CONF_AGENT_USE_SSL: bool(user_input.get(CONF_AGENT_USE_SSL, False)),
        CONF_AGENT_TOKEN: agent_token,
        CONF_MAINTENANCE_TOKEN: user_input.get(CONF_MAINTENANCE_TOKEN, "").strip(),
        CONF_STAIR_LIGHT_ADDRESS: stair_light_address,
    }
    if include_name:
        data[CONF_NAME] = user_input.get(CONF_NAME, DEFAULT_NAME).strip()
    if include_rotate:
        data[CONF_ROTATE_SHARED_SECRET] = bool(
            user_input.get(CONF_ROTATE_SHARED_SECRET, False)
        )
    return data, errors


def _feature_input(
    user_input: dict[str, Any],
    *,
    default_video_enabled: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate common feature page input."""

    errors: dict[str, str] = {}
    device_ui_enabled = bool(user_input.get(CONF_DEVICE_UI_ENABLED, False))
    alarm_entity_id = ""
    weather_entity_id = ""
    dashboard_entities: list[str] = []
    actions: dict[str, dict[str, Any]] = {}
    if device_ui_enabled:
        try:
            actions = parse_actions_json(user_input.get(CONF_ACTIONS_JSON, ""))
        except ActionValidationError:
            errors[CONF_ACTIONS_JSON] = "invalid_action_map"
        try:
            alarm_entity_id = _alarm_entity_id(user_input.get(CONF_ALARM_ENTITY_ID, ""))
        except vol.Invalid:
            errors[CONF_ALARM_ENTITY_ID] = "invalid_alarm_entity"
        try:
            weather_entity_id = _weather_entity_id(
                user_input.get(CONF_WEATHER_ENTITY_ID, "")
            )
        except vol.Invalid:
            errors[CONF_WEATHER_ENTITY_ID] = "invalid_weather_entity"
        try:
            dashboard_entities = _dashboard_entity_ids(
                user_input.get(CONF_DASHBOARD_ENTITIES, [])
            )
        except vol.Invalid:
            errors[CONF_DASHBOARD_ENTITIES] = "invalid_dashboard_entities"
    return (
        {
            CONF_ALARM_ENTITY_ID: alarm_entity_id,
            CONF_WEATHER_ENTITY_ID: weather_entity_id,
            CONF_DASHBOARD_ENTITIES: dashboard_entities,
            CONF_ACTIONS: actions,
            CONF_DASHBOARD_PREVENT_RETURN: bool(
                user_input.get(CONF_DASHBOARD_PREVENT_RETURN, True)
                if device_ui_enabled
                else True
            ),
            CONF_VIDEO_ENABLED: bool(
                user_input.get(CONF_VIDEO_ENABLED, default_video_enabled)
            ),
            CONF_VIDEO_PORT: int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
            CONF_VIDEO_STREAM_PATH: user_input.get(
                CONF_VIDEO_STREAM_PATH,
                DEFAULT_VIDEO_STREAM_PATH,
            ),
            CONF_DEVICE_UI_ENABLED: device_ui_enabled,
        },
        errors,
    )


async def _async_probe_agent(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> str:
    """Return reachable, auth_required, or missing for the setup agent probe."""

    try:
        await _async_agent_setup_data(hass, connection, api_token=api_token)
    except C300XAgentApiConnectionError as err:
        message = str(err)
        if "HTTP 401" in message or "HTTP 403" in message:
            return "auth_required"
        return "missing"
    except C300XAgentApiError:
        return "missing"
    return "reachable"


async def _async_agent_stable_unique_id(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> str | None:
    """Return the stable agent ID that mDNS advertises for this device."""

    try:
        setup_data = await _async_agent_setup_data(
            hass,
            connection,
            api_token=api_token,
        )
    except C300XAgentApiError:
        return None
    return _stable_unique_id_from_setup_data(setup_data)


async def _async_agent_setup_data(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> dict[str, Any]:
    """Return setup data from the configured agent endpoint."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    base_url = build_agent_base_url(
        str(connection.get(CONF_AGENT_HOST, "")),
        int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        bool(connection.get(CONF_AGENT_USE_SSL, False)),
    )
    api = C300XAgentApi(async_get_clientsession(hass), base_url, api_token)
    return await api.async_validate_setup()


def _stable_unique_id_from_setup_data(setup_data: dict[str, Any]) -> str | None:
    """Return the normalized config-entry unique ID from agent setup data."""

    from .discovery import discovery_unique_id

    device_id = setup_data.get("device_id")
    return discovery_unique_id({"id": device_id}) if device_id else None


def _options_connection_schema(config_entry: config_entries.ConfigEntry) -> vol.Schema:
    """Return the first options page schema."""

    return vol.Schema(
        {
            vol.Required(
                CONF_AGENT_HOST,
                default=_config_default(config_entry, CONF_AGENT_HOST, ""),
            ): str,
            vol.Optional(
                CONF_AGENT_PORT,
                default=_config_default(
                    config_entry,
                    CONF_AGENT_PORT,
                    DEFAULT_AGENT_PORT,
                ),
            ): int,
            vol.Optional(
                CONF_AGENT_USE_SSL,
                default=_config_default(config_entry, CONF_AGENT_USE_SSL, False),
            ): bool,
            vol.Required(
                CONF_AGENT_TOKEN,
                default=_config_default(config_entry, CONF_AGENT_TOKEN, ""),
            ): str,
            vol.Optional(
                CONF_MAINTENANCE_TOKEN,
                default=_config_default(config_entry, CONF_MAINTENANCE_TOKEN, ""),
            ): str,
            vol.Optional(
                CONF_STAIR_LIGHT_ADDRESS,
                default=_config_default(
                    config_entry,
                    CONF_STAIR_LIGHT_ADDRESS,
                    DEFAULT_STAIR_LIGHT_ADDRESS,
                ),
            ): str,
        }
    )


def _options_features_schema(
    config_entry: config_entries.ConfigEntry,
    *,
    device_ui_enabled: bool | None = None,
    video_enabled: bool | None = None,
    video_port: int | None = None,
    video_stream_path: str | None = None,
) -> vol.Schema:
    """Return the second options page schema."""

    default_device_ui_enabled = (
        bool(_config_default(config_entry, CONF_DEVICE_UI_ENABLED, False))
        if device_ui_enabled is None
        else device_ui_enabled
    )
    default_video_enabled = (
        _config_default(config_entry, CONF_VIDEO_ENABLED, False)
        if video_enabled is None
        else video_enabled
    )
    default_video_port = (
        _config_default(config_entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
        if video_port is None
        else video_port
    )
    default_video_stream_path = (
        _config_default(
            config_entry,
            CONF_VIDEO_STREAM_PATH,
            DEFAULT_VIDEO_STREAM_PATH,
        )
        if video_stream_path is None
        else video_stream_path
    )
    return vol.Schema(
        {
            vol.Optional(
                CONF_DEVICE_UI_ENABLED,
                default=default_device_ui_enabled,
            ): bool,
            **_options_gui_dependent_feature_fields(
                config_entry,
                default_device_ui_enabled,
            ),
            vol.Optional(
                CONF_VIDEO_ENABLED,
                default=default_video_enabled,
            ): bool,
            vol.Optional(
                CONF_VIDEO_PORT,
                default=default_video_port,
            ): int,
            vol.Optional(
                CONF_VIDEO_STREAM_PATH,
                default=default_video_stream_path,
            ): str,
        }
    )


def _setup_gui_dependent_feature_fields(
    default_alarm_entity: str,
    default_weather_entity: str,
    device_ui_enabled: bool,
    default_actions_json: str = "",
    default_dashboard_prevent_return: bool = True,
    default_dashboard_entities: Any = None,
) -> dict[Any, Any]:
    """Return setup/reconfigure fields that require the C300X GUI patch."""

    if not device_ui_enabled:
        return {}
    return {
        _optional_suggested(
            CONF_ALARM_ENTITY_ID,
            default_alarm_entity,
        ): _alarm_entity_selector(),
        _optional_suggested(
            CONF_WEATHER_ENTITY_ID,
            default_weather_entity,
        ): _weather_entity_selector(),
        _optional_suggested(
            CONF_DASHBOARD_ENTITIES,
            _dashboard_entity_ids(default_dashboard_entities or []),
        ): _dashboard_entity_selector(),
        _optional_suggested(
            CONF_ACTIONS_JSON,
            default_actions_json,
        ): _actions_json_field(),
        vol.Optional(
            CONF_DASHBOARD_PREVENT_RETURN,
            default=default_dashboard_prevent_return,
        ): bool,
    }


def _options_gui_dependent_feature_fields(
    config_entry: config_entries.ConfigEntry,
    device_ui_enabled: bool,
) -> dict[Any, Any]:
    """Return option fields that require the C300X GUI patch."""

    if not device_ui_enabled:
        return {}
    return {
        _optional_suggested(
            CONF_ALARM_ENTITY_ID,
            _config_default(config_entry, CONF_ALARM_ENTITY_ID, ""),
        ): _alarm_entity_selector(),
        _optional_suggested(
            CONF_WEATHER_ENTITY_ID,
            _config_default(config_entry, CONF_WEATHER_ENTITY_ID, ""),
        ): _weather_entity_selector(),
        _optional_suggested(
            CONF_DASHBOARD_ENTITIES,
            _dashboard_entity_ids(
                _config_default(config_entry, CONF_DASHBOARD_ENTITIES, [])
            ),
        ): _dashboard_entity_selector(),
        _optional_suggested(
            CONF_ACTIONS_JSON,
            _actions_json(_config_default(config_entry, CONF_ACTIONS, {})),
        ): _actions_json_field(),
        vol.Optional(
            CONF_DASHBOARD_PREVENT_RETURN,
            default=config_entry.options.get(
                CONF_DASHBOARD_PREVENT_RETURN,
                True,
            ),
        ): bool,
    }


def _optional_suggested(key: str, suggested_value: Any) -> vol.Optional:
    """Return an optional form key that can be cleared by the user."""

    if suggested_value in (None, ""):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": suggested_value})


def _needs_gui_details(
    user_input: dict[str, Any],
    *,
    details_shown: bool = False,
) -> bool:
    """Return true when the flow must redisplay GUI-dependent fields."""

    if details_shown:
        return False
    return bool(user_input.get(CONF_DEVICE_UI_ENABLED, False)) and not any(
        field in user_input
        for field in (
            CONF_ALARM_ENTITY_ID,
            CONF_WEATHER_ENTITY_ID,
            CONF_DASHBOARD_ENTITIES,
            CONF_ACTIONS_JSON,
            CONF_DASHBOARD_PREVENT_RETURN,
        )
    )


def _current_connection_options(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Return effective connection options for a restarted options flow."""

    return {
        CONF_AGENT_HOST: _config_default(config_entry, CONF_AGENT_HOST, ""),
        CONF_AGENT_PORT: int(
            _config_default(config_entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
        ),
        CONF_AGENT_USE_SSL: bool(
            _config_default(config_entry, CONF_AGENT_USE_SSL, False)
        ),
        CONF_AGENT_TOKEN: _config_default(config_entry, CONF_AGENT_TOKEN, ""),
        CONF_MAINTENANCE_TOKEN: _config_default(
            config_entry,
            CONF_MAINTENANCE_TOKEN,
            "",
        ),
        CONF_STAIR_LIGHT_ADDRESS: _config_default(
            config_entry,
            CONF_STAIR_LIGHT_ADDRESS,
            DEFAULT_STAIR_LIGHT_ADDRESS,
        ),
    }


def _current_feature_options(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Return effective feature options for reconfigure defaults."""

    return {
        CONF_ALARM_ENTITY_ID: _config_default(config_entry, CONF_ALARM_ENTITY_ID, ""),
        CONF_WEATHER_ENTITY_ID: _config_default(
            config_entry,
            CONF_WEATHER_ENTITY_ID,
            "",
        ),
        CONF_DASHBOARD_ENTITIES: _dashboard_entity_ids(
            _config_default(config_entry, CONF_DASHBOARD_ENTITIES, [])
        ),
        CONF_VIDEO_ENABLED: bool(
            _config_default(config_entry, CONF_VIDEO_ENABLED, False)
        ),
        CONF_VIDEO_PORT: int(
            _config_default(config_entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
        ),
        CONF_VIDEO_STREAM_PATH: _config_default(
            config_entry,
            CONF_VIDEO_STREAM_PATH,
            DEFAULT_VIDEO_STREAM_PATH,
        ),
        CONF_DEVICE_UI_ENABLED: bool(
            _config_default(config_entry, CONF_DEVICE_UI_ENABLED, False)
        ),
        CONF_ACTIONS: _config_default(config_entry, CONF_ACTIONS, {}),
        CONF_DASHBOARD_PREVENT_RETURN: bool(
            _config_default(config_entry, CONF_DASHBOARD_PREVENT_RETURN, True)
        ),
    }


def _reconfigure_connection_schema_from_current(
    config_entry: config_entries.ConfigEntry,
) -> vol.Schema:
    """Return the reconfigure connection schema using effective entry values."""

    current = _current_connection_options(config_entry)
    return _reconfigure_connection_schema(
        current[CONF_AGENT_HOST],
        int(current[CONF_AGENT_PORT]),
        bool(current[CONF_AGENT_USE_SSL]),
        current[CONF_AGENT_TOKEN],
        current[CONF_MAINTENANCE_TOKEN],
        current[CONF_STAIR_LIGHT_ADDRESS],
    )


def _reconfigure_features_schema_from_current(
    config_entry: config_entries.ConfigEntry,
) -> vol.Schema:
    """Return the reconfigure features schema using effective entry values."""

    current = _current_feature_options(config_entry)
    return _reconfigure_features_schema(
        current[CONF_ALARM_ENTITY_ID],
        current[CONF_WEATHER_ENTITY_ID],
        bool(current[CONF_VIDEO_ENABLED]),
        int(current[CONF_VIDEO_PORT]),
        current[CONF_VIDEO_STREAM_PATH],
        bool(current[CONF_DEVICE_UI_ENABLED]),
        _actions_json(current[CONF_ACTIONS]),
        bool(current[CONF_DASHBOARD_PREVENT_RETURN]),
        current[CONF_DASHBOARD_ENTITIES],
    )


def _feature_input_defaults(
    user_input: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Return feature input with hidden GUI fields preserved when absent."""

    data = dict(user_input)
    if not bool(data.get(CONF_DEVICE_UI_ENABLED, False)):
        return data
    data.setdefault(CONF_ALARM_ENTITY_ID, defaults[CONF_ALARM_ENTITY_ID])
    data.setdefault(CONF_WEATHER_ENTITY_ID, defaults[CONF_WEATHER_ENTITY_ID])
    data.setdefault(CONF_DASHBOARD_ENTITIES, defaults.get(CONF_DASHBOARD_ENTITIES, []))
    data.setdefault(CONF_ACTIONS_JSON, _actions_json(defaults[CONF_ACTIONS]))
    data.setdefault(
        CONF_DASHBOARD_PREVENT_RETURN,
        defaults[CONF_DASHBOARD_PREVENT_RETURN],
    )
    return data


def _clear_reconfigured_option_overrides(
    hass: Any,
    config_entry: config_entries.ConfigEntry,
    data_updates: dict[str, Any],
) -> None:
    """Clear stale option values for settings written through reconfigure."""

    options = dict(config_entry.options)
    keys_to_clear = _RECONFIGURED_OPTION_KEYS & data_updates.keys()
    if not options or not keys_to_clear:
        return
    updated_options = {
        key: value for key, value in options.items() if key not in keys_to_clear
    }
    if updated_options == options:
        return
    hass.config_entries.async_update_entry(config_entry, options=updated_options)


def _config_default(
    config_entry: config_entries.ConfigEntry,
    key: str,
    default: Any,
) -> Any:
    """Return an option override when present, otherwise setup data."""

    return entry_config_value(config_entry, key, default)


async def _async_qml_patch_description_placeholders(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, str]:
    """Return placeholders for the device GUI patch status."""

    return {
        "qml_patch_status": _qml_patch_status_label(
            await _async_qml_patch_status(config_entry)
        )
    }


async def _async_qml_patch_status(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Return cached QML patch status, refreshing it only when useful."""

    runtime_data = getattr(config_entry, "runtime_data", None)
    if runtime_data is None:
        return {}

    cached_status = getattr(runtime_data, "qml_patch_status", {})
    if not isinstance(cached_status, dict):
        cached_status = {}

    updated_at = getattr(runtime_data, "qml_patch_status_updated_at", None)
    now = datetime.now(UTC)
    if (
        cached_status
        and isinstance(updated_at, datetime)
        and now - updated_at < _QML_PATCH_STATUS_CACHE_TTL
    ):
        return cached_status

    api = getattr(runtime_data, "api", None)
    if api is None:
        return cached_status

    try:
        status = await api.async_qml_patch_status()
    except C300XAgentApiError:
        return cached_status or {
            "available": False,
            "state": _QML_PATCH_STATUS_UNAVAILABLE,
        }

    runtime_data.qml_patch_status = status
    runtime_data.qml_patch_status_updated_at = now
    return status


def _qml_patch_status_label(status: dict[str, Any]) -> str:
    """Return a concise, user-visible QML patch status label."""

    if not status:
        return _QML_PATCH_STATUS_UNKNOWN
    if status.get("available") is False:
        return _QML_PATCH_STATUS_UNAVAILABLE
    patched = status.get("patched")
    if patched is True:
        return "patched"
    if patched is False:
        return "original"
    state = str(status.get("state") or "").strip()
    return state or _QML_PATCH_STATUS_UNKNOWN


def _actions_json(actions: Any) -> str:
    """Return stable JSON for the action allowlist options form."""

    if not actions:
        return ""
    return json.dumps(actions, indent=2, sort_keys=True)


def _alarm_entity_selector() -> Any:
    """Return the HA alarm entity selector with a test-friendly fallback."""

    if selector is None:
        return str
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=ALARM_DOMAIN),
    )


def _weather_entity_selector() -> Any:
    """Return the HA weather entity selector with a test-friendly fallback."""

    if selector is None:
        return str
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=WEATHER_DOMAIN),
    )


def _dashboard_entity_selector() -> Any:
    """Return a multi-entity selector for the simple C300X dashboard."""

    if selector is None:
        return list
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=list(DASHBOARD_ENTITY_DOMAINS),
            multiple=True,
        ),
    )


def _password_selector() -> Any:
    """Return a password field without storing the submitted secret."""

    if selector is None:
        return str
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD),
    )


def _actions_json_field() -> Any:
    """Return the HA multiline text selector for action JSON."""

    if selector is None:
        return str
    return selector.TextSelector(selector.TextSelectorConfig(multiline=True))
