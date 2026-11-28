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
# Classe 300X2 (firmware 1.2.x): recognised, not supported yet. It runs
# aarch64 only, with no loader for the armhf agent, and has a Flutter display
# instead of Qt. The installer writes nothing to it.
C3X2 = "C3X2"
C3X2_NOT_SUPPORTED = "c3x2_not_supported"
# C300X 1.7.x/2.0.x: Qt 4, the display files are patched on disk.
QT4_ONDISK = "qt4_ondisk"
# C300X 3.0.x: Qt 5, the pages reach the display as a resource overlay.
QT5_RCC = "qt5_rcc"
# C100X: its own pages through hooks, activated by a reboot.
QT5_ONDISK = "qt5_ondisk"
# A station without a display we know: the Classe 300X2.
NO_DISPLAY = "none"
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
# The vendor's folder, on every station of every firmware. A host without it
# is no BTicino station and gets nothing from the installer.
_STATION_HOME = "/home/bticino"
# The kernel's machine name of a 64-bit ARM station. Every Classe 300X and
# 100X runs a 32-bit ARM kernel (armv7l); the agent is an armhf program.
_AARCH64 = "aarch64"
NOT_A_BTICINO_STATION = "not_a_bticino_station"
# The entry keeps the model the agent last named: an entry whose agent does
# not answer stays the station it is.
STATION_MODEL = "station_model"


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
    def supported(self) -> bool:
        """False on a station the integration does not serve yet: the Classe 300X2."""

        return self.model != C3X2

    @property
    def display_is_qt5_overlay(self) -> bool:
        """The Qt 5 display of C300X firmware 3.0.x, not the C100X."""

        return self.display == QT5_RCC

    @property
    def has_display_patch(self) -> bool:
        """The Display patch exists on every C300X; the C100X has its own activation.

        A station whose own model name and display program disagree gets neither.
        """

        return self.supported and self.display != QT5_ONDISK and self.model_confirmed

    @property
    def camera_fixed(self) -> bool:
        return self.camera == CAMERA_FIXED


def _profile(
    c100x: bool, qt5: bool, camera: Any = None, *, confirmed: bool = True,
) -> DeviceProfile:
    """The camera follows the display unless the agent names it."""

    display = QT5_ONDISK if c100x else QT5_RCC if qt5 else QT4_ONDISK
    if camera not in (CAMERA_HIGH_RES, CAMERA_FIXED):
        camera = CAMERA_HIGH_RES if display == QT4_ONDISK else CAMERA_FIXED
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
        return _profile(True, True, info.get("camera"), confirmed=confirmed)
    if kind in (QT4_ONDISK, QT5_RCC):
        return _profile(False, kind == QT5_RCC, info.get("camera"), confirmed=confirmed)
    overlay = display_status.get("qt5_overlay") if isinstance(display_status, Mapping) else None
    return _profile(False, overlay is not None)


def reported_model(setup: Any) -> str | None:
    """The model an agent's answer names, None when it names neither model nor display."""

    info = setup if isinstance(setup, Mapping) else {}
    if info.get("model") not in (C300X, C100X) and info.get("display_kind") not in (
        QT4_ONDISK, QT5_RCC, QT5_ONDISK,
    ):
        return None
    return setup_profile(info).model


def station_model_data(setup: Any) -> dict[str, str]:
    """The entry data a new entry keeps of the model its setup found."""

    model = reported_model(setup)
    return {STATION_MODEL: model} if model is not None else {}


def remember_station_model(hass: Any, entry: Any, setup: Any) -> None:
    """Keep the model the agent named, for starts at which it does not answer."""

    model = reported_model(setup)
    if model is not None and entry.data.get(STATION_MODEL) != model:
        hass.config_entries.async_update_entry(entry, data={**entry.data, STATION_MODEL: model})


def entry_profile(entry: Any) -> DeviceProfile:
    """Profile of a config entry: the live agent answer, else the model it last named."""

    runtime = getattr(entry, "runtime_data", None)
    info = getattr(runtime, "agent_info", None)
    data = getattr(entry, "data", None)
    stored = data.get(STATION_MODEL) if isinstance(data, Mapping) else None
    if reported_model(info) is None and stored in (C300X, C100X):
        info = {**(info if isinstance(info, Mapping) else {}), "model": stored}
    return setup_profile(info, getattr(runtime, "qml_patch_status", None))


def is_bticino_station(run: Callable[[str], str], quote: Callable[[str], str]) -> bool:
    """True only when the host answers that it has the vendor's folder."""

    return "station" in run(f"test -d {quote(_STATION_HOME)} && echo station || echo other").split()


def station_profile(run: Callable[[str], str], quote: Callable[[str], str]) -> DeviceProfile:
    """Profile read on the station before an agent runs.

    As in the agent: the station names its model itself; where that name is
    missing or disagrees with the display program, the program decides model
    and display and the profile is not confirmed. An unreadable answer counts
    as the C300X with the Qt 4 display.

    A Classe 300X2 is told by either of two signs, each enough alone: its
    kernel is aarch64, or it names itself C3X2. A Classe 300X or 100X shows
    neither, so an unreadable answer never makes one a Classe 300X2.
    """

    words = run(
        f"test -e {quote(_QT5_DISPLAY_MARKER)} && echo qt5 || echo qt4; "
        f"test -e {quote(_C100X_DISPLAY_MARKER)} && echo c100x || echo c300x; "
        "sed -n -e 's:.*<webserver_type>[[:space:]]*\\(C[13]00X\\)[[:space:]]*</webserver_type>.*:"
        "named-\\1:p' -e 's:.*<webserver_type>[[:space:]]*\\(C3X2\\)[[:space:]]*</webserver_type>.*:"
        f"named-\\1:p' {quote(_MODEL_FILE)} 2>/dev/null | sed -n 1p; "
        "echo machine-$(uname -m 2>/dev/null)"
    ).split()
    if f"machine-{_AARCH64}" in words or f"named-{C3X2}" in words:
        return DeviceProfile(C3X2, NO_DISPLAY, CAMERA_FIXED)
    program = "c100x" in words
    named = next((word[6:] for word in words if word in ("named-C300X", "named-C100X")), None)
    return _profile(program, "qt5" in words, confirmed=named is None or (named == C100X) is program)
