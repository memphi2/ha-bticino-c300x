"""Home Assistant Repairs flows for BTicino C300X."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, cast

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .agent_update import (
    agent_update_repair_placeholders,
    async_apply_packaged_agent_update,
    compare_agent_bundle,
)
from .api import C300XAgentApiError
from .callback_url import async_suggest_callback_base_url, normalize_callback_base_url
from .capabilities import (
    entry_device_ui_enabled,
    gate_capabilities,
    maintenance_action_is_advertised,
    qml_patch_status_is_active,
)
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
    DEFAULT_AGENT_PORT,
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEVICE_ACTIVATION_MODE_AUTO,
    DOMAIN,
    SIGNAL_AGENT_INFO_CHANGED,
    SIGNAL_CONNECTION_STATE_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
    SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT,
)
from .device_installer import (
    C300XDeviceInstallRequest,
    async_install_device_agent,
)
from .device_user import homeassistant_account_label
from .entry_config import entry_config_value
from .media_readiness import media_readiness
from .mqtt_migration import async_migrate_legacy_mqtt_if_available
from .qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
)
from .repair_flows_device_user import DeviceUserRepairFlow
from .repair_flows_frontend import FrontendCardSetupRepairFlow
from .repair_issues import (
    AGENT_CAPABILITY_MISMATCH_ISSUE,
    DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
    DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
    DEVICE_USER_REQUIRED_ISSUE,
    FRONTEND_CARD_SETUP_HINT_ISSUE,
    MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
    UNSUPPORTED_CALLBACK_URL_ISSUE,
    repair_issue_id,
)

_AGENT_UPDATE_RESTART_SETTLE_SECONDS = 1.0

__all__ = (
    "CallbackUrlRepairFlow",
    "DeviceAgentUpdateRepairFlow",
    "DeviceCoreQmlHookRepairFlow",
    "DeviceUserRepairFlow",
    "FrontendCardSetupRepairFlow",
    "MediaSetupRepairFlow",
    "async_create_fix_flow",
)


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a C300X repair flow."""

    if (
        data is not None
        and data.get("issue_type")
        in {
            AGENT_CAPABILITY_MISMATCH_ISSUE,
            DEVICE_AGENT_UPDATE_REQUIRED_ISSUE,
        }
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceAgentUpdateRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == UNSUPPORTED_CALLBACK_URL_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return CallbackUrlRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceCoreQmlHookRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == DEVICE_USER_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return DeviceUserRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == MEDIA_SETUP_REPAIR_REQUIRED_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return MediaSetupRepairFlow(hass, str(data["entry_id"]))
    if (
        data is not None
        and data.get("issue_type") == FRONTEND_CARD_SETUP_HINT_ISSUE
        and isinstance(data.get("entry_id"), str)
    ):
        return FrontendCardSetupRepairFlow(hass, str(data["entry_id"]))
    raise ValueError(f"unknown repair issue: {issue_id}")


class MediaSetupRepairFlow(RepairsFlow):
    """Guided repair flow for local C300X media prerequisites."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm(None)

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Repair explicitly confirmed media setup prerequisites."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        readiness = media_readiness(entry)
        placeholders = _media_setup_repair_placeholders(readiness)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders=placeholders,
            )
        try:
            repaired = await _async_repair_media_setup(self.hass, entry)
        except C300XAgentApiError:
            return self.async_show_form(
                step_id="confirm",
                errors={"base": "media_setup_repair_failed"},
                description_placeholders=placeholders,
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(
                MEDIA_SETUP_REPAIR_REQUIRED_ISSUE,
                self._entry_id,
            ),
        )
        return self.async_create_entry(data={"repaired": repaired})


async def _async_repair_media_setup(hass: HomeAssistant, entry: Any) -> list[str]:
    """Run the safe media setup repairs selected by current readiness."""

    readiness = media_readiness(entry)
    failed = readiness.get("failed_checks")
    failed_checks = {str(check) for check in failed} if isinstance(failed, list) else set()
    repaired: list[str] = []
    if "agent_reachable" in failed_checks:
        await _async_reload_entry_after_agent_update(hass, entry.entry_id)
        repaired.append("agent_reachable_check")
        return repaired
    if failed_checks & {"capabilities", "rtsp"}:
        setup_data = await entry.runtime_data.api.async_validate_setup()
        await _async_apply_repaired_agent_setup(hass, entry, setup_data)
        repaired.append("agent_update_check")
    if failed_checks & {"firewall", "talkback_rtp"}:
        await entry.runtime_data.api.async_set_firewall_enabled(True)
        await entry.runtime_data.api.async_apply_firewall()
        repaired.append("firewall")
    if failed_checks & {"homeassistant_user", "device_routing"}:
        status = await entry.runtime_data.api.async_ensure_homeassistant_user(
            account_label=homeassistant_account_label(hass)
        )
        entry.runtime_data.device_user_status = status
        repaired.append("homeassistant_user")
    if "forwarding_homeassistant" in failed_checks:
        status = await entry.runtime_data.api.async_set_smartphone_forwarding_mode(
            SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT
        )
        entry.runtime_data.event_state.smartphone_forwarding_mode = status.get(
            "state",
            SMARTPHONE_FORWARDING_MODE_HOME_ASSISTANT,
        )
        repaired.append("forwarding_homeassistant")
    if repaired:
        with suppress(C300XAgentApiError):
            entry.runtime_data.self_test_status = await entry.runtime_data.api.async_self_test()
        with suppress(C300XAgentApiError):
            entry.runtime_data.device_user_status = (
                await entry.runtime_data.api.async_device_user_status()
            )
        async_dispatcher_send(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)
    return repaired


def _media_setup_repair_placeholders(readiness: dict[str, Any]) -> dict[str, str]:
    """Return user-facing placeholders for the media setup repair."""

    failed = readiness.get("failed_checks")
    warnings = readiness.get("warnings")
    return {
        "failed_checks": ", ".join(str(check) for check in failed)
        if isinstance(failed, list) and failed
        else "unknown",
        "warnings": ", ".join(str(warning) for warning in warnings)
        if isinstance(warnings, list) and warnings
        else "none",
        "recommended_action": str(readiness.get("recommended_action") or "unknown"),
    }


class CallbackUrlRepairFlow(RepairsFlow):
    """Repair flow for callback targets the C300X cannot reach."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the callback URL repair flow."""

        return await self.async_step_configure(user_input)

    async def async_step_configure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Store a local HTTP callback base URL override."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")

        errors: dict[str, str] = {}
        if user_input is not None:
            callback_base_url = _validated_callback_base_url(user_input, errors)
            if callback_base_url:
                self.hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **dict(entry.options),
                        CONF_CALLBACK_BASE_URL: callback_base_url,
                    },
                )
                ir.async_delete_issue(
                    hass=self.hass,
                    domain=DOMAIN,
                    issue_id=repair_issue_id(
                        UNSUPPORTED_CALLBACK_URL_ISSUE,
                        self._entry_id,
                    ),
                )
                await _async_reload_entry_after_agent_update(self.hass, self._entry_id)
                return self.async_create_entry(data={})
            errors[CONF_CALLBACK_BASE_URL] = "invalid_callback_base_url"

        suggested = await async_suggest_callback_base_url(self.hass, entry)
        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CALLBACK_BASE_URL,
                        default=suggested,
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "suggested_callback_base_url": suggested or "http://HA_LOCAL_IP:8123",
            },
        )


class DeviceCoreQmlHookRepairFlow(RepairsFlow):
    """Repair flow for the core media QML hook used by video session tracking."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Apply the minimal core QML hook after explicit confirmation."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        capabilities = getattr(entry.runtime_data, "capabilities", {})
        if not maintenance_action_is_advertised(capabilities, "qml_core_patch"):
            return self.async_abort(reason="core_patch_unsupported")
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        try:
            status = await async_apply_qml_core_patch_and_confirm(
                entry,
                lambda: async_dispatcher_send(
                    self.hass,
                    SIGNAL_QML_PATCH_CHANGED,
                    entry.entry_id,
                ),
            )
        except C300XAgentApiError:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_failed"},
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        if status.get("core_patched") is not True:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_verify_failed"},
                description_placeholders={
                    "qml_patch_status": _runtime_qml_patch_status(entry),
                },
            )
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(
                DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
                self._entry_id,
            ),
        )
        return self.async_create_entry(data={})


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
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
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
                description_placeholders=agent_update_repair_placeholders(
                    entry.runtime_data.agent_update_state,
                    entry.runtime_data,
                ),
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
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
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
                    device_activation_mode=str(
                        entry_config_value(
                            entry,
                            CONF_DEVICE_ACTIVATION_MODE,
                            DEVICE_ACTIVATION_MODE_AUTO,
                        )
                    ),
                    device_activation_stair_light_address=str(
                        entry_config_value(
                            entry,
                            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS,
                            DEFAULT_STAIR_LIGHT_ADDRESS,
                        )
                    ),
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
                description_placeholders=agent_update_repair_placeholders(
                    entry.runtime_data.agent_update_state,
                    entry.runtime_data,
                ),
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
            return cast(dict[str, Any], await api.async_validate_setup())
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
    return cast(dict[str, Any], await api.async_validate_setup())


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
        runtime_changed: bool = False,
        qml_patch_changed: bool = False,
        firewall_patch_changed: bool = False,
        ipv6_firewall_patch_changed: bool = False,
        config_schema_changed: bool = False,
    ) -> None:
        self.runtime_changed = runtime_changed
        self.qml_patch_changed = qml_patch_changed
        self.firewall_patch_changed = firewall_patch_changed
        self.ipv6_firewall_patch_changed = ipv6_firewall_patch_changed
        self.config_schema_changed = config_schema_changed

    @classmethod
    def from_update_result(cls, update_result: dict[str, Any]) -> _ExternalPatchChanges:
        """Return changed groups reported by native self-update."""

        return cls(
            runtime_changed=update_result.get("runtime_changed") is True,
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
        runtime_changed = any(
            path.endswith("/c300x-agent-native")
            or path.endswith("/c300x-native-agent")
            for path in changed_files
        )
        config_changed = any(path.endswith("/config.json") for path in changed_files)
        firewall_source_changed = any(
            path.endswith("/bootstrap_firewall.sh") for path in changed_files
        )
        qml_changed = any(
            "/qml/" in path or path.endswith("/qml_patch.sh")
            for path in changed_files
        )
        return cls(
            runtime_changed=runtime_changed,
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
    if changed.qml_patch_changed:
        entry.runtime_data.qml_patch_status = await api.async_apply_qml_core_patch()
        if patch_state.qml_patch_required:
            await async_apply_qml_patch_and_confirm(entry)
        await api.async_reload_gui()
        entry.runtime_data.qml_patch_status = await api.async_qml_patch_status()
    elif changed.runtime_changed and patch_state.qml_patch_required:
        await api.async_reload_gui()


def _ssh_install_schema() -> vol.Schema:
    """Return the SSH repair schema for agents without self-update support."""

    return vol.Schema(
        {
            vol.Required(CONF_BOOTSTRAP_SSH_USERNAME): str,
            vol.Required(CONF_BOOTSTRAP_SSH_PASSWORD): str,
        }
    )


def _validated_callback_base_url(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> str:
    """Validate a required local callback base URL for the repair flow."""

    try:
        return normalize_callback_base_url(user_input.get(CONF_CALLBACK_BASE_URL, ""))
    except ValueError:
        errors[CONF_CALLBACK_BASE_URL] = "invalid_callback_base_url"
        return ""


def _runtime_qml_patch_status(entry: Any) -> str:
    status = getattr(getattr(entry, "runtime_data", None), "qml_patch_status", {})
    if isinstance(status, dict):
        core_state = str(status.get("core_state") or "").strip()
        if core_state:
            return core_state
        state = str(status.get("state") or "").strip()
        if state:
            return state
    return "unknown"
