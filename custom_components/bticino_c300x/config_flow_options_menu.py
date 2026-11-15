"""Saving an area of the settings menu and closing the menu.

They live here as a mixin so the flow module stays within its size budget.
"""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult


class OptionsMenuSteps:
    """Store what an area saved, show the menu again, and close it on Done."""

    async def _async_store_options(self, options: dict[str, Any]) -> ConfigFlowResult:
        """Save the settings of an area and return to the menu.

        They are saved now, not when the dialog ends, so the next area can be
        opened without calling the dialog again. An area submitted as it is
        changes nothing and reloads nothing.
        """

        flow: Any = self
        entry = flow._config_entry
        saved = {**entry.data, **entry.options}
        if (
            any(key not in saved or saved[key] != value for key, value in options.items())
            or any(key not in options for key in entry.options)
        ):
            flow.hass.config_entries.async_update_entry(entry, options=options)
        # The next area starts from what is saved now.
        flow._connection_options = {}
        flow._feature_options = {}
        flow._device_activations = []
        flow._activation_edit_id = None
        flow._dashboard_options = {}
        flow._tile_form = None
        return cast(ConfigFlowResult, await flow.async_step_init())

    async def async_step_done(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Close the settings; every area was saved when it was submitted."""

        return cast(
            ConfigFlowResult,
            self.async_create_entry(title="", data=dict(self._config_entry.options)),
        )
