"""Small error formatting helpers."""

from __future__ import annotations


def compact_error_text(err: Exception, *, max_length: int = 180) -> str:
    """Return a compact one-line error text for diagnostics."""

    name = type(err).__name__
    message = " ".join(str(err).split())
    if not message or message == name:
        return name
    value = f"{name}: {message}"
    if len(value) > max_length:
        return f"{value[: max_length - 3]}..."
    return value
