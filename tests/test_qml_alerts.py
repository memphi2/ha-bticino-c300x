"""Exercise authored alert logic without claiming Qt/firmware hardware proof."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("script", ["alerts.cjs", "alerts_qml.cjs"])
def test_native_alert_logic(script: str) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests/qml" / script)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode,fault,error", [
    ("ack", "none", None),
    ("localization", "none", None),
    ("transport", "none", None),
    ("touch", "none", None),
    ("touch", "missing_observer", "user-owned Normal must survive alert expiry"),
    ("touch", "consumed_press", "outside press must pass through"),
])
def test_alert_engine_regression(mode: str, fault: str, error: str | None) -> None:
    interpreter = os.environ.get("C300X_QML_PYTHON")
    if not interpreter:
        if importlib.util.find_spec("PySide6") is None:
            pytest.skip("Optional PySide6 absent; set C300X_QML_PYTHON")
        interpreter = sys.executable
    script = Path(__file__).resolve().parent / "qml/alerts_engine.py"
    result = subprocess.run([interpreter, str(script), mode, fault],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == (0 if error is None else 1), result.stdout + result.stderr
    if error is not None:
        assert error in result.stderr


def test_notification_looks_like_a_station_popup():
    """Grey sheet on black like ConfirmPopup, station font, severity as a marker."""
    import re

    source = (Path(__file__).resolve().parents[1] / "device_qml/C300XAlerts.qml").read_text(encoding="utf-8")
    texts = re.findall(r"\n( +)Text \{\n(.*?)\n\1\}", source, re.S)
    assert len(texts) == 4
    for _indent, body in texts:
        # A plain Text falls back to the system font unless the family is named.
        assert 'font.family: "Ubuntu"' in body and "font.weight: Font.Light" in body
        assert re.search(r"font\.pixelSize: (18|20)\b", body), "station popups use 18 px text"
        assert 'color: "white"' in body
    assert 'Rectangle { anchors.fill: parent; color: "black"; opacity: 0.9 }' in source
    assert re.search(r'id: sheet\n(?: .*\n){2} +color: "white"\n +opacity: 0\.5', source)
    assert re.search(r"id: severityMark\n +x: 16; y: 14; width: 6; height: 22\n +color: root\.accent", source)
    assert source.count("root.accent") == 1, "only the marker carries the severity colour"
    assert "#176196" not in source and "border." not in source
    # Presses outside the panel still reach the page underneath, so nothing
    # outside the panel may be covered.
    assert "width: Math.max(0, Math.min(parent.width - 24, 560))" in source
    assert "mouse.accepted = false" in source


def test_notification_has_no_black_band_above_the_button():
    """The sheet ends 2 px above the button and the message area holds whole lines."""
    import re

    source = (Path(__file__).resolve().parents[1] / "device_qml/C300XAlerts.qml").read_text(encoding="utf-8")
    # Only the 90 % black backing shows between sheet and button. Station popups
    # separate two buttons by 2 px; 10 px read as a band that cuts the text.
    gap = int(re.search(r"id: sheet\n +width: parent\.width\n +height: Math\.max\(0, acknowledgeButton\.y - (\d+)\)", source).group(1))
    assert gap <= 2
    panel = int(re.search(r"height: Math\.max\(0, Math\.min\(parent\.height - 24, (\d+)\)\)", source).group(1))
    button = int(re.search(r"id: acknowledgeButton\n +y: parent\.height - (\d+); width: parent\.width; height: \1\n", source).group(1))
    top, margin = map(int, re.search(
        r"id: messageScroll\n +x: 16; y: (\d+); width: parent\.width - 32\n +height: Math\.max\(0, sheet\.height - y - (\d+)\)", source).groups())
    # Ubuntu Light at 18 px has a line pitch of 21 px on the station.
    assert (panel - button - gap - top - margin) % 21 == 0
    assert "clip: true" in source[source.index("id: messageScroll"):source.index("id: messageLabel")]
