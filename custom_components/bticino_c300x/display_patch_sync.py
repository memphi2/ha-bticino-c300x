"""Apply the Display setting to the device when the settings are applied.

The setting says that it installs the Home Assistant pages on the C300X and
that turning it off restores the original display. Where the setting is
applied - a new entry, the reconfigure, the Display settings submitted -
the entry data gets a mark; the start that follows does it with the agent it
then talks to. The mark stays until the device followed, so a later start
tries again. Other settings saved, and a start without the mark, change
nothing on the device: an entry from before the setting stored it with its
first save of any area, not always as its device has it.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .agent_update import async_retry_update_maintenance_busy
from .api import C300XAgentApiError
from .c100x_display_activation import async_follow_c100x_display, c100x_display_status
from .capabilities import entry_device_ui_configured, maintenance_action_is_advertised
from .const import (
    CONF_DISPLAY_FOLLOWUP_PENDING,
    CONF_DISPLAY_SETTING_PENDING,
    HOME_BUTTONS_LAYOUTS,
    SIGNAL_QML_PATCH_CHANGED,
)
from .display_activation import display_activation_confirmed, display_unsupported
from .display_support import entry_display_supported
from .entry_types import BticinoC300XConfigEntry
from .error_text import compact_error_text
from .qml_patch import (
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_patch_and_confirm,
    entry_home_buttons,
)

_LOGGER = logging.getLogger(__name__)


def _differs(status: dict[str, Any], wanted: bool, home_buttons: str) -> bool | None:
    """Whether the device differs from the setting; None when it does not say.

    Both home page layouts are patched, so an installed page also differs when
    it reports the other layout. An agent that does not report the layout is
    taken at its patched state: asking it again would never end.
    """

    if status.get("qt5_overlay") == "failed" or display_unsupported(status):
        # Repeated setup/settings saves must not retry a quarantined overlay,
        # nor a display the agent does not know.
        return None
    if status.get("qt5_overlay") == "incomplete" and not wanted:
        # A restore keeps the core hook packed and writes the resource file
        # back: after the way out of a restart loop (the file renamed) that
        # starts the loop again. The core Repair is raised for it.
        return None
    patched = status.get("patched")
    if isinstance(patched, bool):
        if patched is not wanted:
            return True
        if not display_activation_confirmed(status, required=wanted):
            return True if status.get("qt5_overlay") in ("incomplete", "off") and wanted else None
        installed = status.get("home_buttons")
        return wanted and installed in HOME_BUTTONS_LAYOUTS and installed != home_buttons
    # Only some of the files are there: neither the pages nor the original.
    return True if status.get("state") == "partial" else None


async def async_apply_display_setting(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry
) -> bool | None:
    """Apply or restore the Display patch as the Display setting says.

    True: applied or restored. False: nothing to do, also for an entry without
    the setting or an agent that has no Display patch. None: the device could
    not be asked or did not follow, so it is still to do.
    """

    wanted = entry_device_ui_configured(entry)
    if not entry_display_supported(entry):
        return False
    runtime_data: Any = getattr(entry, "runtime_data", None)
    if wanted is None:
        return False
    capabilities = getattr(runtime_data, "capabilities", None)
    if not capabilities:
        return None
    c100x = c100x_display_status(capabilities)
    if c100x is not None:
        return await _async_apply_c100x_setting(hass, entry, wanted, c100x)
    if not maintenance_action_is_advertised(capabilities, "qml_patch" if wanted else "qml_restore"):
        return False
    run = async_apply_qml_patch_and_confirm if wanted else async_restore_qml_patch_and_confirm
    home_buttons = entry_home_buttons(entry)
    try:
        differs = _differs(await async_refresh_qml_patch_status(entry, wait_busy=True), wanted, home_buttons)
        if differs is False and wanted and CONF_DISPLAY_FOLLOWUP_PENDING in entry.data:
            # Pages of the earlier agent read as patched; an update or install
            # still owes the new ones. A quarantined or unknown display (None)
            # stays with the core Repair.
            differs = True
        if not differs:
            return None if differs is None else False
        status = await async_retry_update_maintenance_busy(
            lambda: run(
                entry, lambda: async_dispatcher_send(hass, SIGNAL_QML_PATCH_CHANGED, entry.entry_id)
            )
        )
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X Display patch was not %s for the Display setting: %s",
            "applied" if wanted else "restored",
            compact_error_text(err),
        )
        return None
    if _differs(status, wanted, home_buttons) is not False:
        _LOGGER.warning("C300X Display patch did not reach the state of the Display setting")
        return None
    return True


async def _async_apply_c100x_setting(
    hass: HomeAssistant, entry: BticinoC300XConfigEntry, wanted: bool, status: Any
) -> bool | None:
    """C100X: the pages come with their button; the setting turned off restores the display."""

    if wanted or status.get("confirmed") is not True:
        return False
    try:
        await entry.runtime_data.api.async_c100x_display_restore()
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C100X display was not restored for the Display setting: %s", compact_error_text(err)
        )
        return None
    async_follow_c100x_display(hass, entry)
    return True


def display_setting_pending(entry: BticinoC300XConfigEntry) -> bool:
    """Whether this start applies the Display setting to the device."""

    return CONF_DISPLAY_SETTING_PENDING in entry.data


def async_mark_display_setting(hass: HomeAssistant, entry: BticinoC300XConfigEntry, *, pending: bool) -> None:
    """Mark the Display setting as to be applied at the next start, or done."""

    if (CONF_DISPLAY_SETTING_PENDING in entry.data) is pending:
        return
    data = dict(entry.data)
    if pending:
        data[CONF_DISPLAY_SETTING_PENDING] = True
    else:
        del data[CONF_DISPLAY_SETTING_PENDING]
    hass.config_entries.async_update_entry(entry, data=data)


async def async_settle_display_setting(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Apply the Display setting and keep it marked until the device followed."""

    applied = await async_apply_display_setting(hass, entry)
    if applied is not None:
        async_mark_display_setting(hass, entry, pending=False)
    if applied is True and entry_device_ui_configured(entry) and CONF_DISPLAY_FOLLOWUP_PENDING in entry.data:
        data = dict(entry.data)
        del data[CONF_DISPLAY_FOLLOWUP_PENDING]
        hass.config_entries.async_update_entry(entry, data=data)

