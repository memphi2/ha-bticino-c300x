"""The status line of the Alarm page is readable on every station background.

It was text in the status colour straight on the wallpaper: amber "PIN
required" on the orange part of the default picture, or on the sand-coloured
one, could not be read. The line now sits on the dark panel the page uses
elsewhere, the text is white, and the status colour is a small marker.
"""

import re
from pathlib import Path

QML = Path(__file__).resolve().parents[1] / "device_qml/Alarm.qml"


def status_block():
    source = QML.read_text(encoding="utf-8")
    start = source.rindex("                Item {\n                    id: status\n")
    return source[start:source.index("\n                }\n", start)]


def test_status_text_is_white_on_the_dark_panel():
    block = status_block()
    panel, marker, text = block.index("Image {"), block.index("Rectangle {"), block.index("UbuntuLightText {")
    assert panel < marker < text, "panel behind, then marker, then text"
    assert 'source: "images/settings/act_btn.svg"' in block[panel:marker]
    line = block[text:]
    assert 'color: "white"' in line and "status.color" not in line
    assert "text: statusText()" in line
    assert "wrapMode: Text.Wrap" in line and "maximumLineCount: 2" in line


def test_status_colour_is_a_small_marker():
    block = status_block()
    marker = block[block.index("Rectangle {"):block.index("UbuntuLightText {")]
    assert "x: 8; y: 8; width: 4; height: 22" in marker
    assert 'color: feedbackColorsEnabled || !alarmOnline ? status.color : "#c7d0d9"' in marker
    assert len(re.findall(r"status\.color", block)) == 1


def test_an_empty_status_draws_nothing():
    block = status_block()
    assert block.count('visible: statusLine.text !== ""') == 2, "panel and marker hide with the text"
