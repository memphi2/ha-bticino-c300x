"""Switches for BTicino C300X."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agent_diagnostics import async_refresh_agent_diagnostics
from .api import (
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
)
from .capabilities import auth_config_supported, maintenance_action_is_advertised
from .const import (
    CONF_AGENT_TOKEN,
    CONF_MAINTENANCE_TOKEN,
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_AUTH_CONFIG_CHANGED,
    SIGNAL_MQTT_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
)
from .device_user import homeassistant_account_label
from .entity import C300XEntity, entry_config_value, supports_capability
from .entity import entry_video_enabled
from .event_payload import agent_event_key
from .qml_patch import (
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_patch_and_confirm,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X switches."""

    entities: list[SwitchEntity] = []
    if supports_capability(entry, "ringer"):
        entities.append(C300XRingerMuteSwitch(entry))
    if supports_capability(entry, "answering_machine"):
        entities.append(C300XAnsweringMachineSwitch(entry))
    if entry_video_enabled(entry) and supports_capability(entry, "device_user"):
        entities.append(C300XHomeAssistantUserPatchSwitch(entry))
    entities.append(C300XNoAuthSwitch(entry))
    entities.append(C300XMaintenanceNoAuthSwitch(entry))
    entities.append(C300XMdnsDiscoverySwitch(entry))
    entities.append(C300XMaintenanceSshSwitch(entry))
    entities.append(C300XGuiFunctionPatchSwitch(entry))
    entities.append(C300XFirewallPatchSwitch(entry))
    entities.append(C300XIpv6FirewallPatchSwitch(entry))
    entities.append(C300XNativeMqttBridgeSwitch(entry))
    entities.append(C300XLegacyMqttBridgeSwitch(entry))
    if entities:
        await _async_refresh_initial_states(entities)
        async_add_entities(entities)


class C300XHomeAssistantUserPatchSwitch(C300XEntity, SwitchEntity):
    """Apply or restore the full Home Assistant media-user patch."""

    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "homeassistant_user_patch"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "homeassistant_user_patch")
        self._status: dict = {}
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the complete Home Assistant user patch is active."""

        if not self._status:
            return None
        return (
            self._status.get("homeassistant_user_present") is True
            and self._status.get("routes_consistent") is True
            and self._status.get("inhouse_binary_patch_applied") is True
            and self._status.get("inhouse_qml_patch_applied") is True
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return the non-sensitive patch status reported by the agent."""

        keys = (
            "homeassistant_user_present",
            "routes_consistent",
            "media_identity_available",
            "media_identity_source",
            "inhouse_binary_patch_state",
            "inhouse_binary_patch_backup_present",
            "inhouse_binary_patch_error",
            "inhouse_qml_patch_state",
            "account_label",
            "error",
        )
        return {key: self._status.get(key) for key in keys if key in self._status}

    async def async_turn_on(self, **kwargs) -> None:
        """Apply the complete Home Assistant media-user patch."""

        try:
            status = await self._entry.runtime_data.api.async_ensure_homeassistant_user(
                account_label=homeassistant_account_label(self.hass)
            )
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support device-user setup"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X Home Assistant user patch failed") from err
        await self._store_status(status)

    async def async_turn_off(self, **kwargs) -> None:
        """Restore the binary/QML parts of the Home Assistant media-user patch."""

        try:
            status = await self._entry.runtime_data.api.async_restore_homeassistant_user_patch()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support device-user restore"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X Home Assistant user patch restore failed") from err
        await self._store_status(status)

    async def async_update(self) -> None:
        """Refresh patch state through the agent read-only endpoint."""

        try:
            status = await self._entry.runtime_data.api.async_device_user_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        await self._store_status(status, write_state=False)

    async def _store_status(self, status: dict, *, write_state: bool = True) -> None:
        self._status = status
        self._attr_available = True
        self._entry.runtime_data.device_user_status = status
        from .repair_issues import async_sync_entry_repair_issues

        async_sync_entry_repair_issues(self.hass, self._entry)
        await async_refresh_agent_diagnostics(self.hass, self._entry)
        if write_state:
            self.async_write_ha_state()


class C300XRingerMuteSwitch(C300XEntity, SwitchEntity):
    """Mute or unmute the C300X ringer."""

    _attr_should_poll = False
    _attr_translation_key = "ringer_mute"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "ringer_mute")
        self._muted: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the ringer is muted."""

        return self._muted

    async def async_turn_on(self, **kwargs) -> None:
        """Mute the ringer."""

        await self._set_muted(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Unmute the ringer."""

        await self._set_muted(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh ringer mute state."""

        try:
            status = await self._entry.runtime_data.api.async_ringer_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_muted(self, muted: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_ringer_muted(muted)
        self._apply_status(status)

    def _apply_status(self, status: dict) -> None:
        self._muted = status.get("muted")
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to push state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        event_type = agent_event_key(event.data)
        if event_type not in {"ringer_muted", "ringer_unmuted"}:
            return
        self._muted = event_type == "ringer_muted"
        self._attr_available = True
        self.async_write_ha_state()


class C300XAnsweringMachineSwitch(C300XEntity, SwitchEntity):
    """Enable or disable the C300X answering machine."""

    _attr_should_poll = False
    _attr_translation_key = "answering_machine"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "answering_machine")
        self._enabled: bool | None = None
        self._greeting_message_enabled: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the answering machine is enabled."""

        return self._enabled

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return answering-machine status metadata."""

        return {"greeting_message_enabled": self._greeting_message_enabled}

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the answering machine."""

        await self._set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the answering machine."""

        await self._set_enabled(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh answering-machine state."""

        try:
            status = await self._entry.runtime_data.api.async_answering_machine_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_answering_machine_enabled(
            enabled
        )
        self._apply_status(status)

    def _apply_status(self, status: dict) -> None:
        self._enabled = status.get("enabled")
        self._greeting_message_enabled = status.get("greeting_message_enabled")
        self._attr_available = True


class C300XMaintenanceSshSwitch(C300XEntity, SwitchEntity):
    """Start or stop SSH through the device-agent maintenance API."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "maintenance_ssh"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "maintenance_ssh")
        self._running: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether SSH is running."""

        return self._running

    @property
    def available(self) -> bool:
        """Return true when the SSH maintenance action is advertised."""

        return super().available and _supports_maintenance_action(
            self._entry,
            "ssh_start",
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Start SSH."""

        await self._set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop SSH."""

        await self._set_enabled(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh SSH state through the maintenance API."""

        if not _supports_maintenance_action(self._entry, "ssh_start"):
            return
        try:
            status = await self._entry.runtime_data.api.async_ssh_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_ssh_enabled(enabled)
        self._apply_status(status)

    def _apply_status(self, status: dict) -> None:
        self._running = status.get("running")
        self._attr_available = True


class C300XGuiFunctionPatchSwitch(C300XEntity, SwitchEntity):
    """Apply or restore the device GUI function patch."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "gui_function_patch"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "gui_function_patch")
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the GUI function patch is fully applied."""

        patched = _qml_patch_status(self._entry).get("patched")
        return patched if isinstance(patched, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return read-only patch metadata."""

        status = _qml_patch_status(self._entry)
        return {
            "state": status.get("state"),
            "backup_available": status.get("backup_available"),
            "core_state": status.get("core_state"),
            "core_patched": status.get("core_patched"),
            "core_backup_available": status.get("core_backup_available"),
            "gui_running": status.get("gui_running"),
        }

    @property
    def available(self) -> bool:
        """Return true when all GUI patch maintenance actions are advertised."""

        return super().available and _supports_maintenance_actions(
            self._entry,
            "qml_status",
            "qml_patch",
            "qml_restore",
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Apply the GUI function patch."""

        status = await async_apply_qml_patch_and_confirm(
            self._entry,
            self._dispatch_qml_patch_changed,
        )
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore the original GUI files."""

        status = await async_restore_qml_patch_and_confirm(
            self._entry,
            self._dispatch_qml_patch_changed,
        )
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh GUI patch state through the read-only status endpoint."""

        if not _supports_maintenance_actions(
            self._entry,
            "qml_status",
            "qml_patch",
            "qml_restore",
        ):
            return
        try:
            status = await async_refresh_qml_patch_status(self._entry)
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def async_added_to_hass(self) -> None:
        """Subscribe to GUI patch state updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_QML_PATCH_CHANGED,
                self._handle_qml_patch_changed,
            )
        )

    @callback
    def _handle_qml_patch_changed(self, entry_id: str) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._apply_status(_qml_patch_status(self._entry))
        self.async_write_ha_state()

    def _dispatch_qml_patch_changed(self) -> None:
        hass = getattr(self, "hass", None)
        if hass is not None:
            async_dispatcher_send(hass, SIGNAL_QML_PATCH_CHANGED, self._entry.entry_id)

    def _apply_status(self, status: dict) -> None:
        self._attr_available = bool(status.get("available", True))


class C300XFirewallPatchSwitch(C300XEntity, SwitchEntity):
    """Apply or restore the persistent IPv4 API firewall patch."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_translation_key = "firewall_patch"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "firewall_patch")
        self._status: dict[str, object] = {}
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the IPv4 firewall patch is fully applied."""

        patched = self._status.get("patched")
        return patched if isinstance(patched, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return read-only IPv4 firewall patch metadata."""

        return {
            "state": self._status.get("state"),
            "family": self._status.get("family"),
            "exists": self._status.get("exists"),
            "backup_available": self._status.get("backup_available"),
            "api_port": self._status.get("api_port"),
            "rtsp_port": self._status.get("rtsp_port"),
            "talkback_rtp_port": self._status.get("talkback_rtp_port"),
            "media_ports_enabled": self._status.get("media_ports_enabled"),
            "changed_files": self._status.get("changed_files"),
        }

    @property
    def available(self) -> bool:
        """Return true when IPv4 firewall maintenance is configurable."""

        return super().available and _supports_firewall_switch(self._entry)

    async def async_turn_on(self, **kwargs) -> None:
        """Apply the persistent IPv4 API firewall rule."""

        await self._async_enable_maintenance_endpoint()
        status = await self._entry.runtime_data.api.async_apply_firewall()
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore the original IPv4 firewall script."""

        status = await self._entry.runtime_data.api.async_restore_firewall()
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh IPv4 firewall patch state through the read-only status endpoint."""

        if not _supports_firewall_switch(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_firewall_status()
        except C300XAgentApiUnsupportedError:
            if await self._async_configured_endpoint_disabled():
                self._apply_disabled_status()
                return
            self._attr_available = False
            return
        except C300XAgentApiError:
            if await self._async_configured_endpoint_disabled():
                self._apply_disabled_status()
                return
            self._attr_available = False
            return
        self._apply_status(status)

    async def _async_enable_maintenance_endpoint(self) -> None:
        """Enable IPv4 firewall maintenance before applying the explicit patch."""

        if not _supports_auth_config(self._entry):
            return
        status = await self._entry.runtime_data.api.async_set_firewall_enabled(True)
        _dispatch_auth_config_status(self, status)

    async def _async_configured_endpoint_disabled(self) -> bool:
        """Return true when config says the IPv4 firewall endpoint is disabled."""

        if not _supports_auth_config(self._entry):
            return False
        try:
            status = await self._entry.runtime_data.api.async_auth_config_status()
        except C300XAgentApiError:
            return False
        _dispatch_auth_config_status(self, status)
        return (
            status.get("firewall_enabled") is False
            or status.get("maintenance_enabled") is False
        )

    def _apply_disabled_status(self) -> None:
        self._apply_status(
            {
                "available": True,
                "family": "ipv4",
                "patched": False,
                "state": "disabled",
            }
        )

    def _apply_status(self, status: dict) -> None:
        self._status = status
        self._attr_available = bool(status.get("available", True))


class C300XIpv6FirewallPatchSwitch(C300XEntity, SwitchEntity):
    """Apply or restore the persistent IPv6 API firewall patch."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_translation_key = "ipv6_firewall_patch"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "ipv6_firewall_patch")
        self._status: dict[str, object] = {}
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the IPv6 firewall patch is fully applied."""

        patched = self._status.get("patched")
        return patched if isinstance(patched, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return read-only IPv6 firewall patch metadata."""

        return {
            "state": self._status.get("state"),
            "family": self._status.get("family"),
            "exists": self._status.get("exists"),
            "backup_available": self._status.get("backup_available"),
            "api_port": self._status.get("api_port"),
            "rtsp_port": self._status.get("rtsp_port"),
            "talkback_rtp_port": self._status.get("talkback_rtp_port"),
            "media_ports_enabled": self._status.get("media_ports_enabled"),
            "changed_files": self._status.get("changed_files"),
        }

    @property
    def available(self) -> bool:
        """Return true when IPv6 firewall maintenance is configurable."""

        return super().available and _supports_ipv6_firewall_switch(self._entry)

    async def async_turn_on(self, **kwargs) -> None:
        """Apply the persistent IPv6 API firewall rules."""

        await self._async_enable_maintenance_endpoint()
        status = await self._entry.runtime_data.api.async_apply_ipv6_firewall()
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Restore the original IPv6 firewall script."""

        status = await self._entry.runtime_data.api.async_restore_ipv6_firewall()
        self._apply_status(status)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh IPv6 firewall patch state through the read-only status endpoint."""

        if not _supports_ipv6_firewall_switch(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_ipv6_firewall_status()
        except C300XAgentApiUnsupportedError:
            if await self._async_configured_endpoint_disabled():
                self._apply_disabled_status()
                return
            self._attr_available = False
            return
        except C300XAgentApiError:
            if await self._async_configured_endpoint_disabled():
                self._apply_disabled_status()
                return
            self._attr_available = False
            return
        self._apply_status(status)

    async def _async_enable_maintenance_endpoint(self) -> None:
        """Enable IPv6 firewall maintenance before applying the explicit patch."""

        if not _supports_auth_config(self._entry):
            return
        status = (
            await self._entry.runtime_data.api.async_set_ipv6_firewall_enabled(True)
        )
        _dispatch_auth_config_status(self, status)

    async def _async_configured_endpoint_disabled(self) -> bool:
        """Return true when config says the IPv6 firewall endpoint is disabled."""

        if not _supports_auth_config(self._entry):
            return False
        try:
            status = await self._entry.runtime_data.api.async_auth_config_status()
        except C300XAgentApiError:
            return False
        _dispatch_auth_config_status(self, status)
        return (
            status.get("ipv6_firewall_enabled") is False
            or status.get("maintenance_enabled") is False
        )

    def _apply_disabled_status(self) -> None:
        self._apply_status(
            {
                "available": True,
                "family": "ipv6",
                "patched": False,
                "state": "disabled",
            }
        )

    def _apply_status(self, status: dict) -> None:
        self._status = status
        self._attr_available = bool(status.get("available", True))


class C300XNativeMqttBridgeSwitch(C300XEntity, SwitchEntity):
    """Enable or disable the native MQTT bridge."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "native_mqtt_bridge"

    def __init__(self, entry: ConfigEntry) -> None:
        # Preserve the pre-split unique ID. Older builds mislabeled the native
        # bridge as "legacy_mqtt_bridge"; reusing that unique ID keeps existing
        # HA entity customizations attached to the native bridge.
        super().__init__(entry, "legacy_mqtt_bridge")
        self._enabled: bool | None = None
        self._status: dict[str, object] = {}
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the native MQTT bridge is enabled."""

        if not self.available:
            return False
        return self._enabled

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return non-sensitive MQTT bridge metadata."""

        return {
            "configured": self._status.get("configured"),
            "connected": self._status.get("connected"),
            "subscribed": self._status.get("subscribed"),
            "host_configured": self._status.get("host_configured"),
            "username_configured": self._status.get("username_configured"),
            "password_configured": self._status.get("password_configured"),
            "port": self._status.get("port"),
            "client_id": self._status.get("client_id"),
            "command_host": self._status.get("command_host"),
            "command_port": self._status.get("command_port"),
            "command_topic": self._status.get("command_topic"),
            "event_topic": self._status.get("event_topic"),
            "json_event_topic": self._status.get("json_event_topic"),
            "status_topic": self._status.get("status_topic"),
            "availability_topic": self._status.get("availability_topic"),
            "qos": self._status.get("qos"),
            "keepalive_seconds": self._status.get("keepalive_seconds"),
            "reconnect_initial_seconds": self._status.get(
                "reconnect_initial_seconds"
            ),
            "reconnect_max_seconds": self._status.get("reconnect_max_seconds"),
            "legacy_installed": self._status.get("legacy_installed"),
            "legacy_enabled": self._status.get("legacy_enabled"),
            "legacy_running": self._status.get("legacy_running"),
            "exclusive": self._status.get("exclusive"),
        }

    @property
    def available(self) -> bool:
        """Return true when native MQTT maintenance endpoints are advertised."""

        return super().available and _supports_native_mqtt_bridge_switch(self._entry)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the native MQTT bridge."""

        await self._set_enabled(True)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()
        _dispatch_mqtt_status_changed(self, self._status)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the native MQTT bridge."""

        await self._set_enabled(False)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()
        _dispatch_mqtt_status_changed(self, self._status)

    async def async_update(self) -> None:
        """Refresh MQTT bridge state through the maintenance API."""

        if not _supports_native_mqtt_bridge_switch(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_mqtt_status()
        except C300XAgentApiError:
            self._status = {}
            self._enabled = False
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_mqtt_enabled(enabled)
        self._apply_status(status)

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT bridge state changes from the companion switch."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MQTT_CHANGED,
                self._handle_mqtt_status,
            )
        )

    @callback
    def _handle_mqtt_status(self, entry_id: str, status: dict) -> None:
        if entry_id != self._entry.entry_id:
            return
        native_enabled = status.get("native_enabled")
        if native_enabled is not None:
            self._enabled = native_enabled
            self._status = {**self._status, **status}
            self.async_write_ha_state()

    def _apply_status(self, status: dict) -> None:
        self._status = status
        self._enabled = status.get("enabled")
        self._attr_available = bool(status.get("available", True))


class C300XLegacyMqttBridgeSwitch(C300XEntity, SwitchEntity):
    """Enable or disable the legacy TcpDump2Mqtt autostart."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_translation_key = "legacy_mqtt_bridge"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "legacy_tcpdump2mqtt_bridge")
        self._enabled: bool | None = None
        self._status: dict[str, object] = {}
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether the legacy TcpDump2Mqtt autostart is enabled."""

        if not self.available:
            return False
        return self._enabled

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return non-sensitive legacy MQTT patch metadata."""

        return {
            "installed": self._status.get("installed"),
            "running": self._status.get("running"),
            "backup_available": self._status.get("backup_available"),
            "native_enabled": self._status.get("native_enabled"),
            "exclusive": self._status.get("exclusive"),
            "script_path": self._status.get("script_path"),
            "init_link": self._status.get("init_link"),
            "flexisip_backup_available": self._status.get(
                "flexisip_backup_available"
            ),
            "flexisip_restart_marker": self._status.get("flexisip_restart_marker"),
            "flexisip_reference_state": self._status.get(
                "flexisip_reference_state"
            ),
        }

    @property
    def available(self) -> bool:
        """Return true when legacy MQTT maintenance endpoints are advertised."""

        return super().available and _supports_legacy_mqtt_bridge_switch(self._entry)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the legacy TcpDump2Mqtt autostart."""

        await self._set_enabled(True)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()
        _dispatch_mqtt_status_changed(self, self._status)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the legacy TcpDump2Mqtt autostart and stop MQTT helpers."""

        await self._set_enabled(False)
        await _async_refresh_agent_diagnostics_if_possible(self)
        self.async_write_ha_state()
        _dispatch_mqtt_status_changed(self, self._status)

    async def async_update(self) -> None:
        """Refresh legacy MQTT patch state through the maintenance API."""

        if not _supports_legacy_mqtt_bridge_switch(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_legacy_mqtt_status()
        except C300XAgentApiError:
            self._status = {}
            self._enabled = False
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_legacy_mqtt_enabled(
            enabled
        )
        self._apply_status(status)

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT bridge state changes from the companion switch."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MQTT_CHANGED,
                self._handle_mqtt_status,
            )
        )

    @callback
    def _handle_mqtt_status(self, entry_id: str, status: dict) -> None:
        if entry_id != self._entry.entry_id:
            return
        legacy_enabled = status.get("legacy_enabled")
        legacy_installed = status.get("legacy_installed")
        native_enabled = bool(status.get("enabled") or status.get("native_enabled"))
        exclusive = bool(status.get("exclusive", True))
        if legacy_enabled is not None or legacy_installed is not None:
            self._enabled = bool(
                legacy_enabled and legacy_installed and not (exclusive and native_enabled)
            )
            self._status = {**self._status, **status}
            self.async_write_ha_state()

    def _apply_status(self, status: dict) -> None:
        self._status = status
        native_enabled = bool(status.get("native_enabled"))
        exclusive = bool(status.get("exclusive", True))
        self._enabled = bool(
            status.get("enabled")
            and status.get("installed")
            and not (exclusive and native_enabled)
        )
        self._attr_available = bool(status.get("available", True))


class _AuthConfigStatusEntity(C300XEntity):
    """Mixin for switches backed by the shared agent auth-config endpoint."""

    @property
    def available(self) -> bool:
        """Return true when the agent advertises auth configuration."""

        return super().available and _supports_auth_config(self._entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to shared auth-config updates."""

        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AUTH_CONFIG_CHANGED,
                self._handle_auth_config_status,
            )
        )

    @callback
    def _handle_auth_config_status(self, entry_id: str, status: dict) -> None:
        if entry_id != self._entry.entry_id:
            return
        self._apply_status(status)
        self.async_write_ha_state()


def _dispatch_auth_config_status(entity: C300XEntity, status: dict) -> None:
    hass = getattr(entity, "hass", None)
    if hass is not None:
        async_dispatcher_send(
            hass,
            SIGNAL_AUTH_CONFIG_CHANGED,
            entity._entry.entry_id,
            status,
        )


def _dispatch_mqtt_status_changed(entity: C300XEntity, status: dict) -> None:
    hass = getattr(entity, "hass", None)
    if hass is not None:
        async_dispatcher_send(
            hass,
            SIGNAL_MQTT_CHANGED,
            entity._entry.entry_id,
            status,
        )


class C300XNoAuthSwitch(_AuthConfigStatusEntity, SwitchEntity):
    """Enable or disable the native agent bootstrap noAuth mode."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "maintenance_no_auth"
    _uses_auth_config_status = True

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "maintenance_no_auth")
        self._enabled: bool | None = None
        self._api_token_configured: bool | None = None
        self._maintenance_token_configured: bool | None = None
        self._maintenance_no_auth_allowed: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether noAuth bootstrap mode is enabled."""

        return self._enabled

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return non-sensitive auth configuration metadata."""

        return {
            "api_token_configured": self._api_token_configured,
            "maintenance_token_configured": self._maintenance_token_configured,
            "maintenance_no_auth_allowed": self._maintenance_no_auth_allowed,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Enable noAuth bootstrap mode."""

        await self._set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable noAuth bootstrap mode."""

        await self._set_enabled(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh noAuth state through the maintenance API."""

        if not _supports_auth_config(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_auth_config_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_no_auth_enabled(
            enabled,
            api_token=_configured_token(self._entry, CONF_AGENT_TOKEN)
            if not enabled
            else None,
            maintenance_token=_configured_token(self._entry, CONF_MAINTENANCE_TOKEN)
            if not enabled
            else None,
            maintenance_no_auth_allowed=False if not enabled else None,
        )
        self._apply_status(status)
        _dispatch_auth_config_status(self, status)

    def _apply_status(self, status: dict) -> None:
        self._enabled = status.get("no_auth")
        self._api_token_configured = status.get("api_token_configured")
        self._maintenance_token_configured = status.get(
            "maintenance_token_configured"
        )
        self._maintenance_no_auth_allowed = status.get("maintenance_no_auth_allowed")
        self._attr_available = True


class C300XMdnsDiscoverySwitch(_AuthConfigStatusEntity, SwitchEntity):
    """Enable bootstrap mDNS discovery while the agent has no HA connection."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_translation_key = "maintenance_mdns_discovery"
    _uses_auth_config_status = True

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "maintenance_mdns_discovery")
        self._enabled: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether bootstrap mDNS discovery is enabled."""

        return self._enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable bootstrap mDNS discovery."""

        await self._set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable bootstrap mDNS discovery."""

        await self._set_enabled(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh mDNS discovery config through the maintenance API."""

        if not _supports_auth_config(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_auth_config_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = await self._entry.runtime_data.api.async_set_mdns_enabled(enabled)
        self._apply_status(status)
        _dispatch_auth_config_status(self, status)

    def _apply_status(self, status: dict) -> None:
        self._enabled = status.get("mdns_enabled")
        self._attr_available = True


class C300XMaintenanceNoAuthSwitch(_AuthConfigStatusEntity, SwitchEntity):
    """Allow noAuth requests to use maintenance endpoints."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_translation_key = "maintenance_no_auth_access"
    _uses_auth_config_status = True

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "maintenance_no_auth_access")
        self._enabled: bool | None = None
        self._no_auth: bool | None = None
        self._attr_available = True

    @property
    def is_on(self) -> bool | None:
        """Return whether noAuth maintenance access is allowed."""

        return self._enabled

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return related auth state metadata."""

        return {"no_auth": self._no_auth}

    async def async_turn_on(self, **kwargs) -> None:
        """Allow noAuth maintenance access."""

        await self._set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Deny noAuth maintenance access."""

        await self._set_enabled(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh noAuth maintenance access state."""

        if not _supports_auth_config(self._entry):
            return
        try:
            status = await self._entry.runtime_data.api.async_auth_config_status()
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._apply_status(status)

    async def _set_enabled(self, enabled: bool) -> None:
        status = (
            await self._entry.runtime_data.api.async_set_maintenance_no_auth_allowed(
                enabled
            )
        )
        self._apply_status(status)
        _dispatch_auth_config_status(self, status)

    def _apply_status(self, status: dict) -> None:
        self._enabled = status.get("maintenance_no_auth_allowed")
        self._no_auth = status.get("no_auth")
        self._attr_available = True


async def _async_refresh_initial_states(entities: list[SwitchEntity]) -> None:
    """Populate switch states once during setup without enabling periodic polling."""

    auth_config_entities = [
        entity
        for entity in entities
        if getattr(entity, "_uses_auth_config_status", False)
        and _supports_auth_config(entity._entry)
    ]
    if auth_config_entities:
        try:
            status = (
                await auth_config_entities[
                    0
                ]._entry.runtime_data.api.async_auth_config_status()
            )
        except C300XAgentApiError:
            for entity in auth_config_entities:
                entity._attr_available = False
        else:
            for entity in auth_config_entities:
                entity._apply_status(status)

    for entity in entities:
        if entity in auth_config_entities:
            continue
        await entity.async_update()


def _supports_maintenance_action(entry: ConfigEntry, action: str) -> bool:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return maintenance_action_is_advertised(capabilities, action)


def _supports_maintenance_actions(entry: ConfigEntry, *actions: str) -> bool:
    return all(_supports_maintenance_action(entry, action) for action in actions)


def _supports_firewall_switch(entry: ConfigEntry) -> bool:
    return _supports_maintenance_actions(
        entry,
        "firewall_status",
        "firewall_apply",
        "firewall_restore",
    ) or _supports_auth_config(entry)


def _supports_ipv6_firewall_switch(entry: ConfigEntry) -> bool:
    return _supports_maintenance_actions(
        entry,
        "ipv6_firewall_status",
        "ipv6_firewall_apply",
        "ipv6_firewall_restore",
    ) or _supports_auth_config(entry)


def _supports_native_mqtt_bridge_switch(entry: ConfigEntry) -> bool:
    return _supports_maintenance_actions(entry, "mqtt_status", "mqtt_config")


def _supports_legacy_mqtt_bridge_switch(entry: ConfigEntry) -> bool:
    return _supports_maintenance_actions(
        entry,
        "legacy_mqtt_status",
        "legacy_mqtt_config",
    )


def _supports_auth_config(entry: ConfigEntry) -> bool:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return auth_config_supported(capabilities)


def _configured_token(entry: ConfigEntry, key: str) -> str | None:
    token = str(entry_config_value(entry, key, "") or "").strip()
    return token or None


def _qml_patch_status(entry: ConfigEntry) -> dict[str, object]:
    status = getattr(entry.runtime_data, "qml_patch_status", {})
    return status if isinstance(status, dict) else {}


async def _async_refresh_agent_diagnostics_if_possible(entity: C300XEntity) -> None:
    hass = getattr(entity, "hass", None)
    runtime_data = getattr(entity._entry, "runtime_data", None)
    if hass is None or not hasattr(runtime_data, "capabilities"):
        return
    await async_refresh_agent_diagnostics(hass, entity._entry)
