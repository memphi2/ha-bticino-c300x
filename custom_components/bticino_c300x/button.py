"""Buttons for BTicino C300X commands."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
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
from .api import C300XAgentApiError, C300XAgentApiUnsupportedError
from .capabilities import (
    answering_machine_message_delete_supported,
    entry_device_ui_enabled_or_patch_active,
    entry_gui_function_patch_active,
    locks_for_capabilities,
    maintenance_action_is_advertised,
    memo_delete_supported,
)
from .const import (
    EVENT_AGENT_EVENT_RECEIVED,
    SIGNAL_MEMOS_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
    SIGNAL_VIDEO_MESSAGES_CHANGED,
)
from .entity import C300XEntity, entry_video_enabled, supports_capability
from .event_payload import agent_event_key
from .executor import async_trigger_stair_light, async_unlock_door
from .memos import latest_memo_id
from .message_refresh import (
    async_answering_machine_messages,
    async_memos,
    schedule_answering_machine_messages_refresh,
    schedule_memos_refresh,
)
from .qml_patch import async_refresh_qml_patch_status
from .video_messages import (
    latest_video_message_id,
)

PARALLEL_UPDATES = 1
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up C300X buttons."""

    entities: list[ButtonEntity] = []
    if supports_capability(entry, "stair_light"):
        entities.append(C300XStairLightButton(entry))
    if entry_video_enabled(entry) and supports_capability(entry, "doorbell_video"):
        entities.append(C300XStopDoorbellVideoButton(entry))
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    for lock in locks_for_capabilities(capabilities):
        entities.append(
            C300XDoorUnlockButton(
                entry,
                lock_id=lock["id"],
                lock_name=lock["name"],
            )
        )
    if supports_capability(entry, "activations"):
        for activation in await _async_activation_items(entry):
            if activation.get("executable") is True:
                entities.append(C300XDeviceActivationButton(entry, activation))
    entities.append(C300XRebootButton(entry))
    entities.append(C300XRemoveAgentButton(entry))
    entities.append(C300XRestartAgentButton(entry))
    entities.append(C300XReloadGuiButton(entry))
    if entry_device_ui_enabled_or_patch_active(entry):
        if answering_machine_message_delete_supported(capabilities):
            entities.append(C300XDeleteLatestVideoMessageButton(entry))
        if memo_delete_supported(capabilities):
            entities.append(C300XDeleteLatestTextMemoButton(entry))
            entities.append(C300XDeleteLatestVoiceMemoButton(entry))
    if entities:
        async_add_entities(entities)


class C300XStairLightButton(C300XEntity, ButtonEntity):
    """Button that activates the C300X staircase light command."""

    _attr_translation_key = "stair_light"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "stair_light")

    async def async_press(self) -> None:
        """Activate the staircase light."""

        try:
            await async_trigger_stair_light(self.hass, self._entry)
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support stair light"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X device-agent command failed") from err


class C300XDoorUnlockButton(C300XEntity, ButtonEntity):
    """Button that unlocks a configured C300X door lock."""

    _attr_translation_key = "door_unlock"

    def __init__(self, entry: ConfigEntry, lock_id: str, lock_name: str) -> None:
        key = "door_unlock" if lock_id == "default" else f"door_unlock_{lock_id}"
        super().__init__(entry, key)
        self._lock_id = lock_id
        self._lock_name = lock_name
        self._attr_extra_state_attributes = {"lock_id": lock_id, "lock_name": lock_name}

    async def async_press(self) -> None:
        """Unlock the configured door lock."""

        try:
            await async_unlock_door(self.hass, self._entry, self._lock_id)
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support door unlock"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X device-agent command failed") from err


class C300XDeviceActivationButton(C300XEntity, ButtonEntity):
    """Button that runs one configured C300X device activation."""

    def __init__(self, entry: ConfigEntry, activation: dict[str, Any]) -> None:
        activation_id = str(activation["id"])
        super().__init__(entry, f"device_activation_{activation_id}")
        self._activation = activation
        self._activation_id = activation_id
        self._attr_name = str(activation.get("name") or activation_id)
        self._attr_icon = _activation_icon(str(activation.get("type") or "unknown"))

    @property
    def available(self) -> bool:
        """Return true when the activation can be executed."""

        return super().available and self._activation.get("executable") is True

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return non-secret activation metadata."""

        return {
            "activation_id": self._activation_id,
            "activation_type": self._activation.get("type"),
            "address_mode": self._activation.get("address_mode"),
            "address": self._activation.get("address"),
            "source": self._activation.get("source"),
        }

    async def async_press(self) -> None:
        """Run this configured C300X activation."""

        try:
            await self._entry.runtime_data.api.async_run_device_activation(
                self._activation_id
            )
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support activations"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X device activation failed") from err


class C300XStopDoorbellVideoButton(C300XEntity, ButtonEntity):
    """Button that stops the active C300X doorbell video session."""

    _attr_translation_key = "stop_doorbell_video"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "stop_doorbell_video")

    @property
    def available(self) -> bool:
        """Return true when doorbell video can be controlled."""

        return (
            super().available
            and entry_video_enabled(self._entry)
            and supports_capability(self._entry, "doorbell_video")
        )

    async def async_press(self) -> None:
        """Stop the active doorbell video session."""

        try:
            await self._entry.runtime_data.api.async_stop_doorbell_video()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support doorbell video"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X doorbell video stop failed") from err


class C300XMaintenanceButton(C300XEntity, ButtonEntity):
    """Button backed by an advertised maintenance API action."""

    _maintenance_action = ""

    @property
    def available(self) -> bool:
        """Return true when the maintenance action is currently advertised."""

        return super().available and _supports_maintenance_action(
            self._entry,
            self._maintenance_action,
        )


class C300XRebootButton(C300XMaintenanceButton):
    """Button that reboots the device through the device-agent maintenance API."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reboot"
    _maintenance_action = "reboot"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "reboot")

    async def async_press(self) -> None:
        """Reboot the C300X device."""

        try:
            await self._entry.runtime_data.api.async_reboot()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support rebooting"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X device-agent maintenance command failed") from err


class C300XRemoveAgentButton(C300XMaintenanceButton):
    """Button that removes the native agent and restores managed device patches."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "remove_agent"
    _maintenance_action = "agent_remove"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "remove_agent")

    async def async_press(self) -> None:
        """Schedule native-agent removal through the maintenance API."""

        try:
            await self._entry.runtime_data.api.async_remove_agent()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support removal"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X native-agent removal command failed") from err
        await async_refresh_agent_diagnostics(self.hass, self._entry)


class C300XRestartAgentButton(C300XMaintenanceButton):
    """Button that restarts the native device agent."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "restart_agent"
    _maintenance_action = "agent_restart"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "restart_agent")

    async def async_press(self) -> None:
        """Restart the native device agent through the maintenance API."""

        try:
            await self._entry.runtime_data.api.async_restart_agent()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support restarting"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X native-agent restart command failed") from err
        await async_refresh_agent_diagnostics(self.hass, self._entry)


class C300XReloadGuiButton(C300XMaintenanceButton):
    """Button that reloads the C300X graphical interface."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reload_gui"
    _maintenance_action = "gui_reload"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "reload_gui")

    async def async_press(self) -> None:
        """Reload the device GUI through the device-agent maintenance API."""

        try:
            await self._entry.runtime_data.api.async_reload_gui()
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support Display reload"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X Display reload command failed") from err


class C300XDeleteLatestMemoButton(C300XEntity, ButtonEntity):
    """Button that deletes the latest local memo of one kind."""

    _memo_kind = ""
    _memo_label = "memo"

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        super().__init__(entry, key)

    @property
    def available(self) -> bool:
        """Return true when the memo delete endpoint is available."""

        return (
            bool(getattr(self, "_attr_available", True))
            and _gui_required_action_available(self._entry)
            and _memo_store_available(self._entry)
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the latest memo metadata on the delete entity."""

        memos = getattr(self._entry.runtime_data, "memos", {})
        if not isinstance(memos, dict):
            return {
                "kind": self._memo_kind,
                "has_memo": False,
                "total": None,
                "latest_memo_id": None,
            }
        memo_id = latest_memo_id(memos, self._memo_kind)
        return {
            "kind": self._memo_kind,
            "has_memo": memo_id is not None,
            "total": memos.get(f"{self._memo_kind}_total"),
            "latest_memo_id": memo_id,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to memo refresh notifications."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MEMOS_CHANGED,
                self._handle_memos_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_QML_PATCH_CHANGED,
                self._handle_qml_patch_changed,
            )
        )

    async def async_press(self) -> None:
        """Delete the newest memo and refresh memo state."""

        await _async_ensure_gui_function_patch(self._entry)

        memo_id = latest_memo_id(self._entry.runtime_data.memos, self._memo_kind)
        if memo_id is None:
            try:
                memos = await async_memos(self._entry, force_refresh=True)
            except C300XAgentApiError as err:
                self._attr_available = False
                raise HomeAssistantError("C300X memo refresh failed") from err
            self._attr_available = bool(memos.get("available", True))
            memo_id = latest_memo_id(self._entry.runtime_data.memos, self._memo_kind)
        if memo_id is None:
            async_dispatcher_send(self.hass, SIGNAL_MEMOS_CHANGED, self._entry.entry_id)
            return

        try:
            await self._entry.runtime_data.api.async_delete_memo(memo_id)
            memos = await async_memos(self._entry, force_refresh=True)
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support deleting memos"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X memo delete failed") from err

        self._attr_available = bool(memos.get("available", True))
        async_dispatcher_send(self.hass, SIGNAL_MEMOS_CHANGED, self._entry.entry_id)
        await async_refresh_agent_diagnostics(self.hass, self._entry)

    @callback
    def _handle_memos_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) == "memos_changed":
            schedule_memos_refresh(self.hass, self._entry)

    @callback
    def _handle_qml_patch_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()


class C300XDeleteLatestTextMemoButton(C300XDeleteLatestMemoButton):
    """Button that deletes the latest local text memo."""

    _attr_translation_key = "delete_latest_text_memo"
    _memo_kind = "text"
    _memo_label = "text"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "delete_latest_text_memo")


class C300XDeleteLatestVoiceMemoButton(C300XDeleteLatestMemoButton):
    """Button that deletes the latest local voice memo."""

    _attr_translation_key = "delete_latest_voice_memo"
    _memo_kind = "voice"
    _memo_label = "voice"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "delete_latest_voice_memo")


class C300XDeleteLatestVideoMessageButton(C300XEntity, ButtonEntity):
    """Button that displays and deletes the latest stored video message."""

    _attr_translation_key = "delete_latest_video_message"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "delete_latest_video_message")

    @property
    def available(self) -> bool:
        """Return true when the video-message delete endpoint is available."""

        return (
            bool(getattr(self, "_attr_available", True))
            and _gui_required_action_available(self._entry)
            and _video_message_store_available(self._entry)
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the latest video message metadata on the delete entity."""

        messages = getattr(self._entry.runtime_data, "answering_machine_messages", {})
        if not isinstance(messages, dict):
            return {
                "has_message": False,
                "total": None,
                "unread": None,
                "latest_message_id": None,
            }
        message_id = latest_video_message_id(messages)
        return {
            "has_message": message_id is not None,
            "total": messages.get("total"),
            "unread": messages.get("unread"),
            "latest_message_id": message_id,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to video-message refresh notifications."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_AGENT_EVENT_RECEIVED,
                self._handle_agent_event,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_VIDEO_MESSAGES_CHANGED,
                self._handle_video_messages_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_QML_PATCH_CHANGED,
                self._handle_qml_patch_changed,
            )
        )

    async def async_update(self) -> None:
        """Refresh message metadata on explicit HA update requests."""

        try:
            messages = await async_answering_machine_messages(
                self._entry,
                force_refresh=True,
            )
        except C300XAgentApiError:
            self._attr_available = False
            return
        self._attr_available = bool(messages.get("available", True))

    async def async_press(self) -> None:
        """Delete the newest stored video message and refresh state."""

        await _async_ensure_gui_function_patch(self._entry)

        message_id = latest_video_message_id(
            self._entry.runtime_data.answering_machine_messages
        )
        if message_id is None:
            try:
                messages = await async_answering_machine_messages(
                    self._entry,
                    force_refresh=True,
                )
            except C300XAgentApiError as err:
                self._attr_available = False
                raise HomeAssistantError("C300X video-message refresh failed") from err
            self._attr_available = bool(messages.get("available", True))
            message_id = latest_video_message_id(
                self._entry.runtime_data.answering_machine_messages
            )
        if message_id is None:
            async_dispatcher_send(
                self.hass,
                SIGNAL_VIDEO_MESSAGES_CHANGED,
                self._entry.entry_id,
            )
            return

        try:
            await self._entry.runtime_data.api.async_delete_answering_machine_message(
                message_id
            )
            messages = await async_answering_machine_messages(
                self._entry,
                force_refresh=True,
            )
        except C300XAgentApiUnsupportedError as err:
            raise HomeAssistantError(
                "The installed C300X device agent does not support deleting video messages"
            ) from err
        except C300XAgentApiError as err:
            raise HomeAssistantError("C300X video-message delete failed") from err

        self._attr_available = bool(messages.get("available", True))
        async_dispatcher_send(
            self.hass,
            SIGNAL_VIDEO_MESSAGES_CHANGED,
            self._entry.entry_id,
        )
        await async_refresh_agent_diagnostics(self.hass, self._entry)

    @callback
    def _handle_video_messages_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()

    @callback
    def _handle_agent_event(self, event) -> None:
        if event.data.get("entry_id") != self._entry.entry_id:
            return
        if agent_event_key(event.data) == "answering_machine_messages_changed":
            schedule_answering_machine_messages_refresh(self.hass, self._entry)

    @callback
    def _handle_qml_patch_changed(self, entry_id: str) -> None:
        if entry_id == self._entry.entry_id:
            self.async_write_ha_state()


def _supports_maintenance_action(entry: ConfigEntry, action: str) -> bool:
    capabilities = getattr(entry.runtime_data, "capabilities", {})
    return maintenance_action_is_advertised(capabilities, action)


async def _async_activation_items(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return executable activation discovery items without failing setup."""

    try:
        activations = await entry.runtime_data.api.async_activations()
    except C300XAgentApiUnsupportedError:
        activations = {"available": False, "supported": False, "items": []}
    except C300XAgentApiError as err:
        _LOGGER.debug("C300X activation discovery failed: %s", err)
        activations = {"available": False, "supported": False, "items": []}
    entry.runtime_data.activations = activations
    items = activations.get("items") if isinstance(activations, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _activation_icon(activation_type: str) -> str:
    """Return an icon matching a C300X activation type."""

    if activation_type == "lock":
        return "mdi:lock-open-variant"
    if activation_type in {"light", "stair_light"}:
        return "mdi:lightbulb-on"
    if activation_type == "scenario":
        return "mdi:play-box"
    return "mdi:gesture-tap-button"


def _connection_available(entry: ConfigEntry) -> bool:
    connection_state = getattr(entry.runtime_data, "connection_state", None)
    return connection_state is None or bool(connection_state.available)


def _gui_required_action_available(entry: ConfigEntry) -> bool:
    if not _connection_available(entry):
        return False
    runtime_data = getattr(entry, "runtime_data", None)
    status = getattr(runtime_data, "qml_patch_status", {})
    return entry_device_ui_enabled_or_patch_active(entry) and bool(
        isinstance(status, dict) and status.get("patched") is True
    )


def _memo_store_available(entry: ConfigEntry) -> bool:
    memos = getattr(entry.runtime_data, "memos", {})
    return not isinstance(memos, dict) or bool(memos.get("available", True))


def _video_message_store_available(entry: ConfigEntry) -> bool:
    messages = getattr(entry.runtime_data, "answering_machine_messages", {})
    return not isinstance(messages, dict) or bool(messages.get("available", True))


async def _async_ensure_gui_function_patch(entry: ConfigEntry) -> None:
    if entry_gui_function_patch_active(entry):
        return
    try:
        await async_refresh_qml_patch_status(entry)
    except C300XAgentApiError as err:
        raise HomeAssistantError("C300X Display patch status refresh failed") from err
    if not entry_gui_function_patch_active(entry):
        raise HomeAssistantError(
            "The C300X Display patch is required for this action"
        )
