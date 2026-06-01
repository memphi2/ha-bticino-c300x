"""Home Assistant Repairs flows for BTicino C300X."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .agent_update import async_apply_packaged_agent_update, compare_agent_bundle
from .api import C300XAgentApiError
from .capabilities import (
    entry_device_ui_enabled,
    gate_capabilities,
    qml_patch_status_is_active,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
    DEFAULT_AGENT_PORT,
    DOMAIN,
    SIGNAL_AGENT_INFO_CHANGED,
)
from .device_installer import (
    C300XDeviceInstallRequest,
    async_install_device_agent,
)
from .entry_config import entry_config_value
from .mqtt_migration import async_migrate_legacy_mqtt_if_available
from .qml_patch import async_apply_qml_patch_and_confirm
from .repair_issues import DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, repair_issue_id

_AGENT_UPDATE_RESTART_SETTLE_SECONDS = 1.0


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a C300X repair flow."""

    if (
        data is not None
        and data.get("issue_type") == DEVICE_AGENT_UPDATE_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceAgentUpdateRepairFlow(hass, str(data["entry_id"]))
    raise ValueError(f"unknown repair issue: {issue_id}")


class DeviceAgentUpdateRepairFlow(RepairsFlow):
    """Explicit user-confirmed native-agent update repair flow."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm()

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Confirm and run a device-agent self-update."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = (
            update_state.repair_placeholders
            if update_state is not None
            else {
                "installed_version": "unknown",
                "available_version": "unknown",
                "installed_api_version": "unknown",
                "available_api_version": "unknown",
                "reason": "unknown",
            }
        )
        if not getattr(update_state, "self_update_repair_supported", False):
            return await self.async_step_ssh_install(user_input)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )
        try:
            patch_state = await _async_capture_external_patch_state(entry)
            update_result = await async_apply_packaged_agent_update(
                self.hass,
                entry.runtime_data.api,
            )
            setup_data = await _async_verify_agent_after_update(
                entry.runtime_data.api,
                update_result,
            )
            changes = _ExternalPatchChanges.from_update_result(update_result)
            if changes.config_schema_changed:
                await entry.runtime_data.api.async_normalize_agent_config()
                setup_data = await entry.runtime_data.api.async_validate_setup()
            await _async_restore_external_patch_state(
                entry,
                patch_state,
                changes,
            )
            await async_migrate_legacy_mqtt_if_available(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception:  # noqa: BLE001 - Repairs shows a translated failure
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "update_failed"},
                description_placeholders=placeholders,
            )
        await _async_apply_repaired_agent_setup(self.hass, entry, setup_data)
        if entry.runtime_data.agent_update_state.update_required:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "update_verify_failed"},
                description_placeholders=entry.runtime_data.agent_update_state.repair_placeholders,
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, self._entry_id),
        )
        await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
        return self.async_create_entry(data={})

    async def async_step_ssh_install(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Repair an older agent by reinstalling the packaged bundle over SSH."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = (
            update_state.repair_placeholders
            if update_state is not None
            else _unknown_update_placeholders()
        )
        if user_input is None:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                description_placeholders=placeholders,
            )

        try:
            patch_state = await _async_capture_external_patch_state(entry)
            install_result = await async_install_device_agent(
                C300XDeviceInstallRequest(
                    host=str(entry_config_value(entry, CONF_AGENT_HOST, "")).strip(),
                    ssh_username=str(
                        user_input.get(CONF_BOOTSTRAP_SSH_USERNAME, "")
                    ).strip(),
                    ssh_password=str(user_input.get(CONF_BOOTSTRAP_SSH_PASSWORD, "")),
                    agent_port=int(
                        entry_config_value(entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
                    ),
                    apply_firewall_patch=(
                        patch_state.firewall_patched
                        or not patch_state.firewall_status_known
                    ),
                    apply_gui_patch=False,
                ),
                api_token=str(entry_config_value(entry, CONF_AGENT_TOKEN, "")),
                maintenance_token=str(
                    entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")
                ),
            )
            setup_data = await _async_wait_for_agent_after_update(entry.runtime_data.api)
            await _async_restore_external_patch_state(
                entry,
                patch_state,
                _ExternalPatchChanges.from_install_result(install_result),
            )
            await async_migrate_legacy_mqtt_if_available(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception:  # noqa: BLE001 - Repairs shows a translated failure
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                errors={"base": "ssh_install_failed"},
                description_placeholders=placeholders,
            )

        await _async_apply_repaired_agent_setup(self.hass, entry, setup_data)
        if entry.runtime_data.agent_update_state.update_required:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(),
                errors={"base": "update_verify_failed"},
                description_placeholders=entry.runtime_data.agent_update_state.repair_placeholders,
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_AGENT_UPDATE_REQUIRED_ISSUE, self._entry_id),
        )
        await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
        return self.async_create_entry(data={})


async def _async_wait_for_agent_after_update(
    api: Any,
    *,
    initial_delay: float = 0.0,
) -> dict[str, Any]:
    """Wait briefly for the native agent to restart after self-update."""

    last_error: Exception | None = None
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    for _attempt in range(12):
        try:
            return await api.async_validate_setup()
        except Exception as err:  # noqa: BLE001 - retry during controlled restart
            last_error = err
            await asyncio.sleep(1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("agent update verification failed")


async def _async_verify_agent_after_update(
    api: Any,
    update_result: dict[str, Any],
) -> dict[str, Any]:
    """Verify the native agent after an update, waiting only after restarts."""

    if update_result.get("restart_scheduled") is True:
        return await _async_wait_for_agent_after_update(
            api,
            initial_delay=_AGENT_UPDATE_RESTART_SETTLE_SECONDS,
        )
    return await api.async_validate_setup()


async def _async_apply_repaired_agent_setup(
    hass: HomeAssistant,
    entry: Any,
    setup_data: dict[str, Any],
) -> None:
    """Update runtime metadata after a successful agent repair."""

    from .agent_update import async_load_packaged_bundle_metadata

    capabilities = setup_data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
    entry.runtime_data.agent_info = setup_data
    entry.runtime_data.capabilities = gate_capabilities(
        capabilities,
        doorbell_video_enabled=bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False)),
    )
    entry.runtime_data.agent_update_state = compare_agent_bundle(
        setup_data,
        await async_load_packaged_bundle_metadata(hass),
    )
    async_dispatcher_send(hass, SIGNAL_AGENT_INFO_CHANGED, entry.entry_id)


async def _async_reload_entry_after_agent_update(
    hass: HomeAssistant,
    entry_id: str,
) -> None:
    """Reload the entry so newly advertised platforms/entities are created."""

    with suppress(Exception):
        await hass.config_entries.async_reload(entry_id)


class _ExternalPatchState:
    """Read-only snapshot of device-side patches that must survive updates."""

    def __init__(
        self,
        *,
        qml_patch_required: bool,
        firewall_patched: bool,
        firewall_status_known: bool,
        ipv6_firewall_patched: bool,
    ) -> None:
        self.qml_patch_required = qml_patch_required
        self.firewall_patched = firewall_patched
        self.firewall_status_known = firewall_status_known
        self.ipv6_firewall_patched = ipv6_firewall_patched


class _ExternalPatchChanges:
    """Logical device-artifact changes produced by an agent update/install."""

    def __init__(
        self,
        *,
        qml_patch_changed: bool = False,
        firewall_patch_changed: bool = False,
        ipv6_firewall_patch_changed: bool = False,
        config_schema_changed: bool = False,
    ) -> None:
        self.qml_patch_changed = qml_patch_changed
        self.firewall_patch_changed = firewall_patch_changed
        self.ipv6_firewall_patch_changed = ipv6_firewall_patch_changed
        self.config_schema_changed = config_schema_changed

    @classmethod
    def from_update_result(cls, update_result: dict[str, Any]) -> _ExternalPatchChanges:
        """Return changed groups reported by native self-update."""

        return cls(
            qml_patch_changed=update_result.get("qml_patch_changed") is True,
            firewall_patch_changed=update_result.get("firewall_patch_changed") is True,
            ipv6_firewall_patch_changed=(
                update_result.get("ipv6_firewall_patch_changed") is True
            ),
            config_schema_changed=update_result.get("config_schema_changed") is True,
        )

    @classmethod
    def from_install_result(cls, install_result: Any) -> _ExternalPatchChanges:
        """Return changed groups from the SSH installer result."""

        changed_files = tuple(getattr(install_result, "changed_files", ()))
        config_changed = any(path.endswith("/config.json") for path in changed_files)
        firewall_source_changed = any(
            path.endswith("/bootstrap_firewall.sh") for path in changed_files
        )
        qml_changed = any(
            "/qml/" in path or path.endswith("/qml_patch.sh")
            for path in changed_files
        )
        return cls(
            qml_patch_changed=qml_changed,
            firewall_patch_changed=firewall_source_changed,
            ipv6_firewall_patch_changed=config_changed or firewall_source_changed,
            config_schema_changed=config_changed,
        )


async def _async_capture_external_patch_state(entry: Any) -> _ExternalPatchState:
    """Capture active patch state without mutating the device."""

    api = entry.runtime_data.api
    qml_status = getattr(entry.runtime_data, "qml_patch_status", {})
    try:
        qml_status = await api.async_qml_patch_status()
        entry.runtime_data.qml_patch_status = qml_status
    except C300XAgentApiError:
        pass

    firewall_patched = False
    firewall_status_known = False
    try:
        firewall_status = await api.async_firewall_status()
        firewall_patched = firewall_status.get("patched") is True
        firewall_status_known = firewall_status.get("patched") is not None
    except C300XAgentApiError:
        pass

    ipv6_firewall_patched = False
    try:
        ipv6_firewall_status = await api.async_ipv6_firewall_status()
        ipv6_firewall_patched = ipv6_firewall_status.get("patched") is True
    except C300XAgentApiError:
        pass

    return _ExternalPatchState(
        qml_patch_required=(
            entry_device_ui_enabled(entry) or qml_patch_status_is_active(qml_status)
        ),
        firewall_patched=firewall_patched,
        firewall_status_known=firewall_status_known,
        ipv6_firewall_patched=ipv6_firewall_patched,
    )


async def _async_restore_external_patch_state(
    entry: Any,
    patch_state: _ExternalPatchState,
    changed: _ExternalPatchChanges,
) -> None:
    """Re-apply active external patches only when their patch source changed."""

    api = entry.runtime_data.api
    if patch_state.firewall_patched and changed.firewall_patch_changed:
        await api.async_apply_firewall()
    if patch_state.ipv6_firewall_patched and changed.ipv6_firewall_patch_changed:
        with suppress(C300XAgentApiError):
            await api.async_set_ipv6_firewall_enabled(True)
        await api.async_apply_ipv6_firewall()
    if patch_state.qml_patch_required and changed.qml_patch_changed:
        await async_apply_qml_patch_and_confirm(entry)


def _ssh_install_schema() -> vol.Schema:
    """Return the SSH repair schema for agents without self-update support."""

    return vol.Schema(
        {
            vol.Required(CONF_BOOTSTRAP_SSH_USERNAME): str,
            vol.Required(CONF_BOOTSTRAP_SSH_PASSWORD): str,
        }
    )


def _unknown_update_placeholders() -> dict[str, str]:
    return {
        "installed_version": "unknown",
        "available_version": "unknown",
        "installed_api_version": "unknown",
        "available_api_version": "unknown",
        "reason": "unknown",
    }
