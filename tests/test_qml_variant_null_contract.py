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


# The only two spellings that survive the QVariant round trip. Anything else
# that mentions null is either always true or always false.
_ACCEPTED_PAIRS = (
    r"{e}\s*===\s*null\s*\|\|\s*{e}\s*===\s*undefined",
    r"{e}\s*===\s*undefined\s*\|\|\s*{e}\s*===\s*null",
    r"{e}\s*!==\s*null\s*&&\s*{e}\s*!==\s*undefined",
    r"{e}\s*!==\s*undefined\s*&&\s*{e}\s*!==\s*null",
)


def _null_comparisons(line: str, names: set[str]) -> list[str]:
    """Return the null comparisons on ``line`` that this contract rejects.

    Both the property itself and any member read from it go through the same
    QVariant round trip, so ``control.value === null`` is as unsafe as
    ``selectedItem === null``.

    A comparison is accepted only as part of a complete null-or-undefined
    check: ``x === null || x === undefined`` or ``x !== null && x !== undefined``
    in either order. Merely mentioning ``undefined`` somewhere on the line is
    not enough, because ``x !== null || x !== undefined`` is always true and
    ``x === null && x === undefined`` is always false - the accepted pairs are
    removed from the line first, and whatever still compares against null is
    reported.
    """

    offenders: list[str] = []
    for name in sorted(names):
        # Capture the whole dotted chain, including any object qualifier, so
        # that entitySummary.summary.position is compared as one expression.
        pattern = (
            rf"((?:\w+\.)*\b{re.escape(name)}(?:\.\w+)*)\s*(===|!==)\s*null\b"
        )
        remaining = line
        for expression, _ in re.findall(pattern, line):
            escaped = re.escape(expression)
            for shape in _ACCEPTED_PAIRS:
                remaining = re.sub(shape.format(e=escaped), "", remaining)
        offenders.extend(
            f"{expression} {operator} null"
            for expression, operator in re.findall(pattern, remaining)
        )
    return offenders


def _declared_variant_properties() -> set[str]:
    """Collect variant property names across every device QML file.

    A variant read in one file can be declared in another, so the names are
    pooled rather than checked only against the file that declares them.
    """

    names: set[str] = set()
    for path in sorted(QML_DIR.rglob("*.qml")):
        names |= _variant_properties(path.read_text(encoding="utf-8"))
    return names


def test_null_guard_rejects_incomplete_and_always_true_checks() -> None:
    names = {"selectedItem", "control"}

    assert _null_comparisons("visible: selectedItem === null", names)
    assert _null_comparisons("x: control.value !== null", names)
    # always true
    assert _null_comparisons(
        "visible: selectedItem !== null || selectedItem !== undefined", names
    )
    # always false
    assert _null_comparisons(
        "visible: selectedItem === null && selectedItem === undefined", names
    )
    # unrelated expression mentioning undefined does not excuse it
    assert _null_comparisons(
        "visible: selectedItem === null && control.value !== undefined", names
    )

    assert not _null_comparisons(
        "return control.value === null || control.value === undefined", names
    )
    assert not _null_comparisons(
        "visible: control.value !== null && control.value !== undefined", names
    )
    assert not _null_comparisons("visible: !selectedItem && control", names)


def test_device_qml_never_compares_variant_properties_to_null() -> None:
    offenders: list[str] = []
    checked = 0

    names = _declared_variant_properties()
    for path in sorted(QML_DIR.rglob("*.qml")):
        text = path.read_text(encoding="utf-8")
        checked += 1
        for number, line in enumerate(text.splitlines(), start=1):
            for comparison in _null_comparisons(line, names):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{number}: {comparison} -> use "
                    "truthiness, or a complete null-or-undefined check"
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
