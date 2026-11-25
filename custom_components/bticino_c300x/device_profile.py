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

# The Qt 5 library is the mark, not a missing QML folder: on an older device a
# missing folder is a fault the Display patch has to report. The display
# program's name tells the C100X, which has the Qt 5 library too.
_QT5_DISPLAY_MARKER = "/usr/lib/libQt5Core.so.5"
_C100X_DISPLAY_MARKER = "/home/bticino/bin/gui/BtClass100"


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """What a station is; every difference between stations asks this."""

    model: str = C300X
    display: str = QT4_ONDISK
    camera: str = CAMERA_HIGH_RES

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

        return not self.is_c100x

    @property
    def camera_fixed(self) -> bool:
        return self.camera == CAMERA_FIXED


def _profile(c100x: bool, qt5: bool, camera: Any = None) -> DeviceProfile:
    """The camera follows the display unless the agent names it."""

    if camera not in (CAMERA_HIGH_RES, CAMERA_FIXED):
        camera = CAMERA_FIXED if c100x or qt5 else CAMERA_HIGH_RES
    if c100x:
        return DeviceProfile(C100X, QT5_ONDISK, camera)
    return DeviceProfile(C300X, QT5_RCC if qt5 else QT4_ONDISK, camera)


def setup_profile(setup: Any, display_status: Any = None) -> DeviceProfile:
    """Profile from the agent's answer.

    An agent that did not answer yet names no display; the cached display
    status then decides, whose ``qt5_overlay`` only the Qt 5 display of
    firmware 3.0.x reports. With neither, the station counts as a C300X with
    the Qt 4 display.
    """

    info = setup if isinstance(setup, Mapping) else {}
    kind = info.get("display_kind")
    if info.get("model") == C100X or kind == QT5_ONDISK:
        return _profile(True, True, info.get("camera"))
    if kind in (QT4_ONDISK, QT5_RCC):
        return _profile(False, kind == QT5_RCC, info.get("camera"))
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

    An unreadable answer counts as the C300X with the Qt 4 display.
    """

    words = run(
        f"test -e {quote(_QT5_DISPLAY_MARKER)} && echo qt5 || echo qt4; "
        f"test -e {quote(_C100X_DISPLAY_MARKER)} && echo c100x || echo c300x"
    ).split()
    return _profile("c100x" in words, "qt5" in words)
