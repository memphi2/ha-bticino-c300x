"""Home Assistant Repairs flows for BTicino C300X."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, cast

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .agent_update import (
    agent_update_repair_placeholders,
    async_apply_packaged_agent_update,
    async_load_packaged_bundle_metadata,
    async_retry_update_maintenance_busy,
    compare_agent_bundle,
)
from .agent_update_followup import (
    async_full_patch_due,
    clear_followup,
    followup_mark,
    followup_unconfirmed,
)
from .api import C300XAgentApiError
from .api_errors import C300XAgentApiUnsupportedError, C300XAgentUpdateError
from .c100x_display_activation import async_renew_c100x_display_after_update
from .callback_url import async_suggest_callback_base_url
from .callback_url import (
    validated_callback_base_url as _validated_callback_base_url,
)
from .capabilities import (
    entry_device_ui_configured,
    entry_device_ui_enabled,
    gate_capabilities,
    maintenance_action_is_advertised,
    qml_patch_status_is_active,
)
from .config_flow_forms import ssh_key_fields
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_AGENT_UPDATE_PAYLOAD_PENDING,
    CONF_AGENT_UPDATE_QML_PENDING,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
    DEFAULT_AGENT_PORT,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_MODE_AUTO,
    DOMAIN,
    SIGNAL_AGENT_INFO_CHANGED,
    SIGNAL_CONNECTION_STATE_CHANGED,
    SIGNAL_QML_PATCH_CHANGED,
)
from .device_installer import (
    DISPLAY_WRITE_TIMEOUT,
    FIREWALL_HOOK_CHANGED,
    C300XDeviceInstallError,
    C300XDeviceInstallRequest,
    async_ensure_installer_dependencies,
    async_install_device_agent,
)
from .device_profile import C3X2_NOT_SUPPORTED, NOT_A_BTICINO_STATION
from .device_ssh_login import (
    INVALID_SSH_KEY,
    SSH_PASSWORD_LOGIN_DISABLED,
    SSH_UNREACHABLE,
    SSH_USER_NOT_ROOT,
)
from .device_user import homeassistant_account_label
from .display_activation import display_is_qt5, display_unsupported
from .display_support import setup_is_c100x
from .entry_config import entry_config_value
from .error_text import compact_error_text
from .factory_login import LOGIN_REFUSED, install_login, login_model
from .media_readiness import media_readiness
from .mqtt_migration import async_migrate_legacy_mqtt_if_available
from .qml_patch import (
    async_apply_qml_core_patch_and_confirm,
    async_restore_display_after_update,
    async_restore_qml_patches_after_update,
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
from .repair_work import OTHER_FLOW_FINISHED, RepairStepWork, async_run_repair_step
from .schema_compat import vol

_LOGGER = logging.getLogger(__name__)

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
        self._work = RepairStepWork(hass, entry_id)

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

        return await async_run_repair_step(
            self, self._work, MEDIA_SETUP_REPAIR_REQUIRED_ISSUE, self._async_confirm, user_input
        )

    async def _async_confirm(self, user_input: dict[str, Any] | None) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
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
        still_failed = _media_checks_still_failed(readiness, media_readiness(entry), repaired)
        if still_failed:
            # The actions ran without an error, but the device still fails
            # the checks they were for. The issue stays open.
            _LOGGER.warning(
                "C300X media setup repair left checks failing: %s",
                ", ".join(still_failed),
            )
            return self.async_show_form(
                step_id="confirm",
                errors={"base": "media_setup_repair_failed"},
                description_placeholders=_media_setup_repair_placeholders(
                    media_readiness(entry)
                ),
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
    if repaired:
        with suppress(C300XAgentApiError):
            entry.runtime_data.self_test_status = await entry.runtime_data.api.async_self_test()
        with suppress(C300XAgentApiError):
            entry.runtime_data.device_user_status = (
                await entry.runtime_data.api.async_device_user_status()
            )
        async_dispatcher_send(hass, SIGNAL_CONNECTION_STATE_CHANGED, entry.entry_id)
    return repaired


_MEDIA_REPAIR_CHECKS = {
    "agent_update_check": {"capabilities", "rtsp"},
    "firewall": {"firewall", "talkback_rtp"},
    "homeassistant_user": {"homeassistant_user", "device_routing"},
}


def _media_checks_still_failed(
    before: dict[str, Any],
    after: dict[str, Any],
    repaired: list[str],
) -> list[str]:
    """Return the checks a repair action was run for that still fail.

    A reload for an unreachable agent is not judged: the readiness of the
    entry is only known after the reload.
    """

    def failed(readiness: dict[str, Any]) -> set[str]:
        checks = readiness.get("failed_checks")
        return {str(check) for check in checks} if isinstance(checks, list) else set()

    targeted: set[str] = set()
    for action in repaired:
        targeted |= _MEDIA_REPAIR_CHECKS.get(action, set())
    return sorted(failed(before) & failed(after) & targeted)


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
        self._work = RepairStepWork(hass, entry_id)

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

        return await async_run_repair_step(
            self, self._work, UNSUPPORTED_CALLBACK_URL_ISSUE, self._async_configure, user_input
        )

    async def _async_configure(self, user_input: dict[str, Any] | None) -> Any:
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
        self._work = RepairStepWork(hass, entry_id)

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

        return await async_run_repair_step(
            self, self._work, DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE, self._async_confirm, user_input
        )

    async def _async_confirm(self, user_input: dict[str, Any] | None) -> Any:
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
                description_placeholders=_core_hook_placeholders(entry),
            )
        try:
            if CONF_DISPLAY_FOLLOWUP_PENDING in entry.data:
                # What an update or install left undone: the whole sequence.
                status = await async_restore_qml_patches_after_update(
                    entry,
                    apply_full_patch=entry.data[CONF_DISPLAY_FOLLOWUP_PENDING] is True
                    and entry_device_ui_configured(entry) is not False,
                )
                async_dispatcher_send(self.hass, SIGNAL_QML_PATCH_CHANGED, entry.entry_id)
                _settle_display_followup(self.hass, entry, True, full=False)
            else:
                status = await async_apply_qml_core_patch_and_confirm(
                    entry,
                    lambda: async_dispatcher_send(
                        self.hass,
                        SIGNAL_QML_PATCH_CHANGED,
                        entry.entry_id,
                    ),
                )
        except C300XAgentApiError:
            if display_unsupported(getattr(entry.runtime_data, "qml_patch_status", None)):
                return self.async_abort(reason="display_unsupported")
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_failed"},
                description_placeholders=_core_hook_placeholders(entry),
            )
        if status.get("core_patched") is not True:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "core_patch_verify_failed"},
                description_placeholders=_core_hook_placeholders(entry),
            )
        # The issue is also raised for a failed status read, and only entry
        # setup cleared that record: without this the next issue sync would
        # raise the issue again although the hook is confirmed.
        diagnostics = getattr(
            getattr(entry.runtime_data, "diagnostics", None), "qml_patch_diagnostics", None
        )
        if diagnostics is not None:
            diagnostics.mark_success(datetime.now(UTC))
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(
                DEVICE_CORE_QML_HOOK_REQUIRED_ISSUE,
                self._entry_id,
            ),
        )
        return self.async_create_entry(data={})


def _ssh_install_error(err: BaseException) -> str:
    """Return the translated error of a failed SSH install."""

    reason = err.reason if isinstance(err, C300XDeviceInstallError) else ""
    shown = (
        LOGIN_REFUSED, DISPLAY_WRITE_TIMEOUT, NOT_A_BTICINO_STATION, INVALID_SSH_KEY, SSH_USER_NOT_ROOT,
        SSH_UNREACHABLE, SSH_PASSWORD_LOGIN_DISABLED, FIREWALL_HOOK_CHANGED, C3X2_NOT_SUPPORTED,
    )
    return reason if reason in shown else "ssh_install_failed"


def _install_error_log_text(err: BaseException) -> str:
    """Return the log text of a failed SSH install, with the kind of its cause.

    The installer reports every SSH and OS error as "device_install_failed".
    The type of the original error tells a wrong password from a timeout or a
    failed command; its text is left out, it can name the host.
    """

    text = compact_error_text(cast(Exception, err))
    cause = err.__cause__
    if cause is None:
        return text
    return f"{text} (cause: {type(cause).__name__})"


class DeviceAgentUpdateRepairFlow(RepairsFlow):
    """Explicit user-confirmed native-agent update repair flow."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the repair flow."""

        self.hass = hass
        self._entry_id = entry_id
        # Patch state and changes of an SSH install whose follow-up steps
        # did not finish. A second install changes no file, so it alone
        # would not know that the firewall and config steps are still due.
        # The display step does not rely on this: its mark is in the entry.
        self._ssh_install_followup: (
            tuple[_ExternalPatchState, _ExternalPatchChanges] | None
        ) = None
        self._ask_ssh_login = False
        self._work = RepairStepWork(hass, entry_id)

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Start the repair flow."""

        return await self.async_step_confirm()

    async def _async_run_step(
        self,
        step: Callable[[dict[str, Any] | None], Coroutine[Any, Any, Any]],
        user_input: dict[str, Any] | None,
    ) -> Any:
        """Run a submitted step so that a dropped request cannot end it.

        The update and the reload after it then finish whatever happens to the
        connection of the client that confirmed the repair.
        """

        if user_input is None:
            return await step(None)

        def still_needed() -> bool:
            # After another flow's work for the entry: is an update still due?
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry is None or not hasattr(entry, "runtime_data"):
                # The step itself reports that.
                return True
            update_state = getattr(entry.runtime_data, "agent_update_state", None)
            return bool(getattr(update_state, "update_required", False))

        result = await self._work.async_run(
            lambda: step(user_input), (step.__name__, user_input), still_needed
        )
        if result is OTHER_FLOW_FINISHED:
            return self.async_create_entry(data={})
        return result

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> Any:
        """Confirm and run a device-agent self-update."""

        return await self._async_run_step(self._async_confirm, user_input)

    async def _async_confirm(self, user_input: dict[str, Any] | None) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
        if not getattr(update_state, "self_update_repair_supported", False):
            # Whatever was submitted here was the empty confirm form, not SSH
            # credentials: show the SSH form, do not run an install with it.
            return await self.async_step_ssh_install(None)
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )
        try:
            patch_state = await _async_capture_external_patch_state(entry, require_reliable=True)
            bootstrap = getattr(update_state, "payload_bootstrap_required", False)
            # The follow-up of an earlier update that never finished: the
            # answer of this run says nothing about what that one changed.
            unconfirmed = followup_unconfirmed(entry) or bootstrap
            pending = _followup_mark(entry, patch_state)
            if bootstrap:
                # Between the two passes the display counts as partly
                # patched, which no longer tells whether the patch was
                # active.
                pending[CONF_AGENT_UPDATE_PAYLOAD_PENDING] = True
            _store_entry_data(self.hass, entry, pending)
            update_result = await async_apply_packaged_agent_update(
                self.hass,
                entry.runtime_data.api,
            )
            setup_data = await _async_verify_agent_after_update(
                self.hass,
                entry.runtime_data.api,
                update_result,
            )
            if bootstrap:
                target_bundle = await async_load_packaged_bundle_metadata(self.hass)
                if not target_bundle or compare_agent_bundle(
                    setup_data, target_bundle
                ).payload_bootstrap_required:
                    raise RuntimeError("updated agent cannot install the target file set")
                # The old updater installed the new executable, but not new payload paths.
                # Complete exactly once through the now-running, verified new updater.
                completion = await async_apply_packaged_agent_update(
                    self.hass, entry.runtime_data.api
                )
                setup_data = await _async_verify_agent_after_update(
                    self.hass, entry.runtime_data.api, completion
                )
                for flag in (
                    "runtime_changed", "qml_patch_changed", "script_changed",
                    "firewall_patch_changed", "ipv6_firewall_patch_changed",
                    "config_schema_changed",
                ):
                    update_result[flag] = (
                        update_result.get(flag) is True or completion.get(flag) is True
                    )
            changes = _ExternalPatchChanges.from_update_result(update_result)
            changes.display_unconfirmed = unconfirmed
            if changes.config_schema_changed:
                await async_retry_update_maintenance_busy(
                    entry.runtime_data.api.async_normalize_agent_config
                )
                setup_data = await entry.runtime_data.api.async_validate_setup()
            display_full = _display_followup_full(entry, patch_state)
            display = await _async_restore_external_patch_state(
                entry,
                patch_state,
                changes,
                setup_data,
            )
            _settle_display_followup(self.hass, entry, display, full=display_full)
            await async_renew_c100x_display_after_update(self.hass, entry)
            clear_followup(self.hass, entry)
            await _async_migrate_mqtt_after_update(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception as err:  # noqa: BLE001 - Repairs shows a translated failure
            _LOGGER.warning("C300X agent update failed: %s", compact_error_text(err))
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": err.repair_key if isinstance(err, C300XAgentUpdateError) else "update_failed"},
                description_placeholders=placeholders,
            )
        if entry.data.get(CONF_AGENT_UPDATE_PAYLOAD_PENDING) is True:
            data = dict(entry.data)
            data.pop(CONF_AGENT_UPDATE_PAYLOAD_PENDING)
            self.hass.config_entries.async_update_entry(entry, data=data)
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

        return await self._async_run_step(self._async_ssh_install, user_input)

    async def _async_ssh_install(self, user_input: dict[str, Any] | None) -> Any:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            return self.async_abort(reason="entry_not_loaded")
        update_state = getattr(entry.runtime_data, "agent_update_state", None)
        placeholders = agent_update_repair_placeholders(update_state, entry.runtime_data)
        if user_input is None:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(self._ask_ssh_login),
                description_placeholders=placeholders,
            )
        login = install_login(user_input, login_model(getattr(entry.runtime_data, "agent_info", None)))

        try:
            patch_state = await _async_capture_external_patch_state(entry)
            await async_ensure_installer_dependencies(self.hass)
            unconfirmed = followup_unconfirmed(entry)
            _store_entry_data(self.hass, entry, _followup_mark(entry, patch_state))
            try:
                install_result = await async_install_device_agent(
                    C300XDeviceInstallRequest(
                        host=str(entry_config_value(entry, CONF_AGENT_HOST, "")).strip(),
                        **login,
                        # The entry exists: its station was accepted at setup.
                        c100x_confirmed=True,
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
                        device_activation_stair_light_p=str(
                            entry_config_value(
                                entry,
                                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
                                DEFAULT_STAIR_LIGHT_P,
                            )
                        ),
                        device_activation_stair_light_n=str(
                            entry_config_value(
                                entry,
                                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
                                DEFAULT_STAIR_LIGHT_N,
                            )
                        ),
                        device_activations=tuple(
                            entry_config_value(entry, CONF_DEVICE_ACTIVATIONS, [])
                            or []
                        ),
                    ),
                    api_token=str(entry_config_value(entry, CONF_AGENT_TOKEN, "")),
                    maintenance_token=str(
                        entry_config_value(entry, CONF_MAINTENANCE_TOKEN, "")
                    ),
                )
            except Exception:
                # The installer can fail after it changed files on the device,
                # and their list is lost with the error. A retry then finds
                # every file unchanged, so remember that all follow-up steps
                # are still due.
                every_step = _ExternalPatchChanges(
                    runtime_changed=True,
                    qml_patch_changed=True,
                    firewall_patch_changed=True,
                    ipv6_firewall_patch_changed=True,
                    config_schema_changed=True,
                )
                if self._ssh_install_followup is not None:
                    patch_state = self._ssh_install_followup[0].merged(patch_state)
                self._ssh_install_followup = (patch_state, every_step)
                raise
            changes = _ExternalPatchChanges.from_install_result(install_result)
            if self._ssh_install_followup is not None:
                patch_state = self._ssh_install_followup[0].merged(patch_state)
                changes = self._ssh_install_followup[1].merged(changes)
            self._ssh_install_followup = (patch_state, changes)
            changes.display_unconfirmed = unconfirmed
            setup_data = await _async_wait_for_agent_after_update(entry.runtime_data.api)
            display_full = _display_followup_full(entry, patch_state)
            display = await _async_restore_external_patch_state(
                entry,
                patch_state,
                changes,
                setup_data,
            )
            if display is None and getattr(install_result, "display_pending", False):
                # The installer's core step failed and nothing ran it again.
                display = False
            _settle_display_followup(self.hass, entry, display, full=display_full)
            await async_renew_c100x_display_after_update(self.hass, entry)
            self._ssh_install_followup = None
            clear_followup(self.hass, entry)
            await _async_migrate_mqtt_after_update(entry.runtime_data.api)
            setup_data = await entry.runtime_data.api.async_validate_setup()
        except Exception as err:  # noqa: BLE001 - Repairs shows a translated failure
            _LOGGER.warning("C300X SSH install failed: %s", _install_error_log_text(err))
            # Another login is needed: refused, or one without root rights.
            refused = isinstance(err, C300XDeviceInstallError) and err.reason in (
                LOGIN_REFUSED, SSH_USER_NOT_ROOT, SSH_PASSWORD_LOGIN_DISABLED,
            )
            self._ask_ssh_login = self._ask_ssh_login or refused
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(self._ask_ssh_login),
                errors={"base": _ssh_install_error(err)},
                description_placeholders=placeholders,
            )

        await _async_apply_repaired_agent_setup(self.hass, entry, setup_data)
        if entry.runtime_data.agent_update_state.update_required:
            return self.async_show_form(
                step_id="ssh_install",
                data_schema=_ssh_install_schema(self._ask_ssh_login),
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
    target_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wait briefly for the native agent to restart after self-update."""

    last_error: Exception | None = None
    saw_stale_setup = False
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    for attempt in range(12):
        try:
            setup_data = cast(dict[str, Any], await api.async_validate_setup())
            if target_bundle is None or _agent_setup_matches_bundle(
                setup_data,
                target_bundle,
            ):
                return setup_data
            saw_stale_setup = True
        except Exception as err:  # noqa: BLE001 - retry during controlled restart
            last_error = err
        if attempt < 11:
            await asyncio.sleep(1)
    if last_error is not None and not saw_stale_setup:
        raise last_error
    raise RuntimeError("agent update verification failed")


async def _async_migrate_mqtt_after_update(api: Any) -> None:
    """Run the MQTT migration that ends an update, waiting while the agent is busy."""

    await async_retry_update_maintenance_busy(
        lambda: async_migrate_legacy_mqtt_if_available(api)
    )


async def _async_verify_agent_after_update(
    hass: HomeAssistant,
    api: Any,
    update_result: dict[str, Any],
) -> dict[str, Any]:
    """Verify the native agent after an update against the packaged bundle."""

    target_bundle = await async_load_packaged_bundle_metadata(hass)
    if not target_bundle:
        raise RuntimeError("packaged native-agent bundle is missing")
    if update_result.get("restart_scheduled") is True:
        return await _async_wait_for_agent_after_update(
            api,
            initial_delay=_AGENT_UPDATE_RESTART_SETTLE_SECONDS,
            target_bundle=target_bundle,
        )
    setup_data = cast(dict[str, Any], await api.async_validate_setup())
    if _agent_setup_matches_bundle(setup_data, target_bundle):
        return setup_data
    await async_retry_update_maintenance_busy(api.async_restart_agent)
    return await _async_wait_for_agent_after_update(
        api,
        initial_delay=_AGENT_UPDATE_RESTART_SETTLE_SECONDS,
        target_bundle=target_bundle,
    )


def _agent_setup_matches_bundle(
    setup_data: dict[str, Any],
    target_bundle: dict[str, Any],
) -> bool:
    """Return true when the running agent reports the packaged bundle."""

    state = compare_agent_bundle(setup_data, target_bundle)
    return not state.update_required and not state.payload_bootstrap_required


async def _async_apply_repaired_agent_setup(
    hass: HomeAssistant,
    entry: Any,
    setup_data: dict[str, Any],
) -> None:
    """Update runtime metadata after a successful agent repair."""

    capabilities = setup_data.get("capabilities", {})
    if not isinstance(capabilities, dict):
        capabilities = {}
    entry.runtime_data.agent_info = setup_data
    entry.runtime_data.capabilities = gate_capabilities(
        capabilities,
        doorbell_video_enabled=bool(entry_config_value(entry, CONF_VIDEO_ENABLED, False)),
        c100x=setup_is_c100x(setup_data),
    )
    entry.runtime_data.agent_update_state = compare_agent_bundle(
        setup_data,
        await async_load_packaged_bundle_metadata(hass),
        payload_bootstrap_pending=(
            entry.data.get(CONF_AGENT_UPDATE_PAYLOAD_PENDING) is True
        ),
        qml_patch_pending=CONF_AGENT_UPDATE_QML_PENDING in entry.data,
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

    def merged(self, later: _ExternalPatchState) -> _ExternalPatchState:
        """Return the patches that were active in this or a later snapshot."""

        return _ExternalPatchState(
            qml_patch_required=self.qml_patch_required or later.qml_patch_required,
            firewall_patched=self.firewall_patched or later.firewall_patched,
            firewall_status_known=(
                self.firewall_status_known or later.firewall_status_known
            ),
            ipv6_firewall_patched=(
                self.ipv6_firewall_patched or later.ipv6_firewall_patched
            ),
        )


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
        # An update started earlier never finished its display follow-up:
        # "no display file changed" of this run does not cover that one.
        self.display_unconfirmed = False

    def merged(self, later: _ExternalPatchChanges) -> _ExternalPatchChanges:
        """Return the changes of this and a later install together."""

        return _ExternalPatchChanges(
            runtime_changed=self.runtime_changed or later.runtime_changed,
            qml_patch_changed=self.qml_patch_changed or later.qml_patch_changed,
            firewall_patch_changed=(
                self.firewall_patch_changed or later.firewall_patch_changed
            ),
            ipv6_firewall_patch_changed=(
                self.ipv6_firewall_patch_changed or later.ipv6_firewall_patch_changed
            ),
            config_schema_changed=(
                self.config_schema_changed or later.config_schema_changed
            ),
        )

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


def _followup_mark(entry: Any, patch_state: _ExternalPatchState) -> dict[str, bool]:
    """Return the follow-up mark to store before an update goes to the station."""

    return followup_mark(
        entry,
        display_seen_active=patch_state.qml_patch_required,
        no_display_patch=_agent_offers_no_display_patch(
            getattr(entry.runtime_data, "agent_info", None)
        ),
    )


def _store_entry_data(hass: HomeAssistant, entry: Any, changed: Mapping[str, Any]) -> None:
    if any(key not in entry.data or entry.data[key] is not value for key, value in changed.items()):
        hass.config_entries.async_update_entry(entry, data={**entry.data, **changed})


async def _async_capture_external_patch_state(
    entry: Any, *, require_reliable: bool = False,
) -> _ExternalPatchState:
    """Capture active patch state without mutating the device."""

    api = entry.runtime_data.api

    async def read(status: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        if not require_reliable:
            return await status()
        result: dict[str, Any] = await async_retry_update_maintenance_busy(status)
        return result

    qml_status = getattr(entry.runtime_data, "qml_patch_status", {})
    try:
        qml_status = await read(api.async_qml_patch_status)
        entry.runtime_data.qml_patch_status = qml_status
    except C300XAgentApiUnsupportedError:
        pass
    except C300XAgentApiError:
        if require_reliable:
            raise
        pass

    firewall_patched = False
    firewall_status_known = False
    try:
        firewall_status = await read(api.async_firewall_status)
        firewall_patched = firewall_status.get("patched") is True
        firewall_status_known = firewall_status.get("patched") is not None
    except C300XAgentApiUnsupportedError:
        pass
    except C300XAgentApiError:
        if require_reliable:
            raise
        pass

    ipv6_firewall_patched = False
    try:
        ipv6_firewall_status = await read(api.async_ipv6_firewall_status)
        ipv6_firewall_patched = ipv6_firewall_status.get("patched") is True
    except C300XAgentApiUnsupportedError:
        pass
    except C300XAgentApiError:
        if require_reliable:
            raise
        pass

    return _ExternalPatchState(
        qml_patch_required=(
            entry_device_ui_enabled(entry) or qml_patch_status_is_active(qml_status)
        ),
        firewall_patched=firewall_patched,
        firewall_status_known=firewall_status_known,
        ipv6_firewall_patched=ipv6_firewall_patched,
    )


def _agent_offers_no_display_patch(setup_data: Mapping[str, Any] | None) -> bool:
    """Return whether an agent with maintenance says it has no Display patch.

    Only an explicit answer counts: without a maintenance block the display
    steps run as before and report their own outcome.
    """

    capabilities = setup_data.get("capabilities") if isinstance(setup_data, Mapping) else None
    maintenance = capabilities.get("maintenance") if isinstance(capabilities, Mapping) else None
    return (
        isinstance(maintenance, Mapping)
        and maintenance.get("supported") is True
        and maintenance.get("qml_core_patch") is False
    )


async def _async_restore_external_patch_state(
    entry: Any,
    patch_state: _ExternalPatchState,
    changed: _ExternalPatchChanges,
    setup_data: Mapping[str, Any] | None = None,
) -> bool | None:
    """Run the follow-up of an update: re-apply what the station needs again.

    The firewall steps run when their source changed. The display step is
    decided here, when it runs: an answer that reports changed display files
    re-applies the hooks, as does an update whose follow-up was never
    confirmed (``changed.display_unconfirmed``). The second is a check first:
    the station compares before it writes, and pages that are current are
    neither written nor restarted. Whether the full Display patch belongs to
    it follows the Display setting of this moment.

    On the Qt 5 display of firmware 3.0.x the overlay's preload library is
    part of the agent runtime: a runtime change re-applies the hooks, and a
    follow-up without the update's answer restarts the display once.

    ``setup_data`` is the setup payload of the agent just installed. When it
    says the agent offers no Display patch, the display steps are skipped.
    Returns None when no display step ran, True when the display steps ran
    and were confirmed, False when they ran and failed on the Qt 5 display
    (``_settle_display_followup`` records them as owed).
    """

    api = entry.runtime_data.api
    busy_retry = async_retry_update_maintenance_busy
    if patch_state.firewall_patched and changed.firewall_patch_changed:
        await busy_retry(api.async_apply_firewall)
    if patch_state.ipv6_firewall_patched and changed.ipv6_firewall_patch_changed:
        with suppress(C300XAgentApiError):
            await busy_retry(lambda: api.async_set_ipv6_firewall_enabled(True))
        await busy_retry(api.async_apply_ipv6_firewall)
    if _agent_offers_no_display_patch(setup_data):
        return None
    qt5 = display_is_qt5(entry)
    owed = CONF_DISPLAY_FOLLOWUP_PENDING in entry.data

    async def full_patch_due() -> bool:
        return await async_full_patch_due(
            entry,
            display_seen_active=(
                patch_state.qml_patch_required
                or entry.data.get(CONF_DISPLAY_FOLLOWUP_PENDING) is True
            ),
        )

    if changed.qml_patch_changed or (changed.runtime_changed and qt5):
        return await async_restore_display_after_update(
            entry,
            apply_full_patch=await full_patch_due(),
            # Qt 5: a write restarts the display itself; only a new runtime
            # without such a write still needs the one restart.
            reload_unchanged=not qt5 or changed.runtime_changed,
        )
    if changed.display_unconfirmed or owed:
        full_patch = await full_patch_due()
        return await async_restore_display_after_update(
            entry,
            apply_full_patch=full_patch,
            # Owed steps and an update answer that never came on Qt 5: whether
            # the runtime with the preload library changed is not known.
            reload_unchanged=qt5 or owed or (changed.runtime_changed and full_patch),
        )
    if changed.runtime_changed and await full_patch_due():
        await busy_retry(api.async_reload_gui)
    return None


def _display_followup_full(entry: Any, patch_state: _ExternalPatchState) -> bool:
    """Whether the follow-up brings the full Display patch back, not only the core hook."""

    return (
        patch_state.qml_patch_required
        or entry.data.get(CONF_AGENT_UPDATE_QML_PENDING) is True
        or entry.data.get(CONF_DISPLAY_FOLLOWUP_PENDING) is True
    )


def _settle_display_followup(
    hass: HomeAssistant, entry: Any, outcome: bool | None, *, full: bool,
) -> None:
    """Record the display steps an update or install still owes, or clear them.

    Owed steps keep their own record after the agent update itself is done:
    the core Repair runs them again (the full patch when it was on) and the
    Display setting sync notices them.
    """

    if outcome is None:
        return
    data = dict(entry.data)
    if outcome:
        if data.pop(CONF_DISPLAY_FOLLOWUP_PENDING, None) is None:
            return
    else:
        data[CONF_DISPLAY_FOLLOWUP_PENDING] = full or data.get(CONF_DISPLAY_FOLLOWUP_PENDING) is True
    hass.config_entries.async_update_entry(entry, data=data)


def _ssh_install_schema(ask_login: bool) -> vol.Schema:
    """Return the SSH repair schema for agents without self-update support.

    The factory login is used until the device refused it; then a login is asked for.
    """

    if not ask_login:
        return vol.Schema({})
    return vol.Schema(
        {
            vol.Optional(CONF_BOOTSTRAP_SSH_USERNAME, default=""): str,
            vol.Optional(CONF_BOOTSTRAP_SSH_PASSWORD, default=""): str,
            **ssh_key_fields(),
        }
    )


def _core_hook_placeholders(entry: Any) -> dict[str, str]:
    """Placeholders of the core hook confirm step, also its owed-steps text."""

    return {
        "qml_patch_status": _runtime_qml_patch_status(entry),
        "entry_title": str(getattr(entry, "title", "") or entry.entry_id),
    }


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
