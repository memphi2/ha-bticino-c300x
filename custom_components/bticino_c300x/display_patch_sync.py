"""Apply the Display setting to the device when the settings are applied.

The setting says that it installs the Home Assistant pages on the C300X and
that turning it off restores the original display. So saving the settings, and
the first start of a new entry, bring the Display patch in line with it. A
plain restart changes nothing on the device.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import C300XAgentApiError
from .capabilities import entry_device_ui_configured, maintenance_action_is_advertised
from .const import SIGNAL_QML_PATCH_CHANGED
from .entry_types import BticinoC300XConfigEntry
from .error_text import compact_error_text
from .qml_patch import (
    async_apply_qml_patch_and_confirm,
    async_refresh_qml_patch_status,
    async_restore_qml_patch_and_confirm,
)

_LOGGER = logging.getLogger(__name__)


async def async_apply_display_setting(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> bool:
    """Apply or restore the Display patch as the Display setting says.

    Returns whether the patch was applied or restored. An entry without the
    setting, an agent without the Display patch, or a status that cannot be
    read leaves the device as it is.
    """

    wanted = entry_device_ui_configured(entry)
    runtime_data: Any = getattr(entry, "runtime_data", None)
    if wanted is None or runtime_data is None:
        return False
    action = "qml_patch" if wanted else "qml_restore"
    if not maintenance_action_is_advertised(runtime_data.capabilities, action):
        return False
    try:
        status = await async_refresh_qml_patch_status(entry)
        if status.get("patched") is not (not wanted):
            return False
        run = async_apply_qml_patch_and_confirm if wanted else async_restore_qml_patch_and_confirm
        status = await run(
            entry, lambda: async_dispatcher_send(hass, SIGNAL_QML_PATCH_CHANGED, entry.entry_id)
        )
    except C300XAgentApiError as err:
        _LOGGER.warning(
            "C300X Display patch was not %s for the Display setting: %s",
            "applied" if wanted else "restored",
            compact_error_text(err),
        )
        return False
    if status.get("patched") is not wanted:
        _LOGGER.warning("C300X Display patch did not reach the state of the Display setting")
    return True


def async_schedule_display_setting(hass: HomeAssistant, entry: BticinoC300XConfigEntry) -> None:
    """Apply the Display setting in the background.

    For the Display settings submitted as they are: nothing is saved then, so
    no reload brings a device that differs in line.
    """

    if getattr(entry, "runtime_data", None) is None:
        return
    entry.async_create_background_task(
        hass, async_apply_display_setting(hass, entry), "c300x_display_setting"
    )
