"""Config flow for BTicino C300X."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .api import (
    C300XAgentApi,
    C300XAgentApiConnectionError,
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
    build_agent_base_url,
)
from .config_flow_activations import (
    ACTIVATION_STEP_DONE as _ACTIVATION_STEP_DONE,
)
from .config_flow_activations import (
    ACTIVATION_STEP_ITEM as _ACTIVATION_STEP_ITEM,
)
from .config_flow_activations import (
    activation_item_form as _activation_item_form,
)
from .config_flow_activations import (
    activation_item_limit as _activation_item_limit,
)
from .config_flow_activations import (
    activation_item_step as _activation_item_step,
)
from .config_flow_activations import (
    activation_items_from_feature_data as _activation_items_from_feature_data,
)
from .config_flow_activations import (
    activation_manage_form as _activation_manage_form,
)
from .config_flow_activations import (
    activation_manage_step as _activation_manage_step,
)
from .config_flow_activations import (
    activation_settings_step as _activation_settings_step,
)
from .config_flow_dashboard import (
    DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT as _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
)
from .config_flow_dashboard import (
    DASHBOARD_PREVENT_RETURN_DEFAULT as _DASHBOARD_PREVENT_RETURN_DEFAULT,
)
from .config_flow_dashboard import (
    dashboard_entity_display_form_complete as _dashboard_entity_display_form_complete,
)
from .config_flow_dashboard import (
    dashboard_entity_display_schema as _dashboard_entity_display_schema,
)
from .config_flow_dashboard import (
    dashboard_input_defaults as _dashboard_input_defaults,
)
from .config_flow_dashboard import (
    dashboard_schema as _dashboard_schema,
)
from .config_flow_features import (
    current_connection_options as _current_connection_options,
)
from .config_flow_features import (
    current_feature_options as _current_feature_options,
)
from .config_flow_features import (
    feature_input_defaults as _feature_input_defaults,
)
from .config_flow_features import (
    options_connection_schema as _options_connection_schema,
)
from .config_flow_features import (
    options_features_schema as _options_features_schema,
)
from .config_flow_features import (
    reconfigure_connection_schema_from_current as _reconfigure_connection_schema_from_current,
)
from .config_flow_features import (
    reconfigure_features_schema_from_current as _reconfigure_features_schema_from_current,
)
from .config_flow_features import (
    webrtc_ice_policy_or_default as _webrtc_ice_policy_or_default,
)
from .config_flow_forms import (
    actions_json as _actions_json,
)
from .config_flow_input import (
    _agent_auth_input,
    _agent_auth_schema,
    _agent_host,
    _agent_missing_schema,
    _alarm_entity_id,
    _bootstrap_install_schema,
    _connection_input,
    _feature_input,
    _initial_connection_input,
    _non_empty_string,
    _setup_connection_schema,
    _weather_entity_id,
)
from .config_schemas import (
    reconfigure_connection_schema as _reconfigure_connection_schema,
)
from .config_schemas import (
    reconfigure_features_schema as _reconfigure_features_schema,
)
from .config_schemas import (
    setup_features_schema as _setup_features_schema,
)
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_BOOTSTRAP_INSTALL_AGENT,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_UI_ENABLED,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_ROTATE_SHARED_SECRET,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    CONF_WEBHOOK_ID,
    CONF_WEBRTC_ICE_POLICY,
    DEFAULT_AGENT_PORT,
    DEFAULT_NAME,
    DOMAIN,
)
from .device_installer import (
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    async_ensure_installer_dependencies,
    async_install_device_agent,
)
from .entry_config import entry_config_value
from .entry_types import BticinoC300XConfigEntry
from .mqtt_migration import async_migrate_legacy_mqtt_for_connection

__all__ = [
    "_agent_auth_input",
    "_agent_auth_schema",
    "_agent_host",
    "_agent_missing_schema",
    "_alarm_entity_id",
    "_bootstrap_install_schema",
    "_connection_input",
    "_feature_input",
    "_initial_connection_input",
    "_non_empty_string",
    "_setup_connection_schema",
    "_weather_entity_id",
]

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult as FlowResult
else:
    FlowResult = dict[str, Any]

_QML_PATCH_STATUS_CACHE_TTL = timedelta(seconds=30)
_QML_PATCH_STATUS_UNKNOWN = "unknown"
_QML_PATCH_STATUS_UNAVAILABLE = "unavailable"
_SETUP_VIDEO_ENABLED_DEFAULT = True
_CREATE_HOMEASSISTANT_USER_DEFAULT = True
_RECONFIGURED_OPTION_KEYS = frozenset(
    {
        CONF_ACTIONS,
        CONF_AGENT_HOST,
        CONF_AGENT_PORT,
        CONF_AGENT_TOKEN,
        CONF_CALLBACK_BASE_URL,
        CONF_CREATE_HOMEASSISTANT_USER,
        CONF_ALARM_ENTITY_ID,
        CONF_ALARM_PAGE_ENTITY_ID,
        CONF_DASHBOARD_ENTITIES,
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
        CONF_DASHBOARD_PREVENT_RETURN,
        CONF_DEVICE_ACTIVATION_MODE,
        CONF_DEVICE_ACTIVATIONS,
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
        CONF_DEVICE_UI_ENABLED,
        CONF_DOORSTATION_AUDIO_GAIN_DB,
        CONF_MAINTENANCE_TOKEN,
        CONF_RING_CAPTURE_AUDIO_GAIN_DB,
        CONF_VIDEO_ENABLED,
        CONF_VIDEO_PORT,
        CONF_VIDEO_STREAM_PATH,
        CONF_WEATHER_ENTITY_ID,
        CONF_WEBRTC_ICE_POLICY,
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
        self._setup_device_ui_default = False
        self._setup_feature_data: dict[str, Any] = {}
        self._setup_device_activations: list[dict[str, Any]] = []
        self._setup_activation_edit_id: str | None = None
        self._setup_dashboard_input: dict[str, Any] = {}
        self._reconfigure_connection: dict[str, Any] = {}
        self._reconfigure_feature_data: dict[str, Any] = {}
        self._reconfigure_device_activations: list[dict[str, Any]] = []
        self._reconfigure_activation_edit_id: str | None = None
        self._reconfigure_dashboard_input: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
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
                        str(user_input.get(CONF_CALLBACK_BASE_URL, "")),
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
    ) -> FlowResult:
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
    ) -> FlowResult:
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
                apply_gui_patch=False,
            )
            try:
                await async_ensure_installer_dependencies(self.hass)
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
    ) -> FlowResult:
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

    async def async_step_zeroconf(
        self, discovery_info: Any
    ) -> FlowResult:
        """Start setup from a C300X native-agent mDNS advertisement."""

        from .discovery import (
            discovery_connection_updates,
            discovery_display_name,
            discovery_matches_entry,
            discovery_unique_id,
        )

        properties = getattr(discovery_info, "properties", {}) or {}
        host = str(getattr(discovery_info, "host", "") or "").strip()
        port = int(
            getattr(discovery_info, "port", DEFAULT_AGENT_PORT) or DEFAULT_AGENT_PORT
        )
        try:
            connection = discovery_connection_updates(host, port)
        except (TypeError, ValueError):
            return self.async_abort(reason="cannot_connect")

        discovered_unique_id = discovery_unique_id(properties)
        unique_id = discovered_unique_id or DOMAIN
        self._setup_unique_id = unique_id
        await self.async_set_unique_id(unique_id)
        self._async_request_existing_entry_event_registration(
            discovered_unique_id,
            connection,
            discovery_matches_entry=discovery_matches_entry,
        )
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
    ) -> FlowResult | None:
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
            self._async_request_event_registration(entry)
            return self.async_abort(reason="already_configured")
        return None

    @callback
    def _async_request_existing_entry_event_registration(
        self,
        discovered_unique_id: str | None,
        connection: dict[str, Any],
        *,
        discovery_matches_entry: Any,
    ) -> None:
        """Ask a loaded matching entry to renew its runtime agent subscription."""

        if discovered_unique_id is None:
            return
        current_entries = getattr(self, "_async_current_entries", None)
        if current_entries is None:
            return
        for entry in current_entries():
            if not discovery_matches_entry(
                discovered_unique_id,
                str(getattr(entry, "unique_id", "") or ""),
            ):
                continue
            if not _entry_connection_matches_discovery(entry, connection):
                return
            self._async_request_event_registration(entry)
            return

    @callback
    def _async_request_event_registration(
        self,
        entry: BticinoC300XConfigEntry,
    ) -> None:
        """Trigger HA-to-agent runtime subscription renewal for a loaded entry."""

        from .events import async_request_agent_event_registration

        async_request_agent_event_registration(self.hass, entry)

    async def async_step_user_features(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Collect initial C300X feature settings."""

        if not self._setup_connection:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        if user_input is not None:
            feature_data, errors = _feature_input(
                user_input,
                default_video_enabled=_SETUP_VIDEO_ENABLED_DEFAULT,
            )
            if errors:
                return self.async_show_form(
                    step_id="user_features",
                    data_schema=_setup_features_schema(
                        bool(
                            user_input.get(
                                CONF_VIDEO_ENABLED,
                                _SETUP_VIDEO_ENABLED_DEFAULT,
                            )
                        ),
                        default_create_homeassistant_user=bool(
                            user_input.get(
                                CONF_CREATE_HOMEASSISTANT_USER,
                                _CREATE_HOMEASSISTANT_USER_DEFAULT,
                            )
                        ),
                    ),
                    errors=errors,
            )

            self._setup_feature_data = feature_data
            self._setup_device_activations = _activation_items_from_feature_data(
                feature_data
            )
            return await self.async_step_user_device_activations()

        return self.async_show_form(
            step_id="user_features",
            data_schema=_setup_features_schema(
                _SETUP_VIDEO_ENABLED_DEFAULT,
                default_create_homeassistant_user=_CREATE_HOMEASSISTANT_USER_DEFAULT,
            ),
            errors=errors,
        )

    async def async_step_user_device_activations(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage additional C300X device activations during setup."""

        if not self._setup_feature_data:
            return await self.async_step_user_features()

        self._setup_feature_data, setting_errors = _activation_settings_step(
            user_input,
            self._setup_feature_data,
        )
        if setting_errors:
            return _activation_manage_form(
                self.async_show_form,
                step_id="user_device_activations",
                items=self._setup_device_activations,
                feature_data=self._setup_feature_data,
                errors=setting_errors,
            )

        result = _activation_manage_step(
            user_input,
            self._setup_device_activations,
            max_items=_activation_item_limit(self._setup_feature_data),
        )
        self._setup_device_activations = result.items
        self._setup_activation_edit_id = result.edit_id
        if result.next_step == _ACTIVATION_STEP_DONE:
            self._setup_feature_data[CONF_DEVICE_ACTIVATIONS] = list(result.items)
            return await self.async_step_user_dashboard()
        if result.next_step == _ACTIVATION_STEP_ITEM:
            return _activation_item_form(
                self.async_show_form,
                step_id="user_device_activation_item",
                items=result.items,
                edit_id=result.edit_id,
                errors=result.errors,
            )

        return _activation_manage_form(
            self.async_show_form,
            step_id="user_device_activations",
            items=result.items,
            feature_data=self._setup_feature_data,
            errors=result.errors,
        )

    async def async_step_user_device_activation_item(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add or edit one C300X device activation during setup."""

        if not self._setup_feature_data:
            return await self.async_step_user_features()

        result = _activation_item_step(
            user_input,
            self._setup_device_activations,
            self._setup_activation_edit_id,
            self._setup_feature_data,
        )
        self._setup_device_activations = result.items
        self._setup_activation_edit_id = result.edit_id
        if result.next_step != _ACTIVATION_STEP_ITEM:
            return await self.async_step_user_device_activations()

        return _activation_item_form(
            self.async_show_form,
            step_id="user_device_activation_item",
            items=result.items,
            edit_id=result.edit_id,
            errors=result.errors,
        )

    async def async_step_user_dashboard(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Collect initial C300X display dashboard settings."""

        if not self._setup_feature_data:
            return await self.async_step_user_features()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._setup_dashboard_input = _dashboard_input_defaults(user_input)
            if (
                self._setup_dashboard_input[CONF_DEVICE_UI_ENABLED]
                and self._setup_dashboard_input[CONF_DASHBOARD_ENTITIES]
            ):
                return self._async_show_user_dashboard_entity_display_form(None, errors)
            return await self._async_create_setup_entry_from_dashboard(errors)

        return self._async_show_user_dashboard_form(user_input, errors)

    async def async_step_user_dashboard_entity_display(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Collect per-entity display labels for the initial C300X dashboard."""

        if not self._setup_dashboard_input:
            return await self.async_step_user_dashboard()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _dashboard_entity_display_form_complete(
                user_input,
                self._setup_dashboard_input[CONF_DASHBOARD_ENTITIES],
            ):
                return self._async_show_user_dashboard_entity_display_form(
                    user_input,
                    errors,
                )
            self._setup_dashboard_input[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] = (
                _dashboard_input_defaults(
                    {
                        **self._setup_dashboard_input,
                        **user_input,
                    }
                )[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]
            )
            return await self._async_create_setup_entry_from_dashboard(errors)
        return self._async_show_user_dashboard_entity_display_form(user_input, errors)

    async def _async_create_setup_entry_from_dashboard(
        self,
        errors: dict[str, str],
    ) -> FlowResult:
        """Create the setup entry from collected setup feature/dashboard pages."""

        feature_data, errors = _feature_input(
            {**self._setup_feature_data, **self._setup_dashboard_input},
            default_video_enabled=_SETUP_VIDEO_ENABLED_DEFAULT,
        )
        if errors:
            return self._async_show_user_dashboard_form(
                self._setup_dashboard_input,
                errors,
            )
        return await self._async_create_setup_entry(feature_data)

    def _async_show_user_dashboard_form(
        self,
        user_input: dict[str, Any] | None,
        errors: dict[str, str],
    ) -> FlowResult:
        """Show initial C300X display dashboard settings."""

        return self.async_show_form(
            step_id="user_dashboard",
            data_schema=_dashboard_schema(
                str((user_input or {}).get(CONF_ALARM_ENTITY_ID, "")),
                str((user_input or {}).get(CONF_WEATHER_ENTITY_ID, "")),
                str((user_input or {}).get(CONF_ACTIONS_JSON, "")),
                bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_PREVENT_RETURN,
                        _DASHBOARD_PREVENT_RETURN_DEFAULT,
                    )
                ),
                (user_input or {}).get(CONF_DASHBOARD_ENTITIES, []),
                (user_input or {}).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    {},
                ),
                default_dashboard_dynamic_homepage=bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                        _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
                    )
                ),
                default_alarm_page_entity=str(
                    (user_input or {}).get(CONF_ALARM_PAGE_ENTITY_ID, "")
                ),
                default_device_ui_enabled=bool(
                    (user_input or {}).get(
                        CONF_DEVICE_UI_ENABLED,
                        self._setup_device_ui_default,
                    )
                ),
            ),
            errors=errors,
            description_placeholders={
                "qml_patch_status": _QML_PATCH_STATUS_UNKNOWN,
            },
        )

    def _async_show_user_dashboard_entity_display_form(
        self,
        user_input: dict[str, Any] | None,
        errors: dict[str, str],
    ) -> FlowResult:
        """Show initial per-entity C300X display dashboard settings."""

        return self.async_show_form(
            step_id="user_dashboard_entity_display",
            data_schema=_dashboard_entity_display_schema(
                self._setup_dashboard_input.get(CONF_DASHBOARD_ENTITIES, []),
                (user_input or self._setup_dashboard_input).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    {},
                ),
            ),
            errors=errors,
        )

    async def _async_create_setup_entry(
        self,
        feature_data: dict[str, Any],
    ) -> FlowResult:
        """Create the initial config entry after feature collection."""

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
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE: feature_data[
                    CONF_DASHBOARD_DYNAMIC_HOMEPAGE
                ],
                CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: feature_data[
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES
                ],
            },
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
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
                        str(user_input.get(CONF_AGENT_TOKEN, "")),
                        str(user_input.get(CONF_MAINTENANCE_TOKEN, "")),
                        str(user_input.get(CONF_CALLBACK_BASE_URL, "")),
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
    ) -> FlowResult:
        """Reconfigure media and display feature settings."""

        entry = self._get_reconfigure_entry()
        if not self._reconfigure_connection:
            self._reconfigure_connection = {
                **_current_connection_options(entry),
                CONF_ROTATE_SHARED_SECRET: False,
            }

        feature_defaults = _current_feature_options(entry)
        errors: dict[str, str] = {}
        if user_input is not None:
            feature_input = _feature_input_defaults(user_input, feature_defaults)
            feature_data, errors = _feature_input(feature_input)
            if errors:
                return self.async_show_form(
                    step_id="reconfigure_features",
                    data_schema=_reconfigure_features_schema(
                        bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        default_create_homeassistant_user=bool(
                            user_input.get(
                                CONF_CREATE_HOMEASSISTANT_USER,
                                feature_defaults[CONF_CREATE_HOMEASSISTANT_USER],
                            )
                        ),
                        default_doorstation_audio_gain_db=float(
                            feature_data[CONF_DOORSTATION_AUDIO_GAIN_DB]
                        ),
                        default_ring_capture_audio_gain_db=float(
                            feature_data[CONF_RING_CAPTURE_AUDIO_GAIN_DB]
                        ),
                        default_webrtc_ice_policy=_webrtc_ice_policy_or_default(
                            user_input.get(
                                CONF_WEBRTC_ICE_POLICY,
                                feature_defaults[CONF_WEBRTC_ICE_POLICY],
                            )
                        ),
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(entry)
                    ),
            )

            self._reconfigure_feature_data = feature_data
            self._reconfigure_device_activations = _activation_items_from_feature_data(
                feature_data
            )
            return await self.async_step_reconfigure_device_activations()

        return self.async_show_form(
            step_id="reconfigure_features",
            data_schema=_reconfigure_features_schema_from_current(entry),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                entry
            ),
        )

    async def async_step_reconfigure_device_activations(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Reconfigure additional C300X device activations."""

        if not self._reconfigure_feature_data:
            return await self.async_step_reconfigure_features()

        self._reconfigure_feature_data, setting_errors = _activation_settings_step(
            user_input,
            self._reconfigure_feature_data,
        )
        if setting_errors:
            return _activation_manage_form(
                self.async_show_form,
                step_id="reconfigure_device_activations",
                items=self._reconfigure_device_activations,
                feature_data=self._reconfigure_feature_data,
                errors=setting_errors,
            )

        result = _activation_manage_step(
            user_input,
            self._reconfigure_device_activations,
            max_items=_activation_item_limit(self._reconfigure_feature_data),
        )
        self._reconfigure_device_activations = result.items
        self._reconfigure_activation_edit_id = result.edit_id
        if result.next_step == _ACTIVATION_STEP_DONE:
            self._reconfigure_feature_data[CONF_DEVICE_ACTIVATIONS] = list(result.items)
            return await self.async_step_reconfigure_dashboard()
        if result.next_step == _ACTIVATION_STEP_ITEM:
            return _activation_item_form(
                self.async_show_form,
                step_id="reconfigure_device_activation_item",
                items=result.items,
                edit_id=result.edit_id,
                errors=result.errors,
            )

        return _activation_manage_form(
            self.async_show_form,
            step_id="reconfigure_device_activations",
            items=result.items,
            feature_data=self._reconfigure_feature_data,
            errors=result.errors,
        )

    async def async_step_reconfigure_device_activation_item(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add or edit one C300X device activation during reconfigure."""

        if not self._reconfigure_feature_data:
            return await self.async_step_reconfigure_features()

        result = _activation_item_step(
            user_input,
            self._reconfigure_device_activations,
            self._reconfigure_activation_edit_id,
            self._reconfigure_feature_data,
        )
        self._reconfigure_device_activations = result.items
        self._reconfigure_activation_edit_id = result.edit_id
        if result.next_step != _ACTIVATION_STEP_ITEM:
            return await self.async_step_reconfigure_device_activations()

        return _activation_item_form(
            self.async_show_form,
            step_id="reconfigure_device_activation_item",
            items=result.items,
            edit_id=result.edit_id,
            errors=result.errors,
        )

    async def async_step_reconfigure_dashboard(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Reconfigure C300X display dashboard settings."""

        entry = self._get_reconfigure_entry()
        feature_defaults = _current_feature_options(entry)
        if not self._reconfigure_feature_data:
            return await self.async_step_reconfigure_features()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._reconfigure_dashboard_input = _dashboard_input_defaults(
                user_input,
                feature_defaults,
            )
            if (
                self._reconfigure_dashboard_input[CONF_DEVICE_UI_ENABLED]
                and self._reconfigure_dashboard_input[CONF_DASHBOARD_ENTITIES]
            ):
                return await self._async_show_reconfigure_dashboard_entity_display_form(
                    None,
                    feature_defaults,
                    errors,
                )
            return await self._async_finish_reconfigure_from_dashboard(
                feature_defaults,
                errors,
            )

        return await self._async_show_reconfigure_dashboard_form(
            user_input,
            feature_defaults,
            errors,
        )

    async def async_step_reconfigure_dashboard_entity_display(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Reconfigure per-entity C300X display dashboard labels."""

        entry = self._get_reconfigure_entry()
        feature_defaults = _current_feature_options(entry)
        if not self._reconfigure_dashboard_input:
            return await self.async_step_reconfigure_dashboard()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _dashboard_entity_display_form_complete(
                user_input,
                self._reconfigure_dashboard_input[CONF_DASHBOARD_ENTITIES],
            ):
                return await self._async_show_reconfigure_dashboard_entity_display_form(
                    user_input,
                    feature_defaults,
                    errors,
                )
            self._reconfigure_dashboard_input[
                CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES
            ] = _dashboard_input_defaults(
                {
                    **self._reconfigure_dashboard_input,
                    **user_input,
                },
                feature_defaults,
            )[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]
            return await self._async_finish_reconfigure_from_dashboard(
                feature_defaults,
                errors,
            )
        return await self._async_show_reconfigure_dashboard_entity_display_form(
            user_input,
            feature_defaults,
            errors,
        )

    async def _async_finish_reconfigure_from_dashboard(
        self,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Finish reconfigure from collected dashboard pages."""

        feature_data, errors = _feature_input(
            {**self._reconfigure_feature_data, **self._reconfigure_dashboard_input}
        )
        if errors:
            return await self._async_show_reconfigure_dashboard_form(
                self._reconfigure_dashboard_input,
                feature_defaults,
                errors,
            )
        return await self._async_finish_reconfigure(feature_data)

    async def _async_show_reconfigure_dashboard_form(
        self,
        user_input: dict[str, Any] | None,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Show reconfigure C300X display dashboard settings."""

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure_dashboard",
            data_schema=_dashboard_schema(
                str(
                    (user_input or {}).get(
                        CONF_ALARM_ENTITY_ID,
                        feature_defaults[CONF_ALARM_ENTITY_ID],
                    )
                ),
                str(
                    (user_input or {}).get(
                        CONF_WEATHER_ENTITY_ID,
                        feature_defaults[CONF_WEATHER_ENTITY_ID],
                    )
                ),
                str(
                    (user_input or {}).get(
                        CONF_ACTIONS_JSON,
                        _actions_json(feature_defaults[CONF_ACTIONS]),
                    )
                ),
                bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_PREVENT_RETURN,
                        feature_defaults[CONF_DASHBOARD_PREVENT_RETURN],
                    )
                ),
                (user_input or {}).get(
                    CONF_DASHBOARD_ENTITIES,
                    feature_defaults[CONF_DASHBOARD_ENTITIES],
                ),
                (user_input or {}).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    feature_defaults[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES],
                ),
                default_dashboard_dynamic_homepage=bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                        feature_defaults[CONF_DASHBOARD_DYNAMIC_HOMEPAGE],
                    )
                ),
                default_alarm_page_entity=str(
                    (user_input or {}).get(
                        CONF_ALARM_PAGE_ENTITY_ID,
                        feature_defaults.get(CONF_ALARM_PAGE_ENTITY_ID, ""),
                    )
                ),
                default_device_ui_enabled=bool(
                    (user_input or {}).get(
                        CONF_DEVICE_UI_ENABLED,
                        feature_defaults[CONF_DEVICE_UI_ENABLED],
                    )
                ),
            ),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                entry
            ),
        )

    async def _async_show_reconfigure_dashboard_entity_display_form(
        self,
        user_input: dict[str, Any] | None,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Show reconfigure per-entity C300X display dashboard settings."""

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure_dashboard_entity_display",
            data_schema=_dashboard_entity_display_schema(
                self._reconfigure_dashboard_input.get(CONF_DASHBOARD_ENTITIES, []),
                (user_input or self._reconfigure_dashboard_input).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    feature_defaults[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES],
                ),
            ),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                entry
            ),
        )

    async def _async_finish_reconfigure(
        self,
        feature_data: dict[str, Any],
    ) -> FlowResult:
        """Finish a reconfigure flow after all feature pages."""

        entry = self._get_reconfigure_entry()
        await self.async_set_unique_id(_reconfigure_unique_id(entry))
        self._abort_if_unique_id_mismatch()

        rotate = bool(self._reconfigure_connection.pop(CONF_ROTATE_SHARED_SECRET))
        data_updates = {**self._reconfigure_connection, **feature_data}
        if rotate:
            data_updates[CONF_SHARED_SECRET] = secrets.token_urlsafe(32)
            data_updates[CONF_EVENT_WEBHOOK_TOKEN] = secrets.token_urlsafe(32)

        _clear_reconfigured_option_overrides(self.hass, entry, data_updates)
        return self.async_update_and_abort(entry, data_updates=data_updates)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: BticinoC300XConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""

        return BticinoC300XOptionsFlow(config_entry)


class BticinoC300XOptionsFlow(config_entries.OptionsFlow):
    """Handle C300X options."""

    def __init__(self, config_entry: BticinoC300XConfigEntry) -> None:
        self._config_entry = config_entry
        self._connection_options: dict[str, Any] = {}
        self._feature_options: dict[str, Any] = {}
        self._device_activations: list[dict[str, Any]] = []
        self._activation_edit_id: str | None = None
        self._dashboard_options: dict[str, Any] = {}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Start the two-page options flow."""

        return await self.async_step_connection(user_input)

    async def async_step_connection(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
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
    ) -> FlowResult:
        """Manage integration media and display feature options."""

        if not self._connection_options:
            self._connection_options = _current_connection_options(self._config_entry)

        errors: dict[str, str] = {}
        if user_input is not None:
            feature_defaults = _current_feature_options(self._config_entry)
            feature_input = _feature_input_defaults(user_input, feature_defaults)
            feature_data, errors = _feature_input(feature_input)
            if errors:
                return self.async_show_form(
                    step_id="features",
                    data_schema=_options_features_schema(
                        self._config_entry,
                        video_enabled=bool(user_input.get(CONF_VIDEO_ENABLED, False)),
                        create_homeassistant_user=bool(
                            user_input.get(
                                CONF_CREATE_HOMEASSISTANT_USER,
                                _CREATE_HOMEASSISTANT_USER_DEFAULT,
                            )
                        ),
                        webrtc_ice_policy=_webrtc_ice_policy_or_default(
                            user_input.get(
                                CONF_WEBRTC_ICE_POLICY,
                                feature_defaults[CONF_WEBRTC_ICE_POLICY],
                            )
                        ),
                    ),
                    errors=errors,
                    description_placeholders=(
                        await _async_qml_patch_description_placeholders(
                            self._config_entry
                        )
                    ),
            )
            self._feature_options = feature_data
            self._device_activations = _activation_items_from_feature_data(
                feature_data
            )
            return await self.async_step_device_activations()

        return self.async_show_form(
            step_id="features",
            data_schema=_options_features_schema(self._config_entry),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                self._config_entry
            ),
        )

    async def async_step_device_activations(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage additional C300X device activations in the options flow."""

        if not self._feature_options:
            return await self.async_step_features()

        self._feature_options, setting_errors = _activation_settings_step(
            user_input,
            self._feature_options,
        )
        if setting_errors:
            return _activation_manage_form(
                self.async_show_form,
                step_id="device_activations",
                items=self._device_activations,
                feature_data=self._feature_options,
                errors=setting_errors,
            )

        result = _activation_manage_step(
            user_input,
            self._device_activations,
            max_items=_activation_item_limit(self._feature_options),
        )
        self._device_activations = result.items
        self._activation_edit_id = result.edit_id
        if result.next_step == _ACTIVATION_STEP_DONE:
            self._feature_options[CONF_DEVICE_ACTIVATIONS] = list(result.items)
            return await self.async_step_dashboard()
        if result.next_step == _ACTIVATION_STEP_ITEM:
            return _activation_item_form(
                self.async_show_form,
                step_id="device_activation_item",
                items=result.items,
                edit_id=result.edit_id,
                errors=result.errors,
            )

        return _activation_manage_form(
            self.async_show_form,
            step_id="device_activations",
            items=result.items,
            feature_data=self._feature_options,
            errors=result.errors,
        )

    async def async_step_device_activation_item(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add or edit one C300X device activation in the options flow."""

        if not self._feature_options:
            return await self.async_step_features()

        result = _activation_item_step(
            user_input,
            self._device_activations,
            self._activation_edit_id,
            self._feature_options,
        )
        self._device_activations = result.items
        self._activation_edit_id = result.edit_id
        if result.next_step != _ACTIVATION_STEP_ITEM:
            return await self.async_step_device_activations()

        return _activation_item_form(
            self.async_show_form,
            step_id="device_activation_item",
            items=result.items,
            edit_id=result.edit_id,
            errors=result.errors,
        )

    async def async_step_dashboard(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage C300X display dashboard options."""

        feature_defaults = _current_feature_options(self._config_entry)
        if not self._feature_options:
            return await self.async_step_features()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._dashboard_options = _dashboard_input_defaults(
                user_input,
                feature_defaults,
            )
            if (
                self._dashboard_options[CONF_DEVICE_UI_ENABLED]
                and self._dashboard_options[CONF_DASHBOARD_ENTITIES]
            ):
                return await self._async_show_options_dashboard_entity_display_form(
                    None,
                    feature_defaults,
                    errors,
                )
            return await self._async_create_options_entry_from_dashboard(
                feature_defaults,
                errors,
            )

        return await self._async_show_options_dashboard_form(
            user_input,
            feature_defaults,
            errors,
        )

    async def async_step_dashboard_entity_display(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage per-entity display labels for C300X dashboard options."""

        feature_defaults = _current_feature_options(self._config_entry)
        if not self._dashboard_options:
            return await self.async_step_dashboard()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _dashboard_entity_display_form_complete(
                user_input,
                self._dashboard_options[CONF_DASHBOARD_ENTITIES],
            ):
                return await self._async_show_options_dashboard_entity_display_form(
                    user_input,
                    feature_defaults,
                    errors,
                )
            self._dashboard_options[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES] = (
                _dashboard_input_defaults(
                    {
                        **self._dashboard_options,
                        **user_input,
                    },
                    feature_defaults,
                )[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES]
            )
            return await self._async_create_options_entry_from_dashboard(
                feature_defaults,
                errors,
            )
        return await self._async_show_options_dashboard_entity_display_form(
            user_input,
            feature_defaults,
            errors,
        )

    async def _async_create_options_entry_from_dashboard(
        self,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Create the options entry from collected dashboard pages."""

        feature_data, errors = _feature_input(
            {**self._feature_options, **self._dashboard_options}
        )
        if errors:
            return await self._async_show_options_dashboard_form(
                self._dashboard_options,
                feature_defaults,
                errors,
            )
        return self.async_create_entry(
            title="",
            data={
                **self._connection_options,
                **feature_data,
            },
        )

    async def _async_show_options_dashboard_form(
        self,
        user_input: dict[str, Any] | None,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Show options C300X display dashboard settings."""

        return self.async_show_form(
            step_id="dashboard",
            data_schema=_dashboard_schema(
                str(
                    (user_input or {}).get(
                        CONF_ALARM_ENTITY_ID,
                        feature_defaults[CONF_ALARM_ENTITY_ID],
                    )
                ),
                str(
                    (user_input or {}).get(
                        CONF_WEATHER_ENTITY_ID,
                        feature_defaults[CONF_WEATHER_ENTITY_ID],
                    )
                ),
                str(
                    (user_input or {}).get(
                        CONF_ACTIONS_JSON,
                        _actions_json(feature_defaults[CONF_ACTIONS]),
                    )
                ),
                bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_PREVENT_RETURN,
                        feature_defaults[CONF_DASHBOARD_PREVENT_RETURN],
                    )
                ),
                (user_input or {}).get(
                    CONF_DASHBOARD_ENTITIES,
                    feature_defaults[CONF_DASHBOARD_ENTITIES],
                ),
                (user_input or {}).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    feature_defaults[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES],
                ),
                default_dashboard_dynamic_homepage=bool(
                    (user_input or {}).get(
                        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                        feature_defaults[CONF_DASHBOARD_DYNAMIC_HOMEPAGE],
                    )
                ),
                default_alarm_page_entity=str(
                    (user_input or {}).get(
                        CONF_ALARM_PAGE_ENTITY_ID,
                        feature_defaults.get(CONF_ALARM_PAGE_ENTITY_ID, ""),
                    )
                ),
                default_device_ui_enabled=bool(
                    (user_input or {}).get(
                        CONF_DEVICE_UI_ENABLED,
                        feature_defaults[CONF_DEVICE_UI_ENABLED],
                    )
                ),
            ),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                self._config_entry
            ),
        )

    async def _async_show_options_dashboard_entity_display_form(
        self,
        user_input: dict[str, Any] | None,
        feature_defaults: dict[str, Any],
        errors: dict[str, str],
    ) -> FlowResult:
        """Show options per-entity C300X display dashboard settings."""

        return self.async_show_form(
            step_id="dashboard_entity_display",
            data_schema=_dashboard_entity_display_schema(
                self._dashboard_options.get(CONF_DASHBOARD_ENTITIES, []),
                (user_input or self._dashboard_options).get(
                    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
                    feature_defaults[CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES],
                ),
            ),
            errors=errors,
            description_placeholders=await _async_qml_patch_description_placeholders(
                self._config_entry
            ),
        )


def _reconfigure_unique_id(entry: BticinoC300XConfigEntry) -> str:
    """Return the existing entry unique id for reconfigure flows."""

    return str(getattr(entry, "unique_id", None) or DOMAIN)


def _manual_setup_unique_id(connection: dict[str, Any]) -> str:
    """Return a deterministic unique id for manual setup flows."""

    host = _normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    port = int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    return f"{DOMAIN}:{host}:{port}" if host else DOMAIN


def _entry_uses_manual_setup_unique_id(
    config_entry: BticinoC300XConfigEntry,
) -> bool:
    """Return true when an existing entry still uses the host-based setup ID."""

    unique_id = str(getattr(config_entry, "unique_id", "") or "")
    return unique_id == DOMAIN or unique_id.startswith(f"{DOMAIN}:")


async def _async_discovery_targets_configured_entry(
    hass: Any,
    config_entry: BticinoC300XConfigEntry,
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
    config_entry: BticinoC300XConfigEntry,
    connection: dict[str, Any],
) -> bool:
    """Return true when host and port already match the discovery endpoint."""

    entry_host = _normalize_discovery_host(
        str(_config_default(config_entry, CONF_AGENT_HOST, "") or "")
    )
    discovery_host = _normalize_discovery_host(str(connection.get(CONF_AGENT_HOST, "")))
    if not entry_host or entry_host != discovery_host:
        return False
    return int(
        _config_default(config_entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
    ) == int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))


def _normalize_discovery_host(host: str) -> str:
    """Normalize a host name for local discovery comparisons."""

    return host.strip().lower().rstrip(".")


async def _async_probe_agent(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> str:
    """Return reachable, auth_required, or missing for the setup agent probe."""

    try:
        await _async_agent_ready_for_setup(hass, connection, api_token=api_token)
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
    )
    api = C300XAgentApi(async_get_clientsession(hass), base_url, api_token)
    return cast(dict[str, Any], await api.async_validate_setup())


async def _async_agent_ready_for_setup(
    hass: Any,
    connection: dict[str, Any],
    *,
    api_token: str = "",
) -> dict[str, Any]:
    """Validate the agent endpoints required for a usable config entry."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    base_url = build_agent_base_url(
        str(connection.get(CONF_AGENT_HOST, "")),
        int(connection.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
    )
    api = C300XAgentApi(async_get_clientsession(hass), base_url, api_token)
    setup_data = cast(dict[str, Any], await api.async_validate_setup())
    try:
        await api.async_self_test()
    except C300XAgentApiUnsupportedError:
        pass
    except C300XAgentApiError:
        pass
    await api.async_list_event_subscriptions()
    return setup_data


def _stable_unique_id_from_setup_data(setup_data: dict[str, Any]) -> str | None:
    """Return the normalized config-entry unique ID from agent setup data."""

    from .discovery import discovery_unique_id

    device_id = setup_data.get("device_id")
    return discovery_unique_id({"id": device_id}) if device_id else None


def _clear_reconfigured_option_overrides(
    hass: Any,
    config_entry: BticinoC300XConfigEntry,
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
    config_entry: BticinoC300XConfigEntry,
    key: str,
    default: Any,
) -> Any:
    """Return an option override when present, otherwise setup data."""

    return entry_config_value(config_entry, key, default)


async def _async_qml_patch_description_placeholders(
    config_entry: BticinoC300XConfigEntry,
) -> dict[str, str]:
    """Return placeholders for the device Display patch status."""

    return {
        "qml_patch_status": _qml_patch_status_label(
            await _async_qml_patch_status(config_entry)
        )
    }


async def _async_qml_patch_status(
    config_entry: BticinoC300XConfigEntry,
) -> dict[str, Any]:
    """Return cached Display patch status, refreshing it only when useful."""

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
    return cast(dict[str, Any], status)


def _qml_patch_status_label(status: dict[str, Any]) -> str:
    """Return a concise, user-visible Display patch status label."""

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
