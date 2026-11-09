"""Guard the QtQuick 1.1 contract that ``property variant`` cannot hold JS null.

The C300X display runs QtQuick 1.1 (Qt 4.8), where a ``variant`` property is
stored as a ``QVariant``. A JavaScript ``null`` does not survive that round
trip and reads back as ``undefined``, so ``x === null`` is false and
``x !== null`` is true for a property that was explicitly set to ``null``.
Gating visibility on such a comparison silently inverts it. Qt 5 introduced
``var`` for exactly this reason; QtQuick 1.1 has no equivalent.

Nothing in the test suite can execute QtQuick property semantics, so this
contract is enforced on the source instead.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "device_qml"

_VARIANT_DECLARATION = re.compile(r"^\s*property\s+variant\s+([A-Za-z_]\w*)", re.MULTILINE)


def _variant_properties(text: str) -> set[str]:
    return set(_VARIANT_DECLARATION.findall(text))


def test_device_qml_never_compares_variant_properties_to_null() -> None:
    offenders: list[str] = []
    checked = 0

    for path in sorted(QML_DIR.glob("*.qml")):
        text = path.read_text(encoding="utf-8")
        names = _variant_properties(text)
        if not names:
            continue
        checked += 1
        for number, line in enumerate(text.splitlines(), start=1):
            for name in names:
                for operator in ("===", "!=="):
                    if re.search(rf"\b{re.escape(name)}\s*{re.escape(operator)}\s*null\b", line):
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{number}: "
                            f"{name} {operator} null -> use truthiness instead"
                        )

    assert checked, "no QML file with variant properties was inspected"
    assert not offenders, "\n".join(offenders)


def test_dashboard_container_is_gated_on_an_explicit_boolean() -> None:
    text = (QML_DIR / "HomeAssistant.qml").read_text(encoding="utf-8")

    # The whole dashboard column (badges, weather, flow, tiles, pager) hangs off
    # this one gate. It must not depend on variant null identity again.
    assert "property bool detailOpen: selectedItem ? true : false" in text
    assert "visible: !detailOpen && !notificationsOpen" in text
    assert "visible: detailOpen || notificationsOpen" in text
