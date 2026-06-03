"""Shared helpers for stored C300X message metadata."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def latest_metadata_item(
    items: Iterable[dict[str, Any]],
    *,
    coerce_unix_time: bool = False,
) -> dict[str, Any] | None:
    """Return the newest metadata item from an iterable."""

    item_list = list(items)
    if not item_list:
        return None
    return max(
        item_list,
        key=lambda item: metadata_sort_key(item, coerce_unix_time=coerce_unix_time),
    )


def metadata_sort_key(
    item: dict[str, Any],
    *,
    coerce_unix_time: bool = False,
) -> tuple[int, str, str]:
    """Return a stable newest-first sort key for stored message metadata."""

    unix_time = item.get("unix_time")
    timestamp = 0
    if isinstance(unix_time, int):
        timestamp = unix_time
    elif coerce_unix_time:
        try:
            timestamp = int(unix_time or 0)
        except (TypeError, ValueError):
            timestamp = 0
    return (
        timestamp,
        str(item.get("iso_time") or item.get("date") or ""),
        str(item.get("id") or ""),
    )


def localized_choice(
    language: str | None,
    *,
    de: str,
    it: str,
    fr: str,
    en: str,
) -> str:
    """Return a simple de/it/fr/en localized text for device metadata."""

    language_code = str(language or "").lower()
    if language_code.startswith("de"):
        return de
    if language_code.startswith("it"):
        return it
    if language_code.startswith("fr"):
        return fr
    return en
