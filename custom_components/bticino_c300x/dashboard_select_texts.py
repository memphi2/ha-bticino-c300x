"""Texts for the options of a select on the display.

Home Assistant shows a select with a translation key through its state
translations; the option itself is only a key such as ``blocked``. The
display has no access to those translations, so the dashboard sends the
texts along with the options.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation


def select_option_texts(hass: Any, entity_id: str, options: list[str]) -> list[str]:
    """Return Home Assistant's text for each option, the option itself without one."""

    if not entity_id.startswith("select."):
        return list(options)
    if er.DATA_REGISTRY not in (getattr(hass, "data", None) or {}):
        return list(options)
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or not entry.translation_key:
        return list(options)
    return [
        translation.async_translate_state(
            hass, option, "select", entry.platform, entry.translation_key, None
        )
        for option in options
    ]


def apply_select_texts(hass: Any, entity_id: str, state: Any, item: dict[str, Any]) -> None:
    """Add option texts to a select tile and show its state with the same text."""

    for control in item.get("controls") or ():
        if control.get("command") != "option":
            continue
        options = control["options"]
        texts = select_option_texts(hass, entity_id, options)
        if texts == options:
            return
        control["labels"] = texts
        value = str(getattr(state, "state", ""))
        if value not in options:
            return
        text = texts[options.index(value)]
        if item.get("state_label") == value:
            item["state_label"] = text
        details = item.get("details")
        if isinstance(details, dict) and details.get("state_label") == value:
            details["state_label"] = text
        return
