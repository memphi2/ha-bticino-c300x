"""Device-user repair flow for BTicino C300X."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .api import C300XAgentApiError
from .const import DOMAIN
from .device_user import homeassistant_account_label
from .repair_issues import DEVICE_USER_REQUIRED_ISSUE, repair_issue_id


class DeviceUserRepairFlow(RepairsFlow):
    """Repair flow that creates or repairs the dedicated HA media user."""

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
        """Create or repair the Home Assistant Flexisip user."""

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_loaded")
        if user_input is None:
            return self.async_show_form(step_id="confirm")
        try:
            status = await entry.runtime_data.api.async_ensure_homeassistant_user(
                account_label=homeassistant_account_label(self.hass)
            )
        except C300XAgentApiError:
            return self.async_show_form(
                step_id="confirm",
                errors={"base": "device_user_setup_failed"},
            )
        entry.runtime_data.device_user_status = status
        ir.async_delete_issue(
            hass=self.hass,
            domain=DOMAIN,
            issue_id=repair_issue_id(DEVICE_USER_REQUIRED_ISSUE, self._entry_id),
        )
        return self.async_create_entry(data={})
