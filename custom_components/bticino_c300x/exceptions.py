"""Translated Home Assistant exceptions for BTicino C300X."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN


def service_validation_error(
    translation_key: str,
    placeholders: dict[str, str] | None = None,
) -> ServiceValidationError:
    """Create a translated service validation error."""

    kwargs: dict[str, Any] = {
        "translation_domain": DOMAIN,
        "translation_key": translation_key,
    }
    if placeholders:
        kwargs["translation_placeholders"] = placeholders
    return ServiceValidationError(**kwargs)
