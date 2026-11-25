"""The explicit opt-in to the experimental Classe 100X support at setup.

One package serves the Classe 300X and the Classe 100X. A Classe 300X is set
up as before. A station that turns out to be a Classe 100X is set up only
after the user confirmed its experimental support in a step of its own; before
that nothing is written to it.
"""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult

from .device_profile import C100X_CONFIRMATION_REQUIRED, setup_profile

CONF_C100X_EXPERIMENTAL = "c100x_experimental"


class C100XOptInSteps:
    """Ask once per setup, then return to the step that found the Classe 100X."""

    _c100x_confirmed: bool = False
    _c100x_resume: tuple[str, dict[str, Any] | None] | None = None

    def _c100x_opt_in_missing(self, setup: Any) -> bool:
        return setup_profile(setup).is_c100x and not self._c100x_confirmed

    @staticmethod
    def _c100x_install_refused(err: Exception) -> bool:
        """The installer found a Classe 100X and wrote nothing yet."""

        return getattr(err, "reason", None) == C100X_CONFIRMATION_REQUIRED

    async def _async_ask_c100x_opt_in(
        self: Any, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        self._c100x_resume = (step, user_input)
        return cast(ConfigFlowResult, await self.async_step_c100x_experimental())

    async def async_step_c100x_experimental(
        self: Any, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._c100x_resume is None:
            return cast(ConfigFlowResult, await self.async_step_user())
        if user_input is not None:
            if user_input.get(CONF_C100X_EXPERIMENTAL) is True:
                step, saved = self._c100x_resume
                self._c100x_resume = None
                self._c100x_confirmed = True
                if step == "install":
                    # Without typed credentials the factory login runs again.
                    self._factory_login_tried = saved is not None
                    return cast(ConfigFlowResult, await self.async_step_bootstrap_install(saved))
                return cast(ConfigFlowResult, await self.async_step_agent_auth(saved))
            errors["base"] = C100X_CONFIRMATION_REQUIRED
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="c100x_experimental",
            data_schema=vol.Schema({vol.Required(CONF_C100X_EXPERIMENTAL, default=False): bool}),
            errors=errors,
        ))
