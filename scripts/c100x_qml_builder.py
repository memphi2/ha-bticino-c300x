"""Build a separate Qt5/key-operated adapter from the shared native pages.

Never modifies firmware inputs or the Qt4 source pages. Installation is a
separate transaction; building these files does not enable capabilities.
"""

import argparse
import hashlib
import re
import shutil
from pathlib import Path

from device_file_strip import STRIPPED_SUFFIXES, strip_device_file

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "Alarm.qml", "HomeAssistant.qml", "C300XAgenda.qml", "C300XAlerts.qml", "C300XChecks.qml",
    "C300XDetailControl.qml", "C300XEnergy.qml", "C300XEnergyConsumers.qml",
    "C300XEnergyReadout.qml", "C300XEnergySums.qml", "C300XLeaveHome.qml",
    "C300XOptionalPages.qml", "C300XPageNavigation.qml", "C300XSituations.qml",
)
# The C100X shows no memos and asks for none.
C300X_ONLY_SCRIPTS = frozenset({"c300x_memos.js"})
TYPES = {
    "Page": "C100XPage", "UbuntuLightText": "C100XText",
    "BeepingMouseArea": "C100XAction", "MouseArea": "C100XAction",
    "BasicButton": "C100XSwitch", "CheckableButtonStyle": "C100XSwitchStyle",
    "Image": "C100XImage", "Flickable": "C100XScroll", "ListView": "C100XList",
}


# The station's own pages use 20 px and more; our dense pages go down to this and no further.
# The energy charts are the exception: their axis, legend and ten consumer rows have fixed places
# that larger labels overflow (the layout check proves it), so they keep their own sizes.
MINIMUM_FONT = 18


def swap(source: str, old: str, new: str) -> str:
    """Replace one known place of a shared page; a changed page must be reviewed."""
    if source.count(old) != 1:
        raise ValueError(f"Shared page changed; review the C100X adaptation of {old!r}")
    return source.replace(old, new)


def adapt_alerts(source: str) -> str:
    """Keep the shared expiry/ack controller; replace only verified vendor IO."""
    for anchor in (
        "    property bool blocked: true", "    function soundReady() {",
        "    function waitForCommand() {", "valid = !!Alerts.validate(command, new Date().getTime())",
        "if (stopped || Alerts.runtimeFor(root)) return", "Component.onCompleted: initialize()",
        "target: global.screenState", "global.screenState.disableState(ScreenState.Normal)",
    ):
        if source.count(anchor) != 1:
            raise ValueError("Shared alert contract changed; review the C100X adaptation")
    source = source.replace("import QtQuick 1.1", "import QtQuick 2.7")
    source = source.replace("import BtObjects 2.0\n", "").replace("import BtClass 1.0\n", "")
    source = source.replace("property variant", "property var").replace("trsl.language", "c100xHost.language")
    source = source.replace("    property bool blocked: true", """    property bool completed: false
    readonly property var vendorScreen: c100xHost && c100xHost.vendor ? c100xHost.vendor.screenState || null : null
    readonly property bool screenReady: !!vendorScreen && c100xHost.normalState >= 0 && c100xHost.offState >= 0
        && typeof vendorScreen.state === "number" && typeof vendorScreen.screensaverInterval === "number"
        && typeof vendorScreen.simulateClick === "function" && typeof vendorScreen.disableState === "function"
        && typeof vendorScreen.stateChangedInt === "function"
    readonly property bool blocked: !screenReady || !c100xHost.running || c100xHost.blocked
        || typeof c100xHost.alertsBlocked !== "boolean" || c100xHost.alertsBlocked
    onScreenReadyChanged: { if (screenReady) initialize(); else preempt() }
    C100XAlertKeys { anchors.fill: parent; controller: root; scroll: messageScroll }""")
    start = source.index("    function soundReady() {")
    end = source.index("    function waitForCommand() {", start)
    source = source[:start] + """    // The stock queued beep has no verified call-safe cancellation contract.
    function soundReady() { return false }
    function shortBeep(stillCurrent) { return false }

""" + source[end:]
    source = source.replace("valid = !!Alerts.validate(command, new Date().getTime())",
                            "valid = !!Alerts.validate(command, new Date().getTime()) && command.sound_duration === 0")
    source = source.replace("if (stopped || Alerts.runtimeFor(root)) return",
                            "if (!completed || !screenReady || stopped || Alerts.runtimeFor(root)) return")
    source = source.replace("global.screenState", "root.vendorScreen")
    source = source.replace("target: root.vendorScreen", "target: root.screenReady ? root.vendorScreen : null")
    source = source.replace("ScreenState.Normal", "c100xHost.normalState").replace("ScreenState.ScreenOff", "c100xHost.offState")
    source = source.replace("Component.onCompleted: initialize()", "Component.onCompleted: { completed = true; initialize() }")
    # The notice covers the whole screen on the station's own background; Return marks it read,
    # so that button carries the selection bar the station draws under its selected item.
    source = swap(source, """        anchors.centerIn: parent
        width: Math.max(0, parent.width - 24)
        height: Math.max(0, Math.min(parent.height - 24, 370))
        color: "#176196"
        border.color: root.accent
        border.width: 2
        radius: 4
        clip: true
""", """        anchors.fill: parent
        color: "black"
        clip: true
        Image { anchors.fill: parent; source: "../images/background.jpg" }
        Rectangle { anchors.fill: parent; color: "#66000000" }
        Rectangle { width: parent.width; height: 6; color: root.accent }
""")
    source = swap(source, "        Flickable {\n            id: messageScroll", "        C100XScroll {\n            id: messageScroll")
    source = swap(source, 'color: acknowledgeMouse.pressed ? "#124974" : "#207cb6"\n            border.color: "white"; radius: 4',
                  'color: acknowledgeMouse.pressed ? "#66ffffff" : "#33ffffff"\n            radius: 6\n'
                  '            Rectangle { objectName: "alertFocusBar"; anchors.bottom: parent.bottom; width: parent.width; height: 5; color: "white" }')
    source = swap(source, "x: 16; y: 10; width: parent.width - 32; height: 30", "x: 36; y: 22; width: parent.width - 72; height: 30")
    source = swap(source, "x: 16; y: 44; width: parent.width - 32; height: 58", "x: 36; y: 56; width: parent.width - 72; height: 66")
    source = swap(source, "x: 16; y: 108; width: parent.width - 32", "x: 36; y: 130; width: parent.width - 72")
    source = swap(source, "x: 16; y: parent.height - 64; width: parent.width - 32; height: 48",
                  "x: 36; y: parent.height - 76; width: parent.width - 72; height: 56")
    source = swap(source, "font.pixelSize: 22\n            color: \"white\"\n            wrapMode: Text.Wrap\n            elide: Text.ElideRight",
                  "font.pixelSize: 27\n            font.bold: true\n            color: \"white\"\n            wrapMode: Text.Wrap\n            elide: Text.ElideRight")
    source = swap(source, "                font.pixelSize: 20\n                color: \"white\"\n                wrapMode: Text.Wrap",
                  "                font.pixelSize: 24\n                color: \"white\"\n                wrapMode: Text.Wrap")
    source = source.replace("id: messageScroll", 'id: messageScroll\n            objectName: "alertMessageScroll"')
    source = source.replace("id: acknowledgeButton", 'id: acknowledgeButton\n            objectName: "alertAcknowledge"')
    if "global." in source or "ScreenState." in source or "AudioState." in source or "BtClass" in source:
        raise ValueError("Unadapted C100X alert vendor dependency")
    return source


def adapt_page(name: str, source: str) -> str:
    if name == "C300XAlerts.qml":
        return adapt_alerts(source)
    source = source.replace("import QtQuick 1.1", "import QtQuick 2.7")
    for module in ("Components 1.0", "Components.Styles 1.0", "BtObjects 2.0"):
        source = source.replace(f"import {module}\n", "")
    source = re.sub(r"\b(" + "|".join(TYPES) + r")(?=\s*\{)",
                    lambda match: TYPES[match[0]], source)
    source = source.replace("property variant", "property var")
    source = source.replace("signal actionRequested(variant", "signal actionRequested(var")
    source = source.replace("trsl.language", "c100xHost.language").replace("trsl.empty", '""')
    source = source.replace("c300xDisplayPreferences", "c100xHost.preferences")
    source = source.replace("tabView.activateTab(homePage)", "page.back()")
    source = source.replace("tabView.activateTab(alarmPage)", "page.alarmRequested()")
    source = source.replace(".pressed", ".down")
    source = source.replace("onPressed:", "onActionPressed:")
    source = source.replace("onReleased:", "onActionReleased:")
    source = source.replace("if (pressed)", "if (down)")
    source = source.replace("id: sliderMouse\n", "id: sliderMouse\n"
                            '                objectName: "c100xNumericSlider"\n'
                            "                keyboardBuckets: false\n"
                            "                keyboardSteps: controlRow.numericRangeValid() && hostPage ? "
                            "hostPage.controlLastStep(control) + 1 : 0\n"
                            "                keyboardInitialPosition: controlRow.numericRangeValid() && hostPage && "
                            "!hostPage.controlValueUnset(control) ? Math.round((Number(control.value) - control.min) / control.step) : 0\n"
                            "                keyboardRangeRatio: controlRow.numericRangeValid() ? "
                            "Math.min(1, (keyboardSteps - 1) * control.step / (control.max - control.min)) : 1\n")
    source = source.replace('objectName: "energyHoursTap"',
                            'objectName: "energyHoursTap"\n                keyboardSteps: 24')
    source = source.replace('objectName: "energyPowerTap"',
                            'objectName: "energyPowerTap"\n                keyboardSteps: root.powerBuckets')
    if name == "Alarm.qml":
        source = swap(source, "id: page\n", 'id: page\n    tint: "#99123a69"\n    icon: "C100XAlarm.svg"\n')
        source = swap(source, 'headerLabel: uiText("alarm") + ""', 'headerLabel: "Alarmo"')
    if name == "HomeAssistant.qml":
        # The station has no touch and no back key: pages are a carousel with dots and a last EXIT
        # entry, like its own menus. The tab bar, the More list and the pager are not shown.
        source = swap(source, "id: page\n", """id: page
    pages: detailOpen || notificationsOpen ? 1 : Math.max(1, pageCount)
    pageIndex: currentPageIndex
    view: notificationsOpen ? "n" : detailOpen ? "d" : ""
    onPageRequested: Api.dashboardSelectPage(index, status, page)
""")
        source = swap(source, "anchors.bottomMargin: tabNavigation && pageCount > 1 ? 65 : 18", "anchors.bottomMargin: 8")
        source = swap(source, "height: pageCount > 1 && !tabNavigation ? 38 : 0", "height: 0")
        source = swap(source, "visible: pageCount > 1 && !tabNavigation", "visible: false")
        source = swap(source, "visible: tabNavigation && pageCount > 1 && !detailOpen && !notificationsOpen", "visible: false")
    if name == "C300XDetailControl.qml":
        # A number is set like the station's own regulations: Return, Up/Down, Return. No +/- buttons.
        source = swap(source, "model: [-1, 1]", "model: []")
        source = swap(source, "anchors.leftMargin: 80; anchors.rightMargin: 80", "anchors.leftMargin: 0; anchors.rightMargin: 0")
    # Opaque C300X panel fills become see-through panels on the station's own background.
    for fill in ('"#1f2c36"', '"#041b3b"'):
        source = source.replace(f"color: {fill}", 'color: "#40000000"')
    smallest = 0 if name.startswith("C300XEnergy") else MINIMUM_FONT
    source = re.sub(r"font\.pixelSize:[^;\n]*", lambda sizes: re.sub(
        r"(?<=[?:] )\d+\b", lambda size: str(max(smallest, int(size[0]))), sizes[0]), source)
    if name == "C300XEnergyConsumers.qml":
        source = source.replace('objectName: "consumerTick"',
                                'objectName: "consumerTick"\n                        fontSizeMode: Text.Fit\n'
                                '                        minimumPixelSize: 10')
    if "import QtQuick 1." in source or "import Components" in source or "tabView" in source:
        raise ValueError(f"Unadapted Qt4 dependency in {name}")
    return source


def build(destination: Path, source: Path = ROOT / "device_qml") -> None:
    if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise ValueError("C100X output must be a fresh empty directory")
    destination.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (destination / name).write_text(adapt_page(name, (source / name).read_text()))
    for pattern in ("*.qml", "*.svg"):
        for path in (source / "c100x").glob(pattern):
            shutil.copyfile(path, destination / path.name)
    (destination / "js").mkdir()
    for path in (source / "js").glob("*.js"):
        if path.name not in C300X_ONLY_SCRIPTS:
            shutil.copyfile(path, destination / "js" / path.name)
    shutil.copytree(source / "c100x" / "js", destination / "js", dirs_exist_ok=True)
    shutil.copytree(source / "c100x" / "hooks", destination / "hooks", dirs_exist_ok=True)
    files = sorted(path for path in destination.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    # Adaptation needs the source anchors; hash only the final delivered bytes.
    for path in files:
        if path.suffix in STRIPPED_SUFFIXES:
            strip_device_file(path, path)
    (destination / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(destination).as_posix()}\n"
        for path in files
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
