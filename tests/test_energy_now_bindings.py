"""The energy page assigns nothing undefined while its boxes change.

A box is drawn from two bindings, "is there a node" and "the node". Qt
re-evaluates them one after the other, and Home Assistant may send a node
without a colour, so for a moment - or for good - the box had a node but no
colour or label. Qt 4.8 then logged "Unable to assign [undefined] to QColor"
and "... to QString" on every view change. Each binding now tests the value
it assigns.

The repository's Qt 4 probe runs without a screen and cannot create text
items, so the page itself is checked on the source.
"""

import re
from pathlib import Path

QML = Path(__file__).resolve().parents[1] / "device_qml/C300XEnergy.qml"


def test_box_bindings_always_have_a_value():
    source = QML.read_text(encoding="utf-8")
    assert 'border.color: box.info.color ? box.info.color : "transparent"' in source
    assert 'text: box.info.label ? box.info.label : ""' in source


def test_no_node_value_is_assigned_behind_another_binding():
    source = QML.read_text(encoding="utf-8")
    # "present ? info.x : y" trusts a second binding; "info.x ? info.x : y" does not.
    assert not re.search(r"\bpresent \? (?:box|link)\.info\.\w+ :", source)
    for name in re.findall(r"(?:color|text): (?:box|link)\.info\.(\w+)\s*$", source, re.M):
        raise AssertionError(f"info.{name} is assigned without a fallback")
