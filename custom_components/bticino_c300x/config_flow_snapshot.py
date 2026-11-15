"""The visitor image steps of setup, reconfiguration and the settings.

They live here as mixins so the flow module stays within its size budget.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult

from .config_schemas import snapshot_schema
from .config_snapshots import SNAPSHOT_DEFAULTS, snapshot_values


def snapshot_step(
    show_form: Callable[..., Any],
    step_id: str,
    current: Mapping[str, Any],
    user_input: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, Any]:
    """Return the validated settings, or the form to show when there are none yet.

    The form starts from the current settings and names the field a refused
    value belongs to.
    """

    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            return snapshot_values(user_input), None
        except ValueError as err:
            errors[str(err)] = "invalid_snapshot_option"
    return None, show_form(
        step_id=step_id,
        # After a refused value the form keeps what was typed.
        data_schema=snapshot_schema({
            key: (user_input or {}).get(key, current[key]) for key in SNAPSHOT_DEFAULTS
        }),
        errors=errors,
    )


class SnapshotWizardSteps:
    """The visitor image step that follows the video page in the two wizards."""

    async def async_step_user_visitor_snapshot(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect the visitor image settings during setup."""

        if not self._setup_feature_data:
            return cast(ConfigFlowResult, await self.async_step_user_features())
        saved, form = snapshot_step(
            self.async_show_form, "user_visitor_snapshot", self._setup_feature_data, user_input
        )
        if saved is None:
            return cast(ConfigFlowResult, form)
        self._setup_feature_data = {**self._setup_feature_data, **saved}
        return cast(ConfigFlowResult, await self.async_step_user_device_activations())

    async def async_step_reconfigure_visitor_snapshot(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Reconfigure the visitor image settings."""

        if not self._reconfigure_feature_data:
            return cast(ConfigFlowResult, await self.async_step_reconfigure_features())
        saved, form = snapshot_step(
            self.async_show_form,
            "reconfigure_visitor_snapshot",
            self._reconfigure_feature_data,
            user_input,
        )
        if saved is None:
            return cast(ConfigFlowResult, form)
        self._reconfigure_feature_data = {**self._reconfigure_feature_data, **saved}
        return cast(ConfigFlowResult, await self.async_step_reconfigure_device_activations())


class SnapshotOptionsStep:
    """The visitor image area of the settings menu."""

    async def async_step_visitor_snapshot(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the visitor image settings."""

        feature_defaults = self._load_saved()
        saved, form = snapshot_step(
            self.async_show_form, "visitor_snapshot", feature_defaults, user_input
        )
        if saved is None:
            return cast(ConfigFlowResult, form)
        self._feature_options = {**self._feature_options, **saved}
        return cast(ConfigFlowResult, await self._async_save_options(feature_defaults))
