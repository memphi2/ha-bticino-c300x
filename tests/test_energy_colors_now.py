"""Source colors, bounded tariff stacks and the Now-only power label lanes."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.bticino_c300x.dashboard_energy import (
    COLOR_BATTERY,
    COLOR_EXPORT,
    COLOR_GRID,
    COLOR_GRID_METERS,
    COLOR_GRID_OTHER,
    COLOR_HOME,
    COLOR_SOLAR,
    EnergyDay,
    EnergyMeter,
    EnergySources,
    energy_page,
)
from custom_components.bticino_c300x.dashboard_energy_power import (
    PowerHistory,
    power_history_payload,
)

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "device_qml/C300XEnergy.qml"
SCRIPT = ROOT / "scripts/check_energy_layout.py"


def sources(count=4):
    return EnergySources(
        grid_from=tuple(EnergyMeter(f"grid{i}", f"cost{i}", f"Meter {i}") for i in range(count)),
        grid_to=(EnergyMeter("export"),), solar=(EnergyMeter("solar"),),
        battery_from=(EnergyMeter("discharge"),), battery_to=(EnergyMeter("charge"),),
        grid_power=("grid_power",), solar_power=("solar_power",), battery_power=("battery_power",),
    )


def test_source_colors_match_now_today_and_power():
    setup = sources(1)
    watts = {"grid_power": 1300.0, "solar_power": 400.0, "battery_power": -100.0}
    energy = energy_page(setup, EnergyDay(), watts)["energy"]
    start = datetime(2026, 11, 15, tzinfo=UTC)
    history = PowerHistory(start, start + timedelta(minutes=15), {key: (value,) for key, value in watts.items()})
    curves = power_history_payload(setup, history, "en")["series"]
    palette = {"grid": COLOR_GRID, "solar": COLOR_SOLAR, "battery": COLOR_BATTERY, "home": COLOR_HOME}
    assert len(set(palette.values())) == 4
    assert COLOR_GRID == "#75bfff"
    assert {key: node["color"] for key, node in energy["nodes"].items()} == palette
    assert {curve["id"]: curve["color"] for curve in curves} == palette
    assert [entry["color"] for entry in energy["hours"]["series"]] == [COLOR_GRID, COLOR_SOLAR, COLOR_BATTERY, COLOR_EXPORT]


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 12])
@pytest.mark.parametrize("missing", [False, True])
def test_tariff_stack_colors_match_bounded_rows_and_preserve_totals(count, missing):
    setup = sources(count)
    day = EnergyDay(
        hours={f"grid{i}": [float(i + 1)] * 24 for i in range(count) if not missing or i % 2 == 0},
        costs={f"cost{i}": float(i + 1) for i in range(count)},
    )
    energy = energy_page(setup, day, {})["energy"]
    series = energy["hours"]["series"][:-3]
    rows = [row for row in energy["sums"] if row["label"].startswith("Meter ") or row["label"] == "Other meters"]
    assert len(energy["sums"]) <= 8
    assert len(series) == len(rows) <= len(COLOR_GRID_METERS)
    assert len({entry["color"] for entry in series}) == len(series)
    assert [entry["color"] for entry in series] == [row["color"] for row in rows]
    for hour in range(24):
        assert sum(entry["values"][hour] for entry in series) == day.hourly(setup.grid_from)[hour]
    assert sum(float(row["value"].split()[0]) for row in rows) == sum(day.hourly(setup.grid_from))
    assert sum(float(row["cost"]) for row in rows) == sum(day.costs.values())
    if count > 3:
        assert rows[-1]["label"] == "Other meters"
        assert rows[-1]["color"] == series[-1]["color"] == COLOR_GRID_OTHER
    if count > 1:
        assert energy["sums"][-1]["color"] == energy["nodes"]["grid"]["color"] == COLOR_GRID


def test_unknown_power_is_not_fabricated_and_zero_remains_visible():
    unknown = energy_page(sources(), EnergyDay(), {})["energy"]["nodes"]
    zero = energy_page(sources(), EnergyDay(), dict.fromkeys(("grid_power", "solar_power", "battery_power"), 0.0))["energy"]["nodes"]
    assert all("power" not in node for node in unknown.values())
    assert all(node["power"] == "0 W" and node["flow"] == 0 for node in zero.values())


@pytest.mark.parametrize("order", [(0, 1, 2, 3, 4), (3, 4, 0, 1, 2)])
@pytest.mark.parametrize("values,expected", [
    ((0, 0, 0, -1.5, 2), 0.5),
    ((0, 0, 0, -3, 2), 0),
    ((0.0006, 0.0006, 0.0006, 0.0006, 0), 0.002),
])
def test_grid_corrections_and_rounding_preserve_total_across_other_group(order, values, expected):
    setup = EnergySources(grid_from=tuple(EnergyMeter(f"grid{i}", name=f"Meter {i}") for i in order))
    day = EnergyDay(hours={f"grid{i}": [value] * 24 for i, value in enumerate(values)})
    energy = energy_page(setup, day, {}, views=["today"])["energy"]
    for hour in range(24):
        segments = [series["values"][hour] for series in energy["hours"]["series"]]
        assert all(value >= 0 for value in segments)
        assert sum(segments) == pytest.approx(expected)
    assert energy["hours"]["max"] == expected


def test_now_label_geometry_uses_production_bindings_at_all_fixture_sizes():
    """Evaluate QML's JS bindings locally; no Qt installation or device needed."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to evaluate the production QML bindings")
    program = r'''
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
const source = fs.readFileSync(process.argv[1], "utf8");
assert(source.startsWith("import QtQuick 1.1\n"));
assert(!source.includes("id: boxPower"));
const linkSource = source.split("id: link")[1].split("Rectangle {")[0];
const arrowSource = source.split("id: flowArrow")[1].split("\n                }")[0];
const powerSource = source.split("id: flowPower")[1].split("\n                }")[0];
assert(powerSource.includes("anchors.top: flowArrow.bottom"));
assert(powerSource.includes("anchors.horizontalCenter: flowArrow.horizontalCenter"));
assert(powerSource.includes("elide: Text.ElideRight"));
const evaluate = (body, name, ctx) => vm.runInContext(body.match(new RegExp("^\\s*" + name.replaceAll(".", "\\.") + ": (.+)$", "m"))[1], ctx);
const overlaps = (a, b) => Math.min(a[0]+a[2], b[0]+b[2]) > Math.max(a[0], b[0]) && Math.min(a[1]+a[3], b[1]+b[3]) > Math.max(a[1], b[1]);
for (const height of [300, 230]) for (const tabs of [0, 40]) {
    const bodyHeight = height - tabs - (tabs ? 8 : 0);
    const root = {width: 728, node: () => ({flow: 1}), hasNode: () => true};
    const ctx = vm.createContext({root, width: root.width, boxWidth: 168, boxHeight: 76, bodyHeight});
    for (const name of ["slotX", "slotY"]) {
        const method = source.match(new RegExp("function " + name + "\\(key\\) \\{([\\s\\S]*?)\\n    \\}"))[0];
        vm.runInContext(method, ctx);
        root[name] = key => ctx[name](key);
    }
    const keys = ["solar", "grid", "home", "battery"];
    const boxes = keys.map(key => [root.slotX(key), root.slotY(key), 168, 76]);
    const labels = [], arrows = [];
    for (const key of keys) {
        ctx.modelData = key;
        for (const match of linkSource.matchAll(/^\s*(?:property \w+ )?(\w+): (.+)$/gm)) {
            ctx[match[1]] = vm.runInContext(match[2], ctx);
        }
        ctx.link = {width: ctx.width};
        const aw = evaluate(arrowSource, "width", ctx), ah = evaluate(arrowSource, "height", ctx);
        const pw = evaluate(powerSource, "width", ctx), ph = evaluate(powerSource, "height", ctx);
        const gap = evaluate(powerSource, "anchors.topMargin", ctx);
        const arrow = [ctx.x + (ctx.width-aw)/2, ctx.y + (ctx.height-ah)/2, aw, ah];
        const label = [ctx.x + (ctx.width-pw)/2, arrow[1]+ah+gap, pw, ph];
        assert(label[0] >= 0 && label[1] >= 0 && label[0]+pw <= 728 && label[1]+ph <= bodyHeight);
        for (const box of boxes) assert(!overlaps(label, box), `${height}/${tabs}/${key}: node overlap`);
        for (const other of labels) assert(!overlaps(label, other), `${height}/${tabs}/${key}: label overlap`);
        labels.push(label); arrows.push(arrow);
    }
    for (const label of labels) for (const arrow of arrows) assert(!overlaps(label, arrow));
}
'''
    result = subprocess.run([node, "-e", program, str(QML)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_now_rendered_labels_stay_below_arrows_and_outside_nodes(tmp_path):
    interpreter = os.environ.get("C300X_QML_PYTHON")
    if not interpreter:
        if importlib.util.find_spec("PySide6") is None:
            pytest.skip("Optional PySide6 absent; set C300X_QML_PYTHON for raster checks")
        interpreter = sys.executable
    spec = importlib.util.spec_from_file_location("energy_now_harness", SCRIPT)
    assert spec and spec.loader
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    fixtures = harness.make_fixtures()
    for fixture in list(fixtures):
        for mode in ("zero", "missing", "reverse", "long"):
            extra = json.loads(json.dumps(fixture))
            extra["name"] += "-" + mode
            for entry in extra["energy"]["nodes"].values():
                if mode == "missing":
                    entry.pop("power", None)
                else:
                    entry["power"] = "0 W" if mode == "zero" else "123456789 kW" if mode == "long" else entry["power"]
                entry["flow"] = -1 if mode == "reverse" else 0
            fixtures.append(extra)
    payload = tmp_path / "fixtures.json"
    payload.write_text(json.dumps(fixtures))
    result = subprocess.run(
        [interpreter, str(SCRIPT), "--fixtures", str(payload), "--views", "now",
         "--scenarios", *sorted({fixture["name"] for fixture in fixtures}),
         "--output", str(tmp_path / "render"), "--check"],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "render/report.json").read_text())
    assert len(report["cases"]) == len(fixtures) * 4
    for case in report["cases"]:
        assert not case["issues"]
        assert not case["warnings"]
        body = case["height"] - (48 if case["tabs"] == "multi" else 0)
        boxes = [[0, (body - 76) // 2, 168, 76], [560, (body - 76) // 2, 168, 76],
                 [280, 0, 168, 76], [280, body - 76, 168, 76]]
        labels = [item for item in case["texts"] if item["id"] == "flowPower"]
        assert len(labels) == (0 if "missing" in case["name"] else 4)
        for label in labels:
            for box in boxes:
                width, height = harness.rect_intersection(label["ink"], box)
                assert width <= 0 or height <= 0
            if "long" not in case["name"]:
                assert not label["truncated"]
