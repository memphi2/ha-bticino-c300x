"""The station's profile: model, display mechanism, camera.

One place answers what differs between the stations. It reads the agent's
answer (``device`` in its capabilities, kept as the entry's agent info) and,
before an agent runs, the installer's one probe of the station. The agent
derives the same profile in native_agent/src/device_detect.c.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

C300X = "C300X"
C100X = "C100X"
# C300X 1.7.x/2.0.x: Qt 4, the display files are patched on disk.
QT4_ONDISK = "qt4_ondisk"
# C300X 3.0.x: Qt 5, the pages reach the display as a resource overlay.
QT5_RCC = "qt5_rcc"
# C100X: its own pages through hooks, activated by a reboot.
QT5_ONDISK = "qt5_ondisk"
CAMERA_HIGH_RES = "high_res"
CAMERA_FIXED = "fixed"
# A Classe 100X is experimental and set up only after the user asked for it:
# the installer's refusal without that, and the error of the setup step.
C100X_CONFIRMATION_REQUIRED = "c100x_confirmation_required"

# The Qt 5 library is the mark, not a missing QML folder: on an older device a
# missing folder is a fault the Display patch has to report. The display
# program's name tells the C100X, which has the Qt 5 library too.
_QT5_DISPLAY_MARKER = "/usr/lib/libQt5Core.so.5"
_C100X_DISPLAY_MARKER = "/home/bticino/bin/gui/BtClass100"
# The vendor's web server file, in which the station names its model.
_MODEL_FILE = "/home/bticino/sp/dbfiles_ws.xml"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """What a station is; every difference between stations asks this."""

    model: str = C300X
    display: str = QT4_ONDISK
    camera: str = CAMERA_HIGH_RES
    # False when the station's own model name and its display program
    # disagree. Such a station gets no display of either kind.
    model_confirmed: bool = True

    @property
    def is_c100x(self) -> bool:
        return self.model == C100X

    @property
    def display_is_qt5_overlay(self) -> bool:
        """The Qt 5 display of C300X firmware 3.0.x, not the C100X."""

        return self.display == QT5_RCC

    @property
    def has_display_patch(self) -> bool:
        """The Display patch exists on every C300X; the C100X has its own activation."""

        return self.display != QT5_ONDISK

    @property
    def camera_fixed(self) -> bool:
        return self.camera == CAMERA_FIXED


def _profile(
    c100x: bool, qt5: bool, camera: Any = None, *,
    c100x_program: bool | None = None, confirmed: bool = True,
) -> DeviceProfile:
    """The camera follows the display unless the agent names it.

    Whatever names a C100X, the station itself or its display program, keeps
    the C300X Display patch away.
    """

    display = QT5_ONDISK if c100x or c100x_program else QT5_RCC if qt5 else QT4_ONDISK
    if camera not in (CAMERA_HIGH_RES, CAMERA_FIXED):
        camera = CAMERA_HIGH_RES if display == QT4_ONDISK else CAMERA_FIXED
    if c100x_program is not None and c100x_program is not c100x:
        confirmed = False
    return DeviceProfile(C100X if c100x else C300X, display, camera, confirmed)


def setup_profile(setup: Any, display_status: Any = None) -> DeviceProfile:
    """Profile from the agent's answer.

    An agent that did not answer yet names no display; the cached display
    status then decides, whose ``qt5_overlay`` only the Qt 5 display of
    firmware 3.0.x reports. With neither, the station counts as a C300X with
    the Qt 4 display.
    """

    info = setup if isinstance(setup, Mapping) else {}
    kind = info.get("display_kind")
    confirmed = info.get("model_check") != "mismatch"
    if info.get("model") == C100X or kind == QT5_ONDISK:
        # A station whose own name and display program disagree is treated as
        # a C100X here: no Display patch; the agent refuses its activation.
        return _profile(True, True, info.get("camera"), confirmed=confirmed)
    if kind in (QT4_ONDISK, QT5_RCC):
        return _profile(False, kind == QT5_RCC, info.get("camera"), confirmed=confirmed)
    overlay = display_status.get("qt5_overlay") if isinstance(display_status, Mapping) else None
    return _profile(False, overlay is not None)


def entry_profile(entry: Any) -> DeviceProfile:
    """Profile of a loaded config entry."""

    runtime = getattr(entry, "runtime_data", None)
    return setup_profile(
        getattr(runtime, "agent_info", None), getattr(runtime, "qml_patch_status", None)
    )


def station_profile(run: Callable[[str], str], quote: Callable[[str], str]) -> DeviceProfile:
    """Profile read on the station before an agent runs.

    As in the agent: the station names its model itself, its display program
    is the cross-check and decides alone where the station names none. An
    unreadable answer counts as the C300X with the Qt 4 display.
    """

    words = run(
        f"test -e {quote(_QT5_DISPLAY_MARKER)} && echo qt5 || echo qt4; "
        f"test -e {quote(_C100X_DISPLAY_MARKER)} && echo c100x || echo c300x; "
        "sed -n 's:.*<webserver_type>[[:space:]]*\\(C[13]00X\\)[[:space:]]*</webserver_type>.*:"
        f"named-\\1:p' {quote(_MODEL_FILE)} 2>/dev/null | sed -n 1p"
    ).split()
    program = "c100x" in words
    named = next((word[6:] for word in words if word in ("named-C300X", "named-C100X")), None)
    if named is None:
        return _profile(program, "qt5" in words)
    return _profile(named == C100X, "qt5" in words, c100x_program=program)
