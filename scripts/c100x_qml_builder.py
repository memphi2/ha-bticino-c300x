"""Build a separate Qt5/key-operated adapter from the shared native pages.

Never modifies firmware inputs or the Qt4 source pages. Installation is a
separate transaction; building these files does not enable capabilities.
"""

from pathlib import Path
import argparse
import re
import shutil
import hashlib

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "Alarm.qml", "HomeAssistant.qml", "C300XAgenda.qml", "C300XChecks.qml",
    "C300XDetailControl.qml", "C300XEnergy.qml", "C300XEnergyConsumers.qml",
    "C300XEnergyReadout.qml", "C300XEnergySums.qml", "C300XLeaveHome.qml",
    "C300XOptionalPages.qml", "C300XPageNavigation.qml", "C300XSituations.qml",
)
TYPES = {
    "Page": "C100XPage", "UbuntuLightText": "C100XText",
    "BeepingMouseArea": "C100XAction", "MouseArea": "C100XAction",
    "BasicButton": "C100XSwitch", "CheckableButtonStyle": "C100XSwitchStyle",
    "Image": "C100XImage", "Flickable": "C100XScroll", "ListView": "C100XList",
}


def adapt_page(name: str, source: str) -> str:
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
        source = source.replace("id: page\n", 'id: page\n    backgroundColor: "#123a69"\n', 1)
    if "import QtQuick 1." in source or "import Components" in source or "tabView" in source:
        raise ValueError(f"Unadapted Qt4 dependency in {name}")
    return source


def build(destination: Path, source: Path = ROOT / "device_qml") -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in PAGES:
        (destination / name).write_text(adapt_page(name, (source / name).read_text()))
    for path in (source / "c100x").glob("*.qml"):
        shutil.copyfile(path, destination / path.name)
    shutil.copytree(source / "js", destination / "js", dirs_exist_ok=True)
    shutil.copytree(source / "c100x" / "js", destination / "js", dirs_exist_ok=True)
    shutil.copytree(source / "c100x" / "hooks", destination / "hooks", dirs_exist_ok=True)
    files = sorted(path for path in destination.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    (destination / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(destination).as_posix()}\n"
        for path in files
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    build(parser.parse_args().out)
