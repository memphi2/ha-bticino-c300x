"""Saving an area of the settings menu and closing the menu.

They live here as a mixin so the flow module stays within its size budget.
"""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult

from .config_flow_input import _feature_input


class OptionsMenuSteps:
    """Store what an area saved, show the menu again, and close it on Done."""

    _unchanged_options: dict[str, Any] | None = None

    def _note_saved_options(self) -> None:
        """Remember what saving an opened area without a change would store.

        The stored form can differ from the entry although the user changed
        nothing: an entry saved by an older release lacks newer settings.
        """

        flow: Any = self
        if self._unchanged_options is None:
            feature_data, errors = _feature_input(
                {**flow._feature_options, **flow._dashboard_options}
            )
            if not errors:
                self._unchanged_options = {**flow._connection_options, **feature_data}

    async def _async_store_options(self, options: dict[str, Any]) -> ConfigFlowResult:
        """Save the settings of an area and return to the menu.

        They are saved now, not when the dialog ends, so the next area can be
        opened without calling the dialog again. An area submitted as it is
        changes nothing and reloads nothing.
        """

        flow: Any = self
        entry = flow._config_entry
        if options != self._unchanged_options and options != dict(entry.options):
            flow.hass.config_entries.async_update_entry(entry, options=options)
        # The next area starts from what is saved now.
        self._unchanged_options = None
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
