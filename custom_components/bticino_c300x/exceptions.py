"""Translated Home Assistant exceptions for BTicino C300X."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .model_names import C100X, entry_model, model_placeholders

# Their C300X wording names the Display patch or the agent; a C100X has its own text.
_C100X_KEYS = frozenset({"display_disabled", "gui_function_patch_required", "text_memo_write_not_supported"})


def _kwargs(translation_key: str, placeholders: dict[str, str] | None, entry: Any) -> dict[str, Any]:
    # Messages name the entry's model; without an entry they keep the C300X text.
    model = entry_model(entry)
    if model == C100X and translation_key in _C100X_KEYS:
        translation_key = f"{translation_key}_c100x"
    return {
        "translation_domain": DOMAIN,
        "translation_key": translation_key,
        "translation_placeholders": model_placeholders(model, placeholders),
    }


def service_validation_error(
    translation_key: str,
    placeholders: dict[str, str] | None = None,
    *,
    entry: Any = None,
) -> ServiceValidationError:
    """Create a translated service validation error."""

    return ServiceValidationError(**_kwargs(translation_key, placeholders, entry))


def home_assistant_error(
    translation_key: str,
    placeholders: dict[str, str] | None = None,
    *,
    entry: Any = None,
) -> HomeAssistantError:
    """Create a translated error for a device that failed or could not be reached."""

    return HomeAssistantError(**_kwargs(translation_key, placeholders, entry))
