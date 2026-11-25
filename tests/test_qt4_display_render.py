"""Display pages shown on the station's own Qt 4.8, where the Qt 6 harness sees no fault."""

from __future__ import annotations

import json
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
    assert [line for line in output.splitlines() if "QT4_FAIL today" in line] == []
    assert "C300X_ENERGY_QT4_PASS " in output, output[-800:]


def test_energy_flow_arrows_sit_on_their_lines_on_qt4(station):
    """Each arrow of Now is centred on its line, whichever way it points and whenever it was turned."""
    output = energy_page(station)
    faults = [line for line in output.splitlines() if "QT4_FAIL now" in line]
    assert faults == []
    assert "C300X_ENERGY_QT4_PASS 27" in output, output[-800:]


def test_energy_views_raise_no_qml_warning_on_qt4(station):
    assert qt4_render.warnings(energy_page(station)) == []


@pytest.mark.parametrize("host", ["HomeAssistant", "Alarm"])
def test_page_opens_without_qml_warning_on_qt4(station, host):
    """A page that opens before any data arrived assigns no missing value to a property."""
    source = (ROOT / "tests/qml/page_load_qt4.qml").read_text().replace("@HOST@", host)
    output = station.show("ProbePage" + host, source, 1500)
    assert "C300X_PAGE_QT4_SHOWN " + host in output, output[-800:]
    assert qt4_render.warnings(output) == []


LONG_NAME = "Mein sehr langer Instanzname hier"
ADDRESSES = (
    "https://homeassistant.my-very-long-home-name.example.duckdns.org:8123",
    "http://[fd00:1234:5678:9abc:def0:1234:5678:9abc]:8123",
    "http://averyveryverylonghostnamewithoutanydotsatallinsideit-andmore:8123",
    "https://ha.example.duckdns.org:8123",
)


def settings_tab(station, language: str, *, reachable: bool = True, switch: bool = False, end: bool = False,
                 name: str = LONG_NAME, background: str = "", picture: Path | None = None) -> str:
    """The vendor Settings page with the Integration tab open, fed by a stand-in agent."""
    station.patch_vendor_pages()
    details = {"ok": True, "integration_version": "2.9.3", "instance_name": name, "preventReturnToHomepage": False,
               "navigation": "tabs"}
    agent = qt4_render.Agent({
        "/ui/maintenance": (200, {"ok": True, "ssh": True, "reboot": True, "remove": True}),
        "/ui/maintenance/ssh": (200, {"ok": True, "running": True}),
        "/ui/status": (200, {"ok": True, "version": "2.9.3", "firmware": "1.7.19", "registered": reachable,
                             "home_assistant": "http://192.0.2.10:8123", "last_contact_age": 20 if reachable else 7300}),
        "/ui/state": (200, details) if reachable else (502, {"ok": False}),
        "/homeassistant": (503, {"ok": False}),
    })
    try:
        source = (ROOT / "tests/qml/settings_tab_qt4.qml").read_text()
        values = {"LANGUAGE": language, "BASE": agent.url, "ADDRESSES": json.dumps(ADDRESSES), "SWITCH": json.dumps(switch),
                  "END": json.dumps(end), "BACKGROUND": background}
        for key, value in values.items():
            source = source.replace(f"@{key}@", value)
        return station.show("ProbeSettingsTab", source, 5000, picture)
    finally:
        agent.close()


@pytest.fixture(scope="module")
def tab(station):
    """Show each state of the tab once per run: language, and whether Home Assistant answers."""
    shown: dict[tuple[str, bool], dict[str, dict]] = {}

    def stages(language: str, reachable: bool = True) -> dict[str, dict]:
        if (language, reachable) not in shown:
            output = settings_tab(station, language, reachable=reachable, switch=reachable)
            assert "C300X_TAB_QT4_DONE" in output, output[-1500:]
            reports = [json.loads(line.split("C300X_TAB_QT4 ", 1)[1]) for line in output.splitlines() if "C300X_TAB_QT4 " in line]
            shown[language, reachable] = {report["stage"]: report for report in reports} | {"output": {"text": output}}
        return shown[language, reachable]

    return stages


def tab_text(report: dict, name: str) -> dict:
    return next(text for text in report["texts"] if text["name"] == name)


def test_integration_tab_address_keeps_its_start_and_its_port_on_qt4(tab):
    """Measured in the station's font: two lines at most, inside the value column, the port at the end."""
    stages = tab("de")
    for address in ADDRESSES:
        report = stages["address " + address]
        value = tab_text(report, "statusValue1")
        assert value["lines"] <= 2 and value["right"] <= report["column"][1] - 12, value
        if "\u2026" not in value["text"]:
            assert value["text"].replace("\n", "") == address
            continue
        start, end = value["text"].split("\n\u2026")
        assert address.startswith(start) and address.endswith(end), value["text"]
        assert len(start) >= 30 and end.endswith(":8123") and len(end) >= 30, "both lines are used: " + value["text"]
    shown = {address: tab_text(stages["address " + address], "statusValue1")["text"] for address in ADDRESSES}
    assert shown[ADDRESSES[3]] == ADDRESSES[3], "an address that fits stays in one line"
    assert shown[ADDRESSES[1]] == "http://[fd00:1234:5678:9abc:def0:\n1234:5678:9abc]:8123"
    assert "\u2026" in shown[ADDRESSES[2]], "the host without a dot is longer than two lines"


def display_text(language: str, key: str) -> str:
    texts = (ROOT / "device_qml/js/c300x_i18n.js").read_text()
    table = texts[texts.index(f"var {language.upper()} = {{"):]
    return json.loads(re.search(rf'^    "{key}": (".*"),?$', table, re.M).group(1))


@pytest.mark.parametrize("reachable", [True, False], ids=["reachable", "not_reachable"])
@pytest.mark.parametrize("language", ["de", "en", "it", "fr"])
def test_integration_tab_texts_stay_in_their_column_on_qt4(tab, language, reachable):
    """Every text of the tab ends inside the column; the values and the reason keep its 12 px inset.

    Qt 4.8 does not elide a single line that has a line limit. The instance
    name "Mein sehr langer Instanzname hier" made the first value 373 px
    wide in a 306 px column: it ran out of the panel and off the screen.
    """
    stages = tab(language, reachable)
    for stage, report in stages.items():
        if stage == "output":
            continue
        left, right = report["column"]
        assert 0 <= left < right <= 800
        for text in report["texts"]:
            inset = 12 if text["name"] else 0
            assert left + inset - 0.5 <= text["left"] and text["right"] <= right - inset + 0.5, (stage, text)
    first = stages["first"]
    assert first["reachable"] is reachable
    state = tab_text(first, "statusValue0")
    assert state["lines"] == 1 and state["text"].startswith(display_text(language, "status_ok" if reachable else "status_down"))
    if reachable:
        assert state["text"].endswith(f"({LONG_NAME})"), "the name is long enough to need the elision"
    else:
        reason = tab_text(first, "bridgeReason")
        assert reason["text"] == display_text(language, "bridge_unreachable") and reason["lines"] >= 2
        assert reason["bottom"] <= first["view"][1], "the reason shows without scrolling"


def test_integration_tab_raises_no_qml_warning_on_qt4(tab):
    """Of our files only: the vendor page reports types its own program provides, which the probe lacks."""
    for reachable in (True, False):
        found = qt4_render.warnings(tab("de", reachable)["output"]["text"])
        assert [line for line in found if re.match(r"C300X|c300x_|ProbeSettingsTab", line)] == []


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
