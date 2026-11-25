"""Separate installed display files from confirmed Qt 5 activation."""

from collections.abc import Mapping
from typing import Any

from .api_errors import C300XAgentApiConnectionError, C300XDisplayNotConfirmedError
from .device_profile import entry_profile

# The agent's answers for a display write that ran on the station and failed:
# 502 the script failed (reload_failed, script_failed), 504 its job limit.
_DISPLAY_STEP_FAILED_HTTP = frozenset({502, 504})
# Answers of a step the agent never started: its script is not installed.
_DISPLAY_STEP_NOT_RUN = frozenset({"script_missing", "reload_script_missing"})


def display_activation_confirmed(status: Mapping[str, Any], *, required: bool = True) -> bool:
    """Honor Qt 5 activation evidence without changing the Qt 4 contract.

    An active overlay and a running process are necessary, not proof of QML
    readiness. Missing Qt 5 metadata is the older filesystem-display contract.
    """

    overlay = status.get("qt5_overlay")
    if overlay is None:
        return True
    if display_restart_pending(status):
        return False
    accepted = ("active",) if required else ("active", "off")
    return overlay in accepted and status.get("gui_running") is True


def display_restart_pending(status: Mapping[str, Any] | None) -> bool:
    """Whether the station still restarts its display (Qt 5 restart worker).

    A write answers once its restart ran or its wait ended; a restart still
    in flight is not a failure. Its outcome shows in a later status read.
    """

    return isinstance(status, Mapping) and status.get("gui_restart") == "pending"


def display_is_qt5(entry: Any) -> bool:
    """Whether the entry's station has the Qt 5 display of firmware 3.0.x."""

    return entry_profile(entry).display_is_qt5_overlay


def gui_reload_kwargs(entry: Any) -> dict[str, bool]:
    """Keywords for ``async_reload_gui`` from the entry's cached display status.

    The longer wait for the display restart only on the Qt 5 display; on
    1.7.x/2.0.2 the call has no keyword.
    """

    return {"display_restart": True} if display_is_qt5(entry) else {}


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
        raise C300XDisplayNotConfirmedError(
            f"The display pages are not available on this station ({reason}); "
            "the agent runs without them."
        )
    if display_restart_pending(status):
        raise C300XDisplayNotConfirmedError(
            "The display restart is still running on the station; "
            "its outcome shows in the display status."
        )
    if not display_activation_confirmed(status, required=required):
        raise C300XDisplayNotConfirmedError(
            "Qt 5 display activation is not confirmed; inspect the display status and log. "
            "A quarantined overlay holds until the next boot; applying the Display "
            "patch or the core Repair tries it once more."
        )


def display_step_failed(err: BaseException) -> bool:
    """Whether a display step ran on the station and its display failed.

    True for a display that is not confirmed and for a write the agent ran
    and answered as failed. False for a step that never ran: no connection, a
    rejected key, the agent busy with another job until the wait ended.
    """

    if isinstance(err, C300XDisplayNotConfirmedError):
        return True
    return (
        isinstance(err, C300XAgentApiConnectionError)
        and err.http_status in _DISPLAY_STEP_FAILED_HTTP
        and err.agent_state not in _DISPLAY_STEP_NOT_RUN
    )
