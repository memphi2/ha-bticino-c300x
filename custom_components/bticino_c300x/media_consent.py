"""Media consent defaults: a C100X asks first, a C300X keeps the usual defaults."""

from __future__ import annotations

from typing import Any

from .factory_login import login_model


def asks_media_consent(agent_info: object) -> bool:
    """A C100X provisions media and the HA SIP user only after an explicit opt-in."""

    return login_model(agent_info) == "C100X"


def entry_asks_media_consent(entry: Any) -> bool:
    """Apply the C100X consent defaults to an entry whose agent reports a C100X."""

    return asks_media_consent(getattr(getattr(entry, "runtime_data", None), "agent_info", None))
