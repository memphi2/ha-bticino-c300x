"""BTicino C300X Home Assistant integration."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import config_validation as cv

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
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
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
from .device_user import homeassistant_account_label
from .entry_config import (
    entry_config_value as _entry_config_value,
)
from .entry_config import (
    normalized_update_options,
)
from .error_text import compact_error_text

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    type BticinoC300XConfigEntry = ConfigEntry[BticinoC300XRuntimeData]
else:
    BticinoC300XConfigEntry = Any

BASE_PLATFORMS = ("binary_sensor", "button", "event", "sensor", "select", "switch")
CAMERA_PLATFORM = "camera"
_LOGGER = logging.getLogger(__name__)
_GUI_DEPENDENT_ENTITY_KEYS = (
    ("button", "delete_latest_video_message"),
    ("button", "delete_latest_text_memo"),
    ("button", "delete_latest_voice_memo"),
)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""

    from .blueprint_installer import async_install_bundled_blueprints
    from .camera import async_register_home_call_ws
    from .frontend import async_setup_frontend
    from .services import async_setup_services

    hass.data.setdefault(DOMAIN, {})
    await async_install_bundled_blueprints(hass)
    await async_setup_frontend(hass)
    await async_setup_services(hass)
    async_register_home_call_ws(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> bool:
    """Normalize existing entries before Home Assistant sets them up."""

    data = dict(getattr(entry, "data", {}) or {})
    options = normalized_update_options(data, dict(getattr(entry, "options", {}) or {}))
    original_data = dict(data)
    original_options = dict(getattr(entry, "options", {}) or {})

    if not str(data.get(CONF_AGENT_HOST, "") or "").strip() and data.get("controller_host"):
        data[CONF_AGENT_HOST] = data["controller_host"]

    _ensure_generated_setup_secret(data, CONF_WEBHOOK_ID, 24)
    _ensure_generated_setup_secret(data, CONF_SHARED_SECRET, 32)
    _ensure_generated_setup_secret(data, CONF_EVENT_WEBHOOK_ID, 24)
    _ensure_generated_setup_secret(data, CONF_EVENT_WEBHOOK_TOKEN, 32)

    if (
        data != original_data
        or options != original_options
        or getattr(entry, "minor_version", 1) < 2
    ):
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            version=1,
            minor_version=2,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Set up a C300X config entry."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .agent_update import async_load_packaged_bundle_metadata, compare_agent_bundle
    from .capabilities import gate_capabilities
    from .events import async_start_agent_event_registration
    from .media import async_setup_media_view
    from .repair_issues import async_sync_entry_repair_issues
    from .services import async_setup_services
    from .webhook import (
        async_register_agent_event_webhook,
        async_register_webhook,
    )

    hass.data.setdefault(DOMAIN, {})
    required = (
        CONF_AGENT_HOST,
        CONF_WEBHOOK_ID,
        CONF_SHARED_SECRET,
        CONF_EVENT_WEBHOOK_ID,
        CONF_EVENT_WEBHOOK_TOKEN,
    )
    missing_required = tuple(key for key in required if not _entry_config_value(entry, key))
    if missing_required:
        _LOGGER.error(
            "C300X config entry is missing required setup field(s): %s",
            ", ".join(missing_required),
        )
        return False

    agent_host = str(_entry_config_value(entry, CONF_AGENT_HOST, "")).strip()
    base_url = build_agent_base_url(
        agent_host,
        int(_entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)),
    )
    api = C300XAgentApi(
        async_get_clientsession(hass),
        base_url,
        str(_entry_config_value(entry, CONF_AGENT_TOKEN, "")),
        str(_entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")),
    )
    event_state = C300XEventState()
    connection_state = C300XConnectionState()
    unregister_event_registration = None
    try:
        setup_data = await api.async_validate_setup()
    except C300XAgentApiError as err:
        _LOGGER.info("C300X device agent is offline during setup: %s", err)
        setup_data = _offline_setup_data(err)
        capabilities = {}
        connection_state.mark_reconnecting(
            type(err).__name__,
            DEFAULT_RECONNECT_GRACE_SECONDS,
            compact_error_text(err),
        )
        connection_state.mark_unavailable()
        unregister_event_registration = _async_start_setup_recovery(
            hass,
            entry,
            api,
            connection_state,
        )
    else:
        capabilities = setup_data.get("capabilities", {})
        if not isinstance(capabilities, dict):
            capabilities = {}
        capabilities = gate_capabilities(
            capabilities,
            doorbell_video_enabled=_entry_video_enabled(entry),
        )
    agent_update_state = (
        None
        if not connection_state.available
        else compare_agent_bundle(
            setup_data,
            await async_load_packaged_bundle_metadata(hass),
        )
    )
    unregister_webhook = async_register_webhook(hass, entry)
    unregister_event_webhook = async_register_agent_event_webhook(
        hass,
        entry,
        event_state,
    )

    async def _async_refresh_runtime_registration() -> None:
        await _async_configure_display_bridge(hass, entry, api)

    if unregister_event_registration is None:
        unregister_event_registration = await async_start_agent_event_registration(
            hass,
            entry,
            api,
            capabilities,
            connection_state,
            on_runtime_registration_created=_async_refresh_runtime_registration,
        )
    platforms = _entry_platforms(entry, capabilities)
    entry.runtime_data = BticinoC300XRuntimeData(
        api=api,
        event_state=event_state,
        connection_state=connection_state,
        capabilities=capabilities,
        agent_info=setup_data,
        unregister_webhook=unregister_webhook,
        unregister_event_webhook=unregister_event_webhook,
        unregister_event_registration=unregister_event_registration,
        on_runtime_registration_created=_async_refresh_runtime_registration,
        unregister_display_bridge_updates=None,
        loaded_platforms=platforms,
        agent_update_state=agent_update_state,
    )
    hass.data.setdefault(DOMAIN, {}).setdefault(DATA_RUNTIME_ENTRIES, {})[
        entry.entry_id
    ] = entry.runtime_data
    entry.runtime_data.unregister_display_bridge_updates = (
        _async_track_display_bridge_updates(hass, entry)
    )
    if connection_state.available:
        await _async_configure_device_activations(entry, api)
        await _async_configure_display_bridge(hass, entry, api)
        await _async_sync_device_ui_patch(entry)
        await _async_sync_device_user(hass, entry)
        await _async_refresh_self_test(entry)
    _async_remove_stale_gui_dependent_entities(hass, entry)
    async_sync_entry_repair_issues(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await async_setup_services(hass)
    async_setup_media_view(hass)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


def _ensure_generated_setup_secret(
    data: dict[str, Any],
    key: str,
    token_bytes: int,
) -> None:
    """Generate a setup secret when an older config entry does not have one."""

    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return
    if value not in (None, ""):
        return
    data[key] = secrets.token_urlsafe(token_bytes)


async def async_unload_entry(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Unload a C300X config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        entry.runtime_data.loaded_platforms,
    )
    if unload_ok:
        if entry.runtime_data.unregister_event_registration:
            entry.runtime_data.unregister_event_registration()
        if entry.runtime_data.unregister_display_bridge_updates:
            entry.runtime_data.unregister_display_bridge_updates()
        if entry.runtime_data.connection_state.expire_unavailable:
            entry.runtime_data.connection_state.expire_unavailable()
        if entry.runtime_data.memos_refresh_task:
            entry.runtime_data.memos_refresh_task.cancel()
            entry.runtime_data.memos_refresh_task = None
        if entry.runtime_data.answering_machine_messages_refresh_task:
            entry.runtime_data.answering_machine_messages_refresh_task.cancel()
            entry.runtime_data.answering_machine_messages_refresh_task = None
        entry.runtime_data.unregister_event_webhook()
        entry.runtime_data.unregister_webhook()
        hass.data.get(DOMAIN, {}).get(DATA_RUNTIME_ENTRIES, {}).pop(
            entry.entry_id,
            None,
        )
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Reload when options change."""

    await hass.config_entries.async_reload(entry.entry_id)


def _async_remove_stale_gui_dependent_entities(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Remove stale HA entities for C300X GUI functions that are currently gated."""

    if entry_device_ui_enabled(entry):
        return

    from homeassistant.helpers import entity_registry as er

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

    if _entry_video_enabled(entry) and capability_is_supported(capabilities or {}, "doorbell_video"):
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
            if _device_user_bootstrap_satisfied(status):
                _mark_homeassistant_media_user_bootstrapped(hass, entry)
        elif _device_user_bootstrap_satisfied(status):
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
        and _device_user_bootstrap_needed(status)
    )


def _device_user_bootstrap_needed(status: dict[str, Any]) -> bool:
    """Return true for a hard missing media-user/routing status."""

    if status.get("available") is False or status.get("status_available") is False:
        return False
    if status.get("homeassistant_user_present") is False:
        return True
    if status.get("media_identity_available") is False:
        return True
    if status.get("routes_consistent") is False:
        return True
    return (
        status.get("homeassistant_user_present") is True
        and "device_routing_applied" in status
        and status.get("device_routing_applied") is False
    )


def _device_user_bootstrap_satisfied(status: dict[str, Any]) -> bool:
    """Return true when startup can mark the one-time bootstrap as done."""

    if status.get("available") is False or status.get("status_available") is False:
        return False
    return (
        status.get("homeassistant_user_present") is True
        and status.get("media_identity_available") is not False
        and status.get("routes_consistent") is not False
        and status.get("device_routing_applied") is not False
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

    enabled, auto_discover, stair_light_address = _entry_activation_config(entry)
    try:
        status = await api.async_auth_config_status()
        current_enabled = status.get("activations_enabled")
        current_auto_discover = status.get("activations_auto_discover")
        current_stair_light_address = status.get("activation_stair_light_address")
        if current_enabled is None or current_auto_discover is None:
            return
        if (
            current_enabled is enabled
            and current_auto_discover is auto_discover
            and (auto_discover or current_stair_light_address in {None, stair_light_address})
        ):
            return
        await api.async_configure_device_activations(
            enabled=enabled,
            auto_discover=auto_discover,
            stair_light_address=stair_light_address,
        )
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support activation configuration")
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X activation configuration sync failed: %s",
            compact_error_text(err),
        )


def _entry_activation_config(entry: BticinoC300XConfigEntry) -> tuple[bool, bool, str]:
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
    if str(p_value or "").strip() or str(n_value or "").strip():
        address = stair_light_where_from_entry_values(p_value, n_value)
    else:
        address = str(
            _entry_config_value(entry, CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS, "")
            or ""
        ).strip() or stair_light_where_from_entry_values("", "")
    return True, auto_discover, address


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
    """Wake the C300X display bridge for HA-side alarm state changes."""

    alarm_entity_id = _entry_config_value(entry, CONF_ALARM_ENTITY_ID, "")
    if not _entry_config_value(entry, CONF_DEVICE_UI_ENABLED, False) or not alarm_entity_id:
        return None

    from homeassistant.core import callback
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.event import async_track_state_change_event

    @callback
    def _handle_alarm_state_change(_event: Any) -> None:
        _async_schedule_display_bridge_notify(hass, entry)

    @callback
    def _handle_alarmo_event(*_args: Any) -> None:
        _async_schedule_display_bridge_notify(hass, entry)

    unsubscribers = [
        async_track_state_change_event(
            hass,
            [str(alarm_entity_id)],
            _handle_alarm_state_change,
        )
    ]
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


def _async_schedule_display_bridge_notify(
    hass: HomeAssistant,
    entry: BticinoC300XConfigEntry,
) -> None:
    """Schedule one non-blocking display bridge wake-up."""

    runtime_data = getattr(entry, "runtime_data", None)
    connection_state = getattr(runtime_data, "connection_state", None)
    if connection_state is not None and not connection_state.available:
        return
    hass.add_job(_async_notify_display_bridge_alarm, entry)


async def _async_notify_display_bridge_alarm(entry: BticinoC300XConfigEntry) -> None:
    """Notify the local display bridge that alarm display data changed."""

    try:
        await entry.runtime_data.api.async_notify_display_bridge_event("alarm")
    except C300XAgentApiUnsupportedError:
        _LOGGER.debug("C300X device agent does not support display bridge events")
    except C300XAgentApiError:
        _LOGGER.debug("C300X display bridge alarm notification failed", exc_info=True)
