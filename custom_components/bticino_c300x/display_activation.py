"""Separate installed display files from confirmed Qt 5 activation."""

from collections.abc import Mapping
from typing import Any

from .api_errors import C300XAgentApiError


def display_activation_confirmed(status: Mapping[str, Any], *, required: bool = True) -> bool:
    """Honor Qt 5 activation evidence without changing the Qt 4 contract.

    An active overlay and a running process are necessary, not proof of QML
    readiness. Missing Qt 5 metadata is the older filesystem-display contract.
    """

    overlay = status.get("qt5_overlay")
    if overlay is None:
        return True
    accepted = ("active",) if required else ("active", "off")
    return overlay in accepted and status.get("gui_running") is True


def display_unsupported(status: Mapping[str, Any] | None) -> str | None:
    """Return why the display pages cannot run on this station, or None.

    A Qt 5 display program or start script the agent does not know is left as
    shipped; the agent then runs without the display pages.
    """

    reason = status.get("qt5_unsupported") if isinstance(status, Mapping) else None
    return reason if isinstance(reason, str) and reason else None


def require_display_activation(status: Mapping[str, Any], *, required: bool = True) -> None:
    """Leave failed updates/repairs pending instead of confirming stock fallback."""

    reason = display_unsupported(status)
    if required and reason is not None:
        raise C300XAgentApiError(
            f"The display pages are not available on this station ({reason}); "
            "the agent runs without them."
        )
    if not display_activation_confirmed(status, required=required):
        raise C300XAgentApiError(
            "Qt 5 display activation is not confirmed; inspect the display status and log. "
            "A quarantined overlay holds until the next boot; applying the Display "
            "patch or the core Repair tries it once more."
        )
