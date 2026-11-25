"""The mark for the display follow-up of an agent update.

The station applies an update by itself once it has the files. Home Assistant
then re-applies the display hooks. Whether that is still due cannot be read
from how one request ended: an answer can be lost, can report a failure after
the files were written, or Home Assistant can stop before it arrives.

So the mark in the entry data says one thing only: an update of this station
was started and its follow-up has not run to its end. It is set before
anything is sent to the station and removed in one place, after the follow-up.
What the follow-up does is decided when it runs, from the Display setting and
the station's answers of that moment.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .capabilities import entry_device_ui_configured, qml_patch_status_is_active
from .const import CONF_AGENT_UPDATE_QML_PENDING
from .qml_patch import async_refresh_qml_patch_status


def followup_unconfirmed(entry: Any) -> bool:
    """Return whether an update was started whose follow-up has not finished."""

    return CONF_AGENT_UPDATE_QML_PENDING in entry.data


def followup_mark(
    entry: Any, *, display_seen_active: bool, no_display_patch: bool,
) -> dict[str, bool]:
    """Return the entry data to store before an update is sent to the station.

    Empty when the station's agent offers no display patch
    (``no_display_patch``) and no earlier update is open: such an update has
    no display follow-up.

    The value keeps whether the Display patch was seen active before an
    update. The update can replace the script that reports this, so it cannot
    always be read again afterwards. It decides nothing against a setting the
    user has chosen, see ``async_full_patch_due``.
    """

    earlier = entry.data.get(CONF_AGENT_UPDATE_QML_PENDING)
    if earlier is None and no_display_patch:
        return {}
    return {CONF_AGENT_UPDATE_QML_PENDING: display_seen_active or earlier is True}


def clear_followup(hass: HomeAssistant, entry: Any) -> None:
    """Remove the mark: the follow-up ran to its end."""

    if CONF_AGENT_UPDATE_QML_PENDING in entry.data:
        data = dict(entry.data)
        data.pop(CONF_AGENT_UPDATE_QML_PENDING)
        hass.config_entries.async_update_entry(entry, data=data)


async def async_full_patch_due(entry: Any, *, display_seen_active: bool) -> bool:
    """Return whether the follow-up re-applies the full Display patch, as of now.

    The Display setting of this moment decides. Where the user never chose
    one, an older entry, the patch seen active before the update counts. A
    setting that is off wins over what was seen or stored earlier; only a
    station that reports the patch active right now is still refreshed.
    """

    configured = entry_device_ui_configured(entry)
    if configured:
        return True
    seen = display_seen_active or entry.data.get(CONF_AGENT_UPDATE_QML_PENDING) is True
    if not seen:
        return False
    if configured is None:
        return True
    return qml_patch_status_is_active(
        await async_refresh_qml_patch_status(entry, wait_busy=True)
    )
