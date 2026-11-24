"""The model a user reads in texts: a C300X keeps its texts, a C100X gets its own.

Texts name the model through the ``{model}`` placeholder.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE

from .const import DEFAULT_NAME
from .display_support import entry_is_c100x, setup_is_c100x
from .factory_login import login_model

MODEL = "model"
C300X = "C300X"
C100X = "C100X"
# Before the device answered, a manual setup cannot know the model.
EITHER = "C300X/C100X"
C100X_DEFAULT_NAME = "BTicino C100X"


def setup_model(setup: Any, hint: str = "") -> str:
    """Model of setup data, else the discovery hint, else both names."""

    if setup_is_c100x(setup):
        return C100X
    return login_model(setup) or hint or EITHER


def entry_model(entry: Any) -> str:
    """Model of a config entry; an entry whose agent did not answer keeps the C300X text."""

    return C100X if entry_is_c100x(entry) else C300X


def model_placeholders(model: str, placeholders: Mapping[str, str] | None = None) -> dict[str, str]:
    """Placeholders with the model; a caller's own value wins."""

    return {MODEL: model, **(placeholders or {})}


class ModelTextFlow:
    """Give every form, menu and abort of a flow the model it is about."""

    def _text_model(self) -> str:
        raise NotImplementedError

    def async_show_form(self, *, step_id: str | None = None,
                        description_placeholders: Mapping[str, str] | None = None, **kwargs: Any) -> Any:
        model = self._text_model()
        return super().async_show_form(  # type: ignore[misc]
            step_id=step_id,
            description_placeholders=model_placeholders(model, description_placeholders), **kwargs,
        )

    def async_show_menu(self, *, step_id: str | None = None,
                        description_placeholders: Mapping[str, str] | None = None, **kwargs: Any) -> Any:
        model = self._text_model()
        return super().async_show_menu(  # type: ignore[misc]
            step_id=step_id,
            description_placeholders=model_placeholders(model, description_placeholders), **kwargs,
        )

    def async_abort(self, *, reason: str, description_placeholders: Mapping[str, str] | None = None,
                    **kwargs: Any) -> Any:
        return super().async_abort(  # type: ignore[misc]
            reason=reason,
            description_placeholders=model_placeholders(self._text_model(), description_placeholders), **kwargs,
        )


class ModelTextConfigFlow(ModelTextFlow):
    """Setup names the device once it answered; reconfigure and reauth name the entry's."""

    _model_hint = ""

    def _text_model(self) -> str:
        source = getattr(self, "context", {}).get("source")
        if source in (SOURCE_RECONFIGURE, SOURCE_REAUTH):
            try:
                getter = self._get_reauth_entry if source == SOURCE_REAUTH else self._get_reconfigure_entry
                return entry_model(getter())  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - a missing entry keeps the C300X text
                return C300X
        return setup_model(getattr(self, "_setup_agent_info", None), self._model_hint)

    def async_create_entry(self, *, title: str, **kwargs: Any) -> Any:
        if title == DEFAULT_NAME and self._text_model() == C100X:
            title = C100X_DEFAULT_NAME
        return super().async_create_entry(title=title, **kwargs)  # type: ignore[misc]


class ModelTextOptionsFlow(ModelTextFlow):
    """Options name the model of their entry."""

    def _text_model(self) -> str:
        return entry_model(getattr(self, "_config_entry", None))
