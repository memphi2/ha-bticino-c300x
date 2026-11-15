#!/usr/bin/env python3
"""Offscreen visual checks of production C300XEnergy.qml, without device I/O.

Run with an optional PySide6 environment, not the integration runtime::

    /path/to/qt-python scripts/check_energy_layout.py \
        --fixture-python /path/to/ha-python --output .artifacts/energy/before

Qt Quick 1.1 is adapted to Qt Quick 2 only in a temporary directory. The
surrounding 800x480 frame and two vendor component mocks are approximations;
this is not a substitute for Qt 4/device verification. Text geometry, resolved
fonts, image hashes, diagnostics and the source hash are recorded in report.json.
No firmware assets are bundled. --stock-skin optionally reads local images;
otherwise generated blue button backgrounds and the system font are used.
--fixtures accepts a JSON list of {name, language, title, energy} objects, so new
backend view contracts can be exercised without changing this renderer.
Default power fixtures pass synthetic recorder intervals through production
aggregation and formatting. Raster probes check scalar curves, gaps and dots.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("de", "en", "fr", "it")


def make_fixtures(include_consumers: bool = False) -> list[dict]:
    """Use the production pure formatter in an existing HA Python environment."""
    sys.path.insert(0, str(ROOT))
    from custom_components.bticino_c300x.dashboard_energy import (
        EnergyDay,
        energy_page,
        energy_sources,
    )
    from custom_components.bticino_c300x.dashboard_energy_power import (
        power_history_from_statistics,
        power_history_payload,
    )

    fixtures = []
    for language in LANGUAGES:
        for scenario in ("normal", "stress"):
            stress = scenario == "stress"
            sources = energy_sources({"energy_sources": [
                *({"type": "grid", "stat_energy_from": f"grid{i}",
                   "stat_cost": f"cost{i}", "stat_rate": f"power{i}",
                   "name": ("Garage / Werkstatt / Waermepumpe - Nebengebaeude "
                            if stress else "Meter ") + str(i + 1),
                   **({"stat_energy_to": "export", "stat_compensation": "refund"} if i == 0 else {})}
                  for i in range(4)),
                {"type": "solar", "stat_energy_from": "solar", "stat_rate": "solar_power"},
                {"type": "battery", "stat_energy_from": "discharge", "stat_energy_to": "charge",
                 "stat_rate": "battery_power"},
            ], "device_consumption": [{"stat_consumption": f"sensor.consumer_{i}_energy",
                                       "stat_rate": f"sensor.consumer_{i}_power", "name": f"Consumer {i + 1}"}
                                      for i in range(10)]}, include_consumers=include_consumers)
            scale = 500.0 if stress else 1.0
            hours = {f"grid{i}": [round(scale * (0.15 + (hour + i) % 7 * 0.14), 3)
                                  for hour in range(24)] for i in range(4)}
            hours.update({
                "solar": [scale * max(0, 1.8 - abs(hour - 12) * 0.3) for hour in range(24)],
                "export": [scale * 0.08 if 10 <= hour <= 15 else 0 for hour in range(24)],
                "discharge": [scale * 0.2 if hour > 17 else 0 for hour in range(24)],
                "charge": [scale * 0.15 if 10 <= hour <= 15 else 0 for hour in range(24)],
            })
            day = EnergyDay(hours=hours, costs={
                **{f"cost{i}": (12345.67 * (i + 1) if stress else 1.85 * (i + 1)) for i in range(4)},
                "refund": 4321.09 if stress else 0.11,
            })
            powers = {**{f"power{i}": scale * (300 + 50 * i) for i in range(4)},
                      "solar_power": scale * 1250, "battery_power": scale * -280}
            page = energy_page(sources, day, powers,
                               language=language, currency="EUR",
                               views=["now", "today", "power", *(["consumers"] if include_consumers else []), "balance"],
                               consumer_states={f"sensor.consumer_{i}_power": SimpleNamespace(
                                   state=str(scale * value), attributes={"unit_of_measurement": "W"})
                                   for i, value in enumerate((22000, 11000, 2450, 1450, 620, 410, 210, 95, 62, 10))})
            assert page is not None
            assert len(page["energy"]["sums"]) == 8
            start = datetime(2026, 11, 15, tzinfo=UTC)
            # Missing five-minute intervals go through the real quarter-hour
            # aggregator. Bucket 42 is isolated between two gaps on each side.
            statistics = {
                entity: [{"start": start.timestamp() + i * 900 + part * 300,
                          "end": start.timestamp() + i * 900 + (part + 1) * 300,
                          "mean": value * ((0.5 if entity == "battery_power" else 0.7)
                                           + math.sin(i / 12) * (1 if entity == "battery_power" else 0.5))}
                         for i in range(96) if not 40 <= i < 45 or i == 42
                         for part in range(3)] for entity, value in powers.items()
            }
            history = power_history_from_statistics(
                start, start + timedelta(days=1), frozenset(powers), statistics,
            )
            page["energy"]["power"] = power_history_payload(sources, history, language)
            fixtures.append({"name": scenario, "language": language, **page,
                             "power_probe": {"isolated_index": 42, "gap_indices": [40, 41, 43, 44]}})
    return fixtures


def adapt_qml(source: str) -> str:
    """Keep layout expressions intact; replace only imports for local mocks."""
    source, count = re.subn(r"(?m)^import QtQuick 1\.1\s*$", "import QtQuick 2.15", source)
    if count != 1:
        raise ValueError("Expected exactly one QtQuick 1.1 import")
    return re.sub(r"(?m)^import Components(?:\.Styles)? 1\.0\s*\n", "", source)


def energy_dependencies(source: str, qml: Path, revision: str | None = None) -> dict[str, str]:
    """Follow only Energy-local QML and JS, including temporary test overrides."""
    result = {}
    pending = [source]
    while pending:
        current = pending.pop()
        names = {name + ".qml" for name in re.findall(r"\b(C300XEnergy[A-Z]\w*)\b", current)}
        names.update(re.findall(r'import "(js/c300x_energy\w*\.js)"', current))
        for name in sorted(names - result.keys()):
            if revision:
                body = subprocess.run(["git", "show", f"{revision}:device_qml/{name}"],
                                      cwd=ROOT, capture_output=True, text=True, check=True).stdout
            else:
                path = qml.parent / name
                body = (path if path.is_file() else ROOT / "device_qml" / name).read_text()
            result[name] = body
            pending.append(body)
    return result


def rect_intersection(a: list[float], b: list[float]) -> tuple[float, float]:
    return (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]),
            min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


def layout_issues(texts: list[dict], bounds: list[float]) -> list[dict]:
    """Check rendered text, not overlapping layout boxes or hidden delegates."""
    issues = []
    for item in texts:
        x, y, width, height = item["ink"]
        if item["box"][2] < 0 or item["box"][3] < 0:
            issues.append({"kind": "negative_text_box", "text": item["text"], "id": item["id"]})
        if width > 0 and height > 0 and (
            x < bounds[0] - 1 or y < bounds[1] - 1
            or x + width > bounds[0] + bounds[2] + 1
            or y + height > bounds[1] + bounds[3] + 1
        ):
            issues.append({"kind": "outside_component", "text": item["text"], "id": item["id"]})
        content_width = item.get("content_width", width)
        allocated_width = item.get("allocated_width", item["box"][2])
        if item["elide"] == 3 and item["wrap"] == 0 and content_width > allocated_width + 1:
            issues.append({"kind": "text_overflow", "text": item["text"], "id": item["id"],
                           "painted_width": content_width, "allocated_width": allocated_width})
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            width, height = rect_intersection(first["ink"], second["ink"])
            if width > 1 and height > 1:
                issues.append({"kind": "text_overlap", "texts": [first["text"], second["text"]],
                               "ids": [first["id"], second["id"]],
                               "intersection": [round(width, 2), round(height, 2)]})
    return issues


def render(args, fixtures: list[dict]) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    from PySide6.QtCore import (
        QPoint,
        QPointF,
        QRectF,
        Qt,
        QUrl,
        qInstallMessageHandler,
        qVersion,
    )
    from PySide6.QtGui import QColor, QFontInfo, QGuiApplication, QImage, QPainter, QPen
    from PySide6.QtQml import QQmlEngine
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest

    app = QGuiApplication.instance() or QGuiApplication([])
    messages = []
    previous_handler = qInstallMessageHandler(lambda _kind, _context, message: messages.append(message))
    source = (subprocess.run(["git", "show", f"{args.revision}:device_qml/C300XEnergy.qml"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
              if args.revision else args.qml.read_text())
    report = {"qml": str(args.qml.resolve()), "sha256": hashlib.sha256(source.encode()).hexdigest(),
              "revision": args.revision,
              "qt": qVersion(), "renderer": "Qt Quick 2 offscreen software", "frame": [800, 480],
              "fixtures_sha256": hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest(),
              "stock_skin": str(args.stock_skin) if args.stock_skin else None,
              "cases": []}

    def settle():
        for _ in range(5):
            app.processEvents()
            QTest.qWait(12)

    def text_bounds(root):
        result = []

        def visit(item, path):
            if not item.isVisible() or item.opacity() <= 0:
                return
            text = item.property("text")
            if isinstance(text, str) and text:
                font = item.property("font")
                info = QFontInfo(font)
                width = float(item.property("contentWidth") or item.property("paintedWidth") or 0)
                height = float(item.property("contentHeight") or item.property("paintedHeight") or 0)
                enums = enum_values.call([window.engine().newQObject(item)]).toVariant()
                align = enums["align"]
                x = item.width() - width if align == 2 else (item.width() - width) / 2 if align == 4 else 0
                valign = enums["valign"]
                y = item.height() - height if valign == 64 else (item.height() - height) / 2 if valign == 128 else 0
                ink = item.mapRectToItem(root, QRectF(x, y, width, height))
                box = item.mapRectToItem(root, item.boundingRect())
                context = QQmlEngine.contextForObject(item)
                name = context.nameForObject(item) if context else ""
                color = item.property("color")
                result.append({"id": name or path, "text": text,
                               "box": [box.x(), box.y(), box.width(), box.height()],
                               "ink": [ink.x(), ink.y(), ink.width(), ink.height()],
                               "content_width": width, "allocated_width": item.width(),
                               "rotation": item.rotation(),
                               "font": {"requested": font.family(), "resolved": info.family(),
                                        "pixels": info.pixelSize(), "weight": int(info.weight())},
                               "color": color.name() if isinstance(color, QColor) else str(color),
                               "truncated": bool(item.property("truncated")),
                               "elide": enums["elide"], "wrap": enums["wrap"]})
            for index, child in enumerate(item.childItems()):
                visit(child, f"{path}/{index}")

        visit(root, "energy")
        return result

    def power_pixels(component, frame, shot, fixture):
        """Check actual rasterized dots/gaps against the backend coordinates."""
        if not fixture.get("power_probe"):
            return [], {}

        def named(item, name):
            context = QQmlEngine.contextForObject(item)
            if context and context.nameForObject(item) == name:
                return item
            for child in item.childItems():
                found = named(child, name)
                if found is not None:
                    return found
            return None

        plot = named(component, "powerPlot")
        if plot is None:
            return [{"kind": "power_plot_missing"}], {}
        series = fixture["energy"]["power"]["series"]
        colors = [QColor(entry["color"]) for entry in series]
        origin = plot.mapToItem(frame, QPointF(0, 0))
        probe = fixture["power_probe"]
        checks = {"dots": [], "gaps": [], "segments": []}
        issues = []

        def matches(x, y, color):
            if not 0 <= x < shot.width() or not 0 <= y < shot.height():
                return False
            actual = shot.pixelColor(x, y)
            return max(abs(actual.red() - color.red()), abs(actual.green() - color.green()),
                       abs(actual.blue() - color.blue())) <= 35

        for entry, color in zip(series, colors, strict=True):
            axis = fixture["energy"]["power"]["axis"]
            points = [None if value is None else (value - axis["min"]) / (axis["max"] - axis["min"])
                      for value in entry["values"]]
            point = points[probe["isolated_index"]]
            if any(value is not None and not isinstance(value, (float, int)) for value in points):
                issues.append({"kind": "power_points_not_scalars", "series": entry["id"]})
                continue
            dot = {"x": round((probe["isolated_index"] + 0.5) / len(points), 6), "y": point}
            if point is None or entry.get("dots") != [probe["isolated_index"]]:
                issues.append({"kind": "power_isolated_contract", "series": entry["id"]})
                continue
            x = round(origin.x() + dot["x"] * plot.width())
            y = round(origin.y() + (1 - dot["y"]) * plot.height())
            visible = any(matches(x + dx, y + dy, color) for dx in range(-2, 3) for dy in range(-2, 3))
            checks["dots"].append({"series": entry["id"], "center": [x, y], "visible": visible})
            if not visible:
                issues.append({"kind": "power_dot_missing", "series": entry["id"]})
            # A dot alone must not let a broken scalar curve renderer pass.
            adjacent = next(i for i in range(len(points) - 1)
                            if points[i] is not None and points[i + 1] is not None)
            x = round(origin.x() + (adjacent + 1) / len(points) * plot.width())
            y = round(origin.y() + (1 - (points[adjacent] + points[adjacent + 1]) / 2) * plot.height())
            visible = any(matches(x + dx, y + dy, color) for dx in range(-2, 3) for dy in range(-2, 3))
            checks["segments"].append({"series": entry["id"], "center": [x, y], "visible": visible})
            if not visible:
                issues.append({"kind": "power_segment_missing", "series": entry["id"]})
        for index in probe["gap_indices"]:
            if any(entry["values"][index] is not None for entry in series):
                issues.append({"kind": "power_gap_contract", "index": index})
                continue
            x = round(origin.x() + (index + 0.5) / len(series[0]["values"]) * plot.width())
            painted = any(matches(x, y, color) for color in colors
                          for y in range(math.ceil(origin.y()) + 2, math.floor(origin.y() + plot.height()) - 2))
            checks["gaps"].append({"index": index, "x": x, "clear": not painted})
            if painted:
                issues.append({"kind": "power_gap_bridged", "index": index})
        return issues, checks

    try:
        with tempfile.TemporaryDirectory(prefix="c300x-energy-layout-") as temp:
            directory = Path(temp)
            adapted = adapt_qml(source)
            if args.stock_skin:
                images = args.stock_skin.resolve() / "images"
                if not images.is_dir():
                    raise ValueError("--stock-skin must be the skin directory containing images/")
                (directory / "images").symlink_to(images, target_is_directory=True)
            else:
                for asset in set(re.findall(r'"(images/[^"\n]+\.svg)"', adapted)):
                    target = directory / Path(asset).with_suffix(".png")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    image = QImage(32, 32, QImage.Format_ARGB32)
                    image.fill(QColor("#24547b" if "list_" in asset else "#19476b"))
                    image.save(str(target))
                    adapted = adapted.replace(asset, str(Path(asset).with_suffix(".png")))
            (directory / "C300XEnergy.qml").write_text(adapted)
            report["dependencies"] = {}
            for dependency, dependency_source in energy_dependencies(source, args.qml, args.revision).items():
                target = directory / dependency
                target.parent.mkdir(parents=True, exist_ok=True)
                (args.output / dependency).parent.mkdir(parents=True, exist_ok=True)
                target.write_text(adapt_qml(dependency_source) if dependency.endswith(".qml") else dependency_source)
                (args.output / dependency).write_text(dependency_source)
                report["dependencies"][dependency] = hashlib.sha256(dependency_source.encode()).hexdigest()
            (args.output / "source.qml").write_text(source)
            (directory / "UbuntuLightText.qml").write_text(
                'import QtQuick 2.15\nText { textFormat: Text.PlainText; '
                'font.family: "Ubuntu"; font.weight: Font.Light }\n')
            (directory / "BeepingMouseArea.qml").write_text('import QtQuick 2.15\nMouseArea {}\n')
            (directory / "Frame.qml").write_text('''import QtQuick 2.15
Rectangle {
    width: 800; height: 480; color: "#123f65"
    property string title: "Energy"
    property bool compact: false
    property int energyHeight: 300
    Rectangle { width: parent.width; height: 64; color: "#16334c" }
    UbuntuLightText { x: 36; y: 19; text: "<"; color: "white"; font.pixelSize: 24 }
    UbuntuLightText { anchors.horizontalCenter: parent.horizontalCenter; y: 20;
        text: parent.title; color: "white"; font.pixelSize: 22 }
    Rectangle { x: 36; y: 88; width: 728; height: 44; visible: parent.compact; color: "#24547b"
        UbuntuLightText { x: 12; anchors.verticalCenter: parent.verticalCenter;
            text: "Notification (1)"; color: "white"; font.pixelSize: 18 } }
    C300XEnergy { objectName: "energy"; x: 36; y: parent.compact ? 147 : 94;
        width: 728; height: parent.energyHeight }
    Rectangle { x: 36; y: 425; width: 90; height: 36; color: "#24547b"
        UbuntuLightText { anchors.centerIn: parent; text: "<"; color: "white"; font.pixelSize: 20 } }
    UbuntuLightText { x: 360; y: 433; text: "2 / 3"; color: "white"; font.pixelSize: 18 }
    Rectangle { x: 674; y: 425; width: 90; height: 36; color: "#24547b"
        UbuntuLightText { anchors.centerIn: parent; text: ">"; color: "white"; font.pixelSize: 20 } }
}
''')
            window = QQuickView()
            enum_values = window.engine().evaluate(
                "(function(item) { return {align: +item.horizontalAlignment, "
                "valign: +item.verticalAlignment, elide: +item.elide, wrap: +item.wrapMode}; })")
            window.setSource(QUrl.fromLocalFile(str(directory / "Frame.qml")))
            if window.status() == QQuickView.Error:
                raise RuntimeError("\n".join(error.toString() for error in window.errors()))
            frame = window.rootObject()
            component = frame.findChild(type(frame), "energy")
            if component is None:
                from PySide6.QtQuick import QQuickItem
                component = frame.findChild(QQuickItem, "energy")
            assert component is not None
            window.show()
            for fixture in fixtures:
                if fixture["language"] not in args.languages or fixture["name"] not in args.scenarios:
                    continue
                available = fixture["energy"].get("views", [])
                for view in available:
                    if args.views and view["id"] not in args.views:
                        continue
                    for height in args.heights:
                        for tabs in args.tabs:
                            start_messages = len(messages)
                            payload = copy.deepcopy(fixture["energy"])
                            if tabs == "single":
                                payload["views"] = [view]
                            frame.setProperty("title", fixture.get("title", "Energy"))
                            frame.setProperty("compact", height < 280)
                            frame.setProperty("energyHeight", height)
                            component.setProperty("energy", payload)
                            component.setProperty("view", "__not_selected__")
                            settle()
                            expected_first = payload["views"][0]["id"]
                            if component.property("shown") != expected_first:
                                raise AssertionError("Disabled view did not fall back to the first selected view")
                            tab_height = component.property("tabHeight")
                            if (tabs == "single") != (tab_height == 0) and len(available) > 1:
                                raise AssertionError("Single/multiple-view tab visibility is incorrect")
                            if tab_height > 0:
                                index = next(i for i, entry in enumerate(payload["views"]) if entry["id"] == view["id"])
                                point = component.mapToItem(frame, QPointF(
                                    (index + 0.5) * component.width() / len(payload["views"]), height - tab_height / 2))
                                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
                            else:
                                component.setProperty("view", view["id"])
                            settle()
                            if component.property("shown") != view["id"]:
                                raise AssertionError(f'Tab did not select {view["id"]}')
                            inspection = None
                            if args.inspect is not None and view["id"] in ("today", "power"):
                                from PySide6.QtQuick import QQuickItem
                                is_power = view["id"] == "power"
                                tap = component.findChild(QQuickItem, "energyPowerTap" if is_power else "energyHoursTap")
                                count = component.property("powerBuckets") if is_power else 24
                                selected = "selectedPower" if is_power else "selectedHour"
                                index = min(args.inspect, count - 1)
                                assert tap is not None and tap.isEnabled() and index >= 0
                                point = tap.mapToItem(frame, QPointF((index + 0.5) * tap.width() / count, tap.height() / 2))
                                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
                                settle()
                                assert component.property(selected) == index
                                component.setProperty("energy", copy.deepcopy(payload))
                                settle()
                                assert component.property(selected) == index
                                inspection = {"index": index, "same_payload_preserved": True}
                            shot = window.grabWindow()
                            if shot.isNull() or shot.size().width() != 800 or shot.size().height() != 480:
                                raise RuntimeError("Offscreen framebuffer is missing or not 800x480")
                            texts = text_bounds(component)
                            issues = layout_issues(texts, [0, 0, 728, height])
                            power_checks = {}
                            if view["id"] == "power":
                                power_issues, power_checks = power_pixels(component, frame, shot, fixture)
                                issues.extend(power_issues)
                            body_texts = [item for item in texts if item["ink"][1] < height - tab_height - 8]
                            if not body_texts:
                                issues.append({"kind": "blank_view"})
                            offset = component.mapToItem(frame, QPointF(0, 0))
                            pixels = {shot.pixelColor(x, y).rgba()
                                      for x in range(int(offset.x()), int(offset.x()) + 728, 4)
                                      for y in range(int(offset.y()), int(offset.y()) + height, 4)}
                            if len(pixels) < 3:
                                issues.append({"kind": "blank_pixels"})
                            name = f'{fixture["language"]}-{fixture["name"]}-{view["id"]}-{height}-{tabs}'
                            name = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
                            output = args.output / (name + ".png")
                            shot.save(str(output))
                            overlay = shot.copy()
                            painter = QPainter(overlay)
                            painter.setPen(QPen(QColor("#ff5263"), 1))
                            for item in texts:
                                x, y, width, ink_height = item["ink"]
                                painter.drawRect(QRectF(x + offset.x(), y + offset.y(), width, ink_height))
                            painter.end()
                            overlay.save(str(args.output / (name + ".bounds.png")))
                            report["cases"].append({"name": name, "height": height, "view": view["id"],
                                                    "tabs": tabs, "texts": texts, "issues": issues,
                                                    "sampled_colors": len(pixels),
                                                    "body_texts": len(body_texts),
                                                    "power_pixels": power_checks,
                                                    "inspection": inspection,
                                                    "warnings": messages[start_messages:],
                                                    "screenshot": str(output)})
                            sys.stdout.write(f"{name}: {len(texts)} texts, {len(issues)} issues\n")
                            sys.stdout.flush()
                            if inspection is not None:
                                dismiss = next(item for item in component.findChildren(QQuickItem, "energyDismiss") if item.isVisible())
                                point = dismiss.mapToItem(frame, QPointF(dismiss.width() / 2, dismiss.height() / 2))
                                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(point.x()), round(point.y())))
                                settle()
                                assert component.property(selected) == -1
                                inspection["dismissed"] = True
                                component.setProperty(selected, index)
                                component.setProperty("visible", False)
                                settle()
                                assert component.property(selected) == -1
                                component.setProperty("visible", True)
                                if is_power:
                                    component.setProperty(selected, index)
                                    changed = copy.deepcopy(payload)
                                    changed["power"]["revision"] += "-inspection-refresh"
                                    component.setProperty("energy", changed)
                                    settle()
                                    assert component.property(selected) == -1
                                if len(payload["views"]) > 1:
                                    component.setProperty(selected, index)
                                    other = next(item["id"] for item in payload["views"] if item["id"] != view["id"])
                                    component.setProperty("view", other)
                                    settle()
                                    assert component.property(selected) == -1
            window.close()
            window.setSource(QUrl())
            app.processEvents()
    finally:
        qInstallMessageHandler(previous_handler)
    report["messages"] = messages
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qml", type=Path, default=ROOT / "device_qml/C300XEnergy.qml")
    parser.add_argument("--revision", help="Read baseline QML with local git show, without changing the checkout")
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/energy")
    parser.add_argument("--fixture-python", default=sys.executable, help="Existing HA Python for pure backend fixtures")
    parser.add_argument("--fixtures", type=Path, help="External JSON fixtures, bypass backend imports")
    parser.add_argument("--emit-fixtures", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--consumers-fixtures", action="store_true", help="Include live consumer data from the production formatter")
    parser.add_argument("--stock-skin", type=Path, help="Optional read-only firmware skin directory")
    parser.add_argument("--languages", nargs="+", default=list(LANGUAGES))
    parser.add_argument("--views", nargs="+")
    parser.add_argument("--inspect", type=int, help="Tap a chart bucket and verify local selection and dismissal")
    parser.add_argument("--scenarios", nargs="+", default=["normal", "stress"])
    parser.add_argument("--heights", nargs="+", type=int, default=[300, 230])
    parser.add_argument("--tabs", nargs="+", choices=["single", "multi"], default=["single", "multi"])
    parser.add_argument("--check", action="store_true", help="Fail for layout issues (baseline capture still writes artifacts)")
    args = parser.parse_args()
    if args.emit_fixtures:
        sys.stdout.write(json.dumps(make_fixtures(args.consumers_fixtures), ensure_ascii=True) + "\n")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    if args.fixtures:
        fixtures = json.loads(args.fixtures.read_text())
    else:
        result = subprocess.run([args.fixture_python, str(Path(__file__).resolve()), "--emit-fixtures",
                                 *(["--consumers-fixtures"] if args.consumers_fixtures else [])],
                                capture_output=True, text=True, timeout=60, check=True)
        fixtures = json.loads(result.stdout)
    report = render(args, fixtures)
    if not report["cases"]:
        raise ValueError("No fixture cases matched the filters")
    (args.output / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=True, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    failures = sum(bool(case["issues"]) for case in report["cases"])
    sys.stdout.write(f'{len(report["cases"])} cases; {failures} with geometry issues; {args.output / "report.json"}\n')
    return int(args.check and failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
