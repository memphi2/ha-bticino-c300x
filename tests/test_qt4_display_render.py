"""Display pages shown on the station's own Qt 4.8, where the Qt 6 harness sees no fault."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import qt4_render

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def station():
    paths = qt4_render.environment()
    if paths is None:
        pytest.skip("Optional Qt 4 render: needs C300X_QT4_" + "/".join(qt4_render.NAMES) + " and an ARM compiler")
    station = qt4_render.Station(paths)
    yield station
    station.close()


def energy_page(station, view: str = "now", picture: Path | None = None) -> str:
    source = (ROOT / "tests/qml/energy_render_qt4.qml").read_text().replace("@VIEW@", view)
    return station.show("ProbeEnergy", source, 2400, picture)


def test_energy_hour_labels_stand_below_the_bars_on_qt4(station):
    """The hour labels of Today stand below the bars."""
    output = energy_page(station)
    assert "C300X_ENERGY_QT4_FAIL" not in output, [line for line in output.splitlines() if "QT4_FAIL" in line]
    assert "C300X_ENERGY_QT4_PASS 9" in output, output[-800:]


def test_energy_views_raise_no_qml_warning_on_qt4(station):
    assert qt4_render.warnings(energy_page(station)) == []



def delegate_anchor_faults(text: str) -> list[str]:
    """Anchors of a Repeater delegate that name another item than its parent.

    Qt 4.8 creates the delegate before it has a parent, refuses such an anchor
    ("Cannot anchor to an item that isn't a parent or sibling") and leaves the
    item where it was.
    """
    lines, faults = text.split("\n"), []
    for index, line in enumerate(lines):
        if not re.match(r"\s*Repeater \{", line):
            continue
        indent = len(line) - len(line.lstrip())
        delegate = False
        for inner in lines[index + 1:]:
            depth = len(inner) - len(inner.lstrip())
            if inner.strip() and depth <= indent:
                break
            child = re.match(r"\s*[A-Z]\w* \{", inner)
            if depth == indent + 4 and child:
                delegate = True
            elif delegate and depth == indent + 8 and not child:
                faults += [found.group(0) for found in re.finditer(r"anchors\.\w+: (?!parent\b)[a-z]\w*", inner)]
    return faults


def test_the_delegate_anchor_check_knows_the_fault():
    fault = "Item {\n    Repeater {\n        Text {\n            anchors.top: bars.bottom\n        }\n    }\n}\n"
    assert delegate_anchor_faults(fault) == ["anchors.top: bars"]
    assert delegate_anchor_faults(fault.replace("bars.bottom", "parent.bottom")) == []
    assert delegate_anchor_faults(fault.replace("anchors.top: bars.bottom", "Item { anchors.top: bars.bottom }")) == []


@pytest.mark.parametrize("path", sorted((ROOT / "device_qml").glob("*.qml")), ids=lambda path: path.name)
def test_no_repeater_delegate_anchors_to_another_item(path):
    assert delegate_anchor_faults(path.read_text()) == []
