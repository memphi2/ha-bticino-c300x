"""Config-entry runtime lifecycle for BTicino C300X."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .activation_address import stair_light_where_from_entry_values
from .api import (
    C300XAgentApi,
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
    build_agent_base_url,
    display_bridge_callback_fingerprint,
)
from .capabilities import (
    capability_is_supported,
    entry_device_ui_enabled,
    maintenance_action_is_advertised,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_UI_ENABLED,
    CONF_EVENT_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_TOKEN,
    CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED,
    CONF_MAINTENANCE_TOKEN,
    CONF_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_WEBHOOK_ID,
    DATA_RUNTIME_ENTRIES,
    DEFAULT_AGENT_PORT,
    DEFAULT_RECONNECT_GRACE_SECONDS,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
    DOMAIN,
    SIGNAL_CONNECTION_STATE_CHANGED,
)
from .data import BticinoC300XRuntimeData, C300XConnectionState, C300XEventState
from .device_activations import (
    activation_items_match,
    desired_activation_items,
)
from .device_user import (
    device_user_bootstrap_needed,
    device_user_bootstrap_satisfied,
    homeassistant_account_label,
)
from .entry_config import entry_config_value as _entry_config_value
from .entry_types import BticinoC300XConfigEntry
from .error_text import compact_error_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

BASE_PLATFORMS = (
    "binary_sensor",
    "button",
    "event",
    "number",
    "sensor",
    "select",
    "switch",
)
CAMERA_PLATFORM = "camera"
_LOGGER = logging.getLogger(__name__)
_GUI_DEPENDENT_ENTITY_KEYS = (
    ("button", "delete_latest_video_message"),
    ("button", "delete_latest_text_memo"),
    ("button", "delete_latest_voice_memo"),
)


class C300XRuntimeManager:
    """Own the lifecycle orchestration for one C300X config entry."""

    def __init__(self, hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
        """Initialize the runtime manager."""

        self.hass = hass
        self.entry = entry
        self.api: C300XAgentApi | None = None
        self.event_state = C300XEventState()
        self.connection_state = C300XConnectionState()
        self.setup_data: Mapping[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self.agent_update_state: Any | None = None
        self.unregister_webhook: Callable[[], None] | None = None
        self.unregister_event_webhook: Callable[[], None] | None = None
        self.unregister_event_registration: Callable[[], None] | None = None
        self.on_runtime_registration_created: Callable[[], Any] | None = None
        self.platforms: tuple[str, ...] = BASE_PLATFORMS

    async def async_prepare(self) -> bool:
        """Prepare runtime data and finish Home Assistant setup."""

        self.hass.data.setdefault(DOMAIN, {})
        if not self._required_config_present():
            return False

        self.api = self._build_agent_api()
        await self.async_validate_agent()
        await self.async_register_callbacks()
        self._store_runtime_data()
        _async_remove_stale_gui_dependent_entities(self.hass, self.entry)

        from .repair_issues import async_sync_entry_repair_issues
        from .services import async_setup_services

        async_sync_entry_repair_issues(self.hass, self.entry)
        self.entry.async_on_unload(self.entry.add_update_listener(_async_update_listener))
        await async_setup_services(self.hass)
        await self.async_forward_platforms()
        self.async_schedule_startup_sync()
        return True

    async def async_validate_agent(self) -> None:
        """Validate the device-agent setup state and derive capabilities."""

        from .agent_update import (
            async_load_packaged_bundle_metadata,
            compare_agent_bundle,
        )
        from .capabilities import gate_capabilities

        api = self._api()
        try:
            self.setup_data = await api.async_validate_setup()
        except C300XAgentApiError as err:
            _LOGGER.info("C300X device agent is offline during setup: %s", err)
            self.setup_data = _offline_setup_data(err)
            self.capabilities = {}
            self.connection_state.mark_reconnecting(
                type(err).__name__,
                DEFAULT_RECONNECT_GRACE_SECONDS,
                compact_error_text(err),
            )
            self.connection_state.mark_unavailable()
            self.unregister_event_registration = _async_start_setup_recovery(
                self.hass,
                self.entry,
                api,
                self.connection_state,
            )
        else:
            capabilities = self.setup_data.get("capabilities", {})
            if not isinstance(capabilities, dict):
                capabilities = {}
            self.capabilities = gate_capabilities(
                capabilities,
                doorbell_video_enabled=_entry_video_enabled(self.entry),
            )

        if self.connection_state.available:
            self.agent_update_state = compare_agent_bundle(
                self.setup_data,
                await async_load_packaged_bundle_metadata(self.hass),
            )

    async def async_register_callbacks(self) -> None:
        """Register webhooks and runtime callbacks for the entry."""

        from .events import async_start_agent_event_registration
        from .webhook import (
            async_register_agent_event_webhook,
            async_register_webhook,
        )

        api = self._api()
        self.unregister_webhook = async_register_webhook(self.hass, self.entry)
        self.unregister_event_webhook = async_register_agent_event_webhook(
            self.hass,
            self.entry,
            self.event_state,
        )

        async def _async_refresh_runtime_registration() -> None:
            await _async_configure_display_bridge(self.hass, self.entry, api)

        self.on_runtime_registration_created = _async_refresh_runtime_registration
        if self.unregister_event_registration is None:
            self.unregister_event_registration = await async_start_agent_event_registration(
                self.hass,
                self.entry,
                api,
                self.capabilities,
                self.connection_state,
                on_runtime_registration_created=_async_refresh_runtime_registration,
            )

    async def async_sync_device_state(self) -> None:
        """Synchronize startup-only runtime state with the device agent."""

        self.entry.runtime_data.unregister_display_bridge_updates = (
            _async_track_display_bridge_updates(self.hass, self.entry)
        )
        if not self.connection_state.available:
            return

        api = self._api()
        await _async_configure_device_activations(self.entry, api)
        await _async_configure_display_bridge(self.hass, self.entry, api)
        await _async_sync_device_ui_patch(self.entry)
        await _async_sync_device_user(self.hass, self.entry)
        await _async_refresh_self_test(self.entry)

    def async_schedule_startup_sync(self) -> None:
        """Run slow startup-only agent synchronization after entity setup."""

        from .repair_issues import async_sync_entry_repair_issues

        async def _async_run_startup_sync() -> None:
            sync_repairs = False
            try:
                await self.async_sync_device_state()
                sync_repairs = True
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep entry setup available
                _LOGGER.warning(
                    "C300X startup device-state sync failed after setup: %s",
                    compact_error_text(err),
                )
                sync_repairs = True
            finally:
                if sync_repairs:
                    async_sync_entry_repair_issues(self.hass, self.entry)
                self.entry.runtime_data.startup_sync_task = None

        create_task = getattr(self.hass, "async_create_task", None)
        task = (
            create_task(_async_run_startup_sync())
            if callable(create_task)
            else asyncio.create_task(_async_run_startup_sync())
        )
        self.entry.runtime_data.startup_sync_task = task

    async def async_forward_platforms(self) -> None:
        """Set up media routes and forward entity platforms."""

        from .media import async_setup_media_view

        async_setup_media_view(self.hass)
        await self.hass.config_entries.async_forward_entry_setups(
            self.entry,
            self.platforms,
        )

    async def async_unload(self) -> bool:
        """Unload platforms and runtime callbacks for the entry."""

        runtime_data = self.entry.runtime_data
        unload_ok = await self.hass.config_entries.async_unload_platforms(
            self.entry,
            runtime_data.loaded_platforms,
        )
        if unload_ok:
            if runtime_data.unregister_event_registration:
                runtime_data.unregister_event_registration()
            if runtime_data.unregister_display_bridge_updates:
                runtime_data.unregister_display_bridge_updates()
            if runtime_data.connection_state.expire_unavailable:
                runtime_data.connection_state.expire_unavailable()
            if runtime_data.memos_refresh_task:
                runtime_data.memos_refresh_task.cancel()
                runtime_data.memos_refresh_task = None
            if runtime_data.answering_machine_messages_refresh_task:
                runtime_data.answering_machine_messages_refresh_task.cancel()
                runtime_data.answering_machine_messages_refresh_task = None
            startup_sync_task = getattr(runtime_data, "startup_sync_task", None)
            if startup_sync_task:
                startup_sync_task.cancel()
                runtime_data.startup_sync_task = None
            runtime_data.unregister_event_webhook()
            runtime_data.unregister_webhook()
            self.hass.data.get(DOMAIN, {}).get(DATA_RUNTIME_ENTRIES, {}).pop(
                self.entry.entry_id,
                None,
            )
        return unload_ok

    def _build_agent_api(self) -> C300XAgentApi:
        """Build the device-agent API client for this entry."""

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        agent_host = str(_entry_config_value(self.entry, CONF_AGENT_HOST, "")).strip()
        base_url = build_agent_base_url(
            agent_host,
            int(_entry_config_value(self.entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
        )
        return C300XAgentApi(
            async_get_clientsession(self.hass),
            base_url,
            str(_entry_config_value(self.entry, CONF_AGENT_TOKEN, "")),
            str(_entry_config_value(self.entry, CONF_MAINTENANCE_TOKEN, "")),
        )

    def _required_config_present(self) -> bool:
        """Return whether the migrated entry contains all setup secrets."""

        required = (
            CONF_AGENT_HOST,
            CONF_WEBHOOK_ID,
            CONF_SHARED_SECRET,
            CONF_EVENT_WEBHOOK_ID,
            CONF_EVENT_WEBHOOK_TOKEN,
        )
        missing_required = tuple(
            key for key in required if not _entry_config_value(self.entry, key)
        )
        if not missing_required:
            return True

        _LOGGER.error(
            "C300X config entry is missing required setup field(s): %s",
            ", ".join(missing_required),
        )
        return False

    def _store_runtime_data(self) -> None:
        """Attach runtime data to the entry and domain registry."""

        self.platforms = _entry_platforms(self.entry, self.capabilities)
        self.entry.runtime_data = BticinoC300XRuntimeData(
            api=self._api(),
            event_state=self.event_state,
            connection_state=self.connection_state,
            capabilities=self.capabilities,
            agent_info=self.setup_data,
            unregister_webhook=self._unregister_webhook(),
            unregister_event_webhook=self._unregister_event_webhook(),
            unregister_event_registration=self.unregister_event_registration,
            on_runtime_registration_created=self.on_runtime_registration_created,
            unregister_display_bridge_updates=None,
            loaded_platforms=self.platforms,
            agent_update_state=self.agent_update_state,
        )
        self.hass.data.setdefault(DOMAIN, {}).setdefault(DATA_RUNTIME_ENTRIES, {})[
            self.entry.entry_id
        ] = self.entry.runtime_data

    def _api(self) -> C300XAgentApi:
        """Return the initialized API client."""

        if self.api is None:
            raise RuntimeError("C300X runtime API is not initialized")
        return self.api

    def _unregister_webhook(self) -> Callable[[], None]:
        """Return the registered main-webhook unsubscriber."""

        if self.unregister_webhook is None:
            raise RuntimeError("C300X runtime webhook is not registered")
        return self.unregister_webhook

    def _unregister_event_webhook(self) -> Callable[[], None]:
        """Return the registered event-webhook unsubscriber."""

        if self.unregister_event_webhook is None:
            raise RuntimeError("C300X runtime event webhook is not registered")
        return self.unregister_event_webhook


async def _async_update_listener(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Reload when options change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _async_remove_stale_gui_dependent_entities(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Remove stale HA entities for C300X GUI functions that are currently gated."""

    if entry_device_ui_enabled(entry):
        return

    import homeassistant.helpers.entity_registry as er

    registry = er.async_get(hass)
    states = getattr(hass, "states", None)
    for platform, key in _GUI_DEPENDENT_ENTITY_KEYS:
        entity_id = registry.async_get_entity_id(
            platform,
            DOMAIN,
            f"{entry.entry_id}_{key}",
        )
        if entity_id is None:
            continue
        registry.async_remove(entity_id)
        if states is not None and hasattr(states, "async_remove"):
            states.async_remove(entity_id)


def _entry_platforms(
    entry: BticinoC300XConfigEntry,
    capabilities: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Return platforms enabled for this config entry."""

    if _entry_video_enabled(entry) and capability_is_supported(
        capabilities or {},
        "doorbell_video",
    ):
        return (*BASE_PLATFORMS, CAMERA_PLATFORM)
    return BASE_PLATFORMS


def _offline_setup_data(err: Exception) -> dict[str, Any]:
    """Return minimal agent metadata for a non-blocking offline setup."""

    return {
        "version": None,
        "implementation": None,
        "api_version": None,
        "model": None,
        "firmware": None,
        "capabilities": {},
        "offline_error": compact_error_text(err),
    }


def _async_start_setup_recovery(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    api: C300XAgentApi,
    connection_state: C300XConnectionState,
) -> Any:
    """Reload the entry once an agent that was offline during setup returns."""

    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from homeassistant.helpers.event import async_call_later

    stopped = False
    retry_cancel = None
    retry_delay_seconds = DEFAULT_RECONNECT_GRACE_SECONDS

    async def _retry(now: Any = None) -> None:
        nonlocal retry_cancel, retry_delay_seconds
        if stopped:
            return
        retry_cancel = None
        try:
            await api.async_validate_setup()
        except C300XAgentApiError as err:
            connection_state.mark_reconnecting(
                type(err).__name__,
                retry_delay_seconds,
                compact_error_text(err),
            )
            connection_state.mark_unavailable()
            async_dispatcher_send(
                hass,
                SIGNAL_CONNECTION_STATE_CHANGED,
                entry.entry_id,
            )
            retry_cancel = async_call_later(hass, retry_delay_seconds, _retry)
            retry_delay_seconds = min(300, retry_delay_seconds * 2)
            return
        await hass.config_entries.async_reload(entry.entry_id)

    retry_cancel = async_call_later(hass, retry_delay_seconds, _retry)

    def _cancel() -> None:
        nonlocal stopped
        stopped = True
        if retry_cancel is not None:
            retry_cancel()

    return _cancel


def _entry_video_enabled(entry: BticinoC300XConfigEntry) -> bool:
    """Return the effective HA video setting for this entry."""

    return bool(_entry_config_value(entry, CONF_VIDEO_ENABLED, False))


async def _async_sync_device_ui_patch(entry: BticinoC300XConfigEntry) -> None:
    """Refresh Display patch status without mutating the device."""

    from .qml_patch import async_refresh_qml_patch_status

    capabilities = getattr(entry.runtime_data, "capabilities", {})
    diagnostics = entry.runtime_data.qml_patch_diagnostics
    try:
        if maintenance_action_is_advertised(capabilities, "qml_status"):
            diagnostics.mark_attempt(datetime.now(UTC))
            status = await async_refresh_qml_patch_status(entry)
            diagnostics.mark_success(datetime.now(UTC))
        else:
            status = {}
        entry.runtime_data.qml_patch_status = status
    except C300XAgentApiError as err:
        error = compact_error_text(err)
        diagnostics.mark_failure(error, datetime.now(UTC))
        _LOGGER.warning("C300X Display patch status sync failed: %s", error)
        return


async def _async_sync_device_user(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Bootstrap once, then refresh the Flexisip user status read-only."""

    if not _entry_video_enabled(entry):
        return
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not capability_is_supported(capabilities, "device_user"):
        return
    try:
        status = await entry.runtime_data.api.async_device_user_status()
        if _device_user_bootstrap_allowed(entry, status):
            status = await entry.runtime_data.api.async_ensure_homeassistant_user(
                account_label=homeassistant_account_label(hass),
            )
            if device_user_bootstrap_satisfied(status):
                _mark_homeassistant_media_user_bootstrapped(hass, entry)
        elif device_user_bootstrap_satisfied(status):
            _mark_homeassistant_media_user_bootstrapped(hass, entry)
        entry.runtime_data.device_user_status = status
        entry.runtime_data.device_user_status_updated_at = datetime.now(UTC)
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support device-user status")
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X device-user status sync failed: %s",
            compact_error_text(err),
        )


def _device_user_bootstrap_allowed(
    entry: BticinoC300XConfigEntry,
    status: dict[str, Any],
) -> bool:
    """Return true when startup may perform the one-time media-user bootstrap."""

    return (
        bool(_entry_config_value(entry, CONF_CREATE_HOMEASSISTANT_USER, False))
        and not bool(
            _entry_config_value(entry, CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED, False)
        )
        and device_user_bootstrap_needed(status)
    )


def _mark_homeassistant_media_user_bootstrapped(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Persist that startup must no longer auto-write media-user files."""

    if _entry_config_value(entry, CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED, False):
        return
    data = dict(entry.data)
    data[CONF_HOMEASSISTANT_MEDIA_USER_BOOTSTRAPPED] = True
    hass.config_entries.async_update_entry(entry, data=data)


async def _async_refresh_device_user_status(
    entry: BticinoC300XConfigEntry,
) -> None:
    """Refresh the dedicated HA media-user status without mutating the device."""

    if not _entry_video_enabled(entry):
        return
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    if not capability_is_supported(capabilities, "device_user"):
        return
    try:
        entry.runtime_data.device_user_status = (
            await entry.runtime_data.api.async_device_user_status()
        )
        entry.runtime_data.device_user_status_updated_at = datetime.now(UTC)
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support device-user status")
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X device-user status refresh failed: %s",
            compact_error_text(err),
        )


async def _async_refresh_self_test(entry: BticinoC300XConfigEntry) -> None:
    """Refresh the read-only device-agent architecture self-test."""

    try:
        entry.runtime_data.self_test_status = await entry.runtime_data.api.async_self_test()
        entry.runtime_data.self_test_status_updated_at = datetime.now(UTC)
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support self-test status")
        entry.runtime_data.self_test_status = {}
        entry.runtime_data.self_test_status_updated_at = None
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X device-agent self-test failed: %s",
            compact_error_text(err),
        )


async def _async_configure_device_activations(
    entry: BticinoC300XConfigEntry,
    api: C300XAgentApi,
) -> None:
    """Synchronize configured C300X activation discovery with the native agent."""

    enabled, auto_discover, items = _entry_activation_config(entry)
    try:
        status = await api.async_auth_config_status()
        current_enabled = status.get("activations_enabled")
        current_auto_discover = status.get("activations_auto_discover")
        if current_enabled is None or current_auto_discover is None:
            return
        if (
            current_enabled is enabled
            and current_auto_discover is auto_discover
            and await _async_device_activation_items_match(api, items)
        ):
            return
        await api.async_configure_device_activations(
            enabled=enabled,
            auto_discover=auto_discover,
            items=items,
        )
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support activation configuration")
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X activation configuration sync failed: %s",
            compact_error_text(err),
        )


async def _async_device_activation_items_match(
    api: C300XAgentApi,
    desired_items: list[dict[str, Any]],
) -> bool:
    """Return true when the agent already reports the desired configured items."""

    try:
        activations = await api.async_activations()
    except C300XAgentApiError:
        return False
    items = activations.get("items")
    if not isinstance(items, list):
        return False
    configured_items = [
        item
        for item in items
        if isinstance(item, dict) and item.get("source") == "config"
    ]
    return activation_items_match(desired_items, configured_items)


def _entry_activation_config(
    entry: BticinoC300XConfigEntry,
) -> tuple[bool, bool, list[dict[str, Any]]]:
    """Return the desired native-agent activation configuration."""

    mode = str(
        _entry_config_value(
            entry,
            CONF_DEVICE_ACTIVATION_MODE,
            DEVICE_ACTIVATION_MODE_AUTO,
        )
    ).strip()
    auto_discover = mode != DEVICE_ACTIVATION_MODE_MANUAL
    p_value = _entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, "")
    n_value = _entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, "")
    address = stair_light_where_from_entry_values(p_value, n_value)
    items = desired_activation_items(
        mode=mode,
        stair_light_address=address,
        device_activations=_entry_config_value(entry, CONF_DEVICE_ACTIVATIONS, []),
    )
    return True, auto_discover, items


async def _async_configure_display_bridge(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
    api: C300XAgentApi,
) -> None:
    """Register the HA display-bridge webhook with the running device agent."""

    from .callback_url import async_generate_agent_callback_url

    enabled = bool(_entry_config_value(entry, CONF_DEVICE_UI_ENABLED, False))
    webhook_url = (
        await async_generate_agent_callback_url(
            hass,
            entry,
            entry.data[CONF_WEBHOOK_ID],
        )
        if enabled
        else ""
    )
    shared_secret = entry.data.get(CONF_SHARED_SECRET, "") if enabled else ""
    diagnostics = entry.runtime_data.display_bridge_diagnostics
    if enabled:
        diagnostics.mark_callback_attempt(webhook_url, datetime.now(UTC))
    else:
        diagnostics.callback_scheme = None
        diagnostics.callback_host_type = None
        diagnostics.mark_attempt(datetime.now(UTC))
    try:
        status = await api.async_display_bridge_status()
        configured = bool(status.get("configured"))
        if enabled:
            expected_hash = display_bridge_callback_fingerprint(
                True,
                webhook_url,
                shared_secret,
            )
            if configured and status.get("callback_hash") == expected_hash:
                diagnostics.mark_success(datetime.now(UTC))
                return
        elif not configured:
            diagnostics.mark_success(datetime.now(UTC))
            return
        await api.async_configure_display_bridge(
            enabled=enabled,
            webhook_url=webhook_url,
            shared_secret=shared_secret,
        )
        diagnostics.mark_success(datetime.now(UTC))
    except C300XAgentApiUnsupportedError:
        diagnostics.mark_failure(
            "device-agent endpoint is not available",
            datetime.now(UTC),
        )
        if enabled:
            _LOGGER.debug("C300X device agent does not support display bridge registration")
    except C300XAgentApiError as err:
        error = compact_error_text(err)
        diagnostics.mark_failure(error, datetime.now(UTC))
        if enabled:
            _LOGGER.warning("C300X display bridge registration failed: %s", error)


def _async_track_display_bridge_updates(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> Any:
    """Wake the C300X display bridge for HA-side alarm display changes."""

    alarm_entity_id = _entry_config_value(entry, CONF_ALARM_ENTITY_ID, "")
    if not _entry_config_value(entry, CONF_DEVICE_UI_ENABLED, False) or not alarm_entity_id:
        return None

    from homeassistant.core import callback
    from homeassistant.helpers.dispatcher import async_dispatcher_connect

    alarm_sensor_entity_ids = set(_alarmo_sensor_entity_ids(hass))

    def _refresh_alarm_sensor_entity_ids() -> None:
        alarm_sensor_entity_ids.clear()
        alarm_sensor_entity_ids.update(_alarmo_sensor_entity_ids(hass))

    @callback
    def _handle_alarm_state_change(event: Any) -> None:
        if not _display_bridge_alarm_state_event_relevant(
            str(alarm_entity_id),
            alarm_sensor_entity_ids,
            event,
        ):
            return
        _async_schedule_display_bridge_notify(hass, entry)

    @callback
    def _handle_alarmo_event(*_args: Any) -> None:
        _refresh_alarm_sensor_entity_ids()
        _async_schedule_display_bridge_notify(hass, entry)

    bus = getattr(hass, "bus", None)
    async_listen = getattr(bus, "async_listen", None)
    if not callable(async_listen):
        return None

    unsubscribers = [async_listen("state_changed", _handle_alarm_state_change)]
    unsubscribers.append(
        async_dispatcher_connect(
            hass,
            "alarmo_event",
            _handle_alarmo_event,
        )
    )

    def _unsub_all() -> None:
        for unsubscribe in unsubscribers:
            unsubscribe()

    return _unsub_all


def _display_bridge_alarm_state_event_relevant(
    alarm_entity_id: str,
    alarm_sensor_entity_ids: set[str],
    event: Any,
) -> bool:
    """Return whether a HA state change can affect the display alarm page."""

    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        return False
    changed_entity_id = data.get("entity_id")
    if not isinstance(changed_entity_id, str) or not changed_entity_id:
        return False
    if changed_entity_id == alarm_entity_id:
        return True
    return changed_entity_id in alarm_sensor_entity_ids


def _alarmo_sensor_entity_ids(hass: HomeAssistant) -> tuple[str, ...]:
    """Return Alarmo sensor entity ids relevant for live display refreshes."""

    alarmo_data = _alarmo_runtime_data(hass)
    if not isinstance(alarmo_data, dict):
        return ()

    entity_ids: set[str] = set()
    sensor_handler = alarmo_data.get("sensor_handler")
    sensor_config = getattr(sensor_handler, "_config", None)
    if isinstance(sensor_config, dict):
        entity_ids.update(
            str(entity_id)
            for entity_id in sensor_config
            if isinstance(entity_id, str) and "." in entity_id
        )

    for alarmo_entity in _alarmo_display_entities(alarmo_data):
        for open_sensors_name in ("open_sensors", "_open_sensors"):
            open_sensors = getattr(alarmo_entity, open_sensors_name, None)
            if isinstance(open_sensors, dict):
                entity_ids.update(
                    str(entity_id)
                    for entity_id in open_sensors
                    if isinstance(entity_id, str) and "." in entity_id
                )
    return tuple(entity_ids)


def _alarmo_runtime_data(hass: HomeAssistant) -> Any:
    """Return Alarmo runtime data from Home Assistant."""

    hass_data = getattr(hass, "data", None)
    if not isinstance(hass_data, dict):
        return None
    return hass_data.get("alarmo")


def _alarmo_display_entities(alarmo_data: dict[str, Any]) -> tuple[Any, ...]:
    """Return Alarmo master and area entities known to the runtime."""

    entities: list[Any] = []
    master = alarmo_data.get("master")
    if master is not None:
        entities.append(master)
    areas = alarmo_data.get("areas")
    if isinstance(areas, dict):
        entities.extend(area for area in areas.values() if area is not None)
    return tuple(entities)


def _async_schedule_display_bridge_notify(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Schedule one non-blocking display bridge wake-up."""

    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    if connection_state is not None and not connection_state.available:
        return
    hass.add_job(_async_notify_display_bridge_alarm_if_listening, entry)


async def _async_notify_display_bridge_alarm_if_listening(
    entry: BticinoC300XConfigEntry,
) -> None:
    """Notify the display bridge only while a local QML page is listening."""

    try:
        diagnostics = await entry.runtime_data.api.async_diagnostics()
        waiters = diagnostics.get("ui_event_waiters")
        if not isinstance(waiters, int) or waiters <= 0:
            return
        await entry.runtime_data.api.async_notify_display_bridge_event("alarm")
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support display bridge events")
    except C300XAgentApiError:
        _LOGGER.debug("C300X display bridge alarm notification failed", exc_info=True)
