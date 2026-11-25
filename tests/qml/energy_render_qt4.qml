import QtQuick 1.1

Rectangle {
    id: host
    width: 800; height: 480
    color: "#203070"
    property int checks: 0
    property variant views: [{id: "now", label: "Now"}, {id: "today", label: "Today"}, {id: "power", label: "Power"}, {id: "balance", label: "Balance"}]
    function hourValues(scale) {
        var values = []
        for (var i = 0; i < 24; i++) values.push(i > 7 && i < 17 ? scale * (i % 5) / 4 : 0)
        return values
    }
    function powerValues(scale) {
        var values = []
        for (var i = 0; i < 96; i++) values.push(i < 50 ? scale * (i % 7) / 6 : null)
        return values
    }
    function energy(solar, grid, battery) {
        function node(label, color, power, flow) { return {label: label, color: color, lines: ["1.26 kWh", "-0.19 kWh"], power: power, flow: flow} }
        var axis = {min: -1, max: 2, unit: "kWh", decimal_separator: ".", ticks: [
            {value: -1, label: "-1", position: 0}, {value: 0, label: "0", position: 1 / 3},
            {value: 1, label: "1", position: 2 / 3}, {value: 2, label: "2", position: 1}]}
        return {
            views: views,
            nodes: {solar: node("Solar", "#ffe066", "520 W", solar), grid: node("Grid", "#75bfff", "75 W", grid),
                    battery: node("Battery", "#69f0ae", "71 W", battery), home: node("Home", "#ff9a8b", "374 W", 1)},
            hours: {max: 1.5, label: "1.5 kWh", axis: axis, series: [
                {color: "#75bfff", values: hourValues(0.6)}, {color: "#ffe066", values: hourValues(0.8)}]},
            sums: [{label: "Solar", value: "1.26 kWh", color: "#ffe066"}, {label: "Grid", value: "35.1 kWh", color: "#75bfff", cost: "9.80 EUR"}],
            balance: {rows: [{label: "Solar used at home", value: "85 %", ratio: 0.85, color: "#ffe066"},
                             {label: "Self-sufficiency", value: "4 %", ratio: 0.04, color: "#69f0ae"}],
                      values: [{label: "Net from grid", value: "34.9 kWh"}, {label: "Cost today", value: "9.80 EUR"}]}
        }
    }
    property variant history: ({
        axis: {min: -2, max: 6, unit: "kW", decimal_separator: ".", ticks: [
            {value: -2, label: "-2", position: 0}, {value: 0, label: "0", position: 0.25},
            {value: 2, label: "2", position: 0.5}, {value: 4, label: "4", position: 0.75}, {value: 6, label: "6", position: 1}]},
        note: "15 min averages",
        series: [{label: "Grid", color: "#75bfff", values: powerValues(0.5), dots: []},
                 {label: "Home", color: "#ff9a8b", values: powerValues(0.7), dots: []}]})

    Loader { id: first; x: 26; y: 96; width: 748; height: 318 }
    Loader { id: second; x: 26; y: 96; width: 748; height: 318; visible: false; source: "C300XEnergy.qml" }

    function all(item, test, out) {
        if (!item) return out
        if (test(item)) out.push(item)
        var kids = item.children
        for (var i = 0; kids && i < kids.length; i++) all(kids[i], test, out)
        return out
    }
    function check(condition, label) {
        if (condition) checks++
        else console.log("C300X_ENERGY_QT4_FAIL " + label)
    }
    function lane(item) {
        while (item && item.laneWidth === undefined) item = item.parent
        return item
    }
    function arrows(view, expected, label) {
        var found = all(view, function(i) { return i.text === "▶" && i.visible === true }, [])
        check(found.length === expected, label + ": " + found.length + " arrows, expected " + expected)
        for (var i = 0; i < found.length; i++) {
            var line = lane(found[i])
            var at = found[i].mapToItem(host, found[i].width / 2, found[i].height / 2)
            var want = line.mapToItem(host, line.width / 2, line.height / 2)
            check(Math.abs(at.x - want.x) <= 1 && Math.abs(at.y - want.y) <= 1,
                  label + ": arrow " + i + " at " + at.x + "," + at.y + ", its line at " + want.x + "," + want.y)
        }
    }
    function hourLabels(view) {
        var tap = all(view, function(i) { return i.objectName === "energyHoursTap" }, [])[0]
        var bars = tap.parent
        var bottom = bars.mapToItem(host, 0, bars.height).y
        var found = all(view, function(i) { return /^\d\d:00$/.test("" + i.text) && i.visible === true }, [])
        check(found.length === 5, "today: " + found.length + " hour labels, expected 5")
        for (var i = 0; i < found.length; i++) {
            var top = found[i].mapToItem(host, 0, 0).y
            check(top >= bottom && top <= bottom + 4, "today: label " + found[i].text + " at " + top + ", bars end at " + bottom)
        }
    }
    Component.onCompleted: {
        first.source = "C300XEnergy.qml"
        first.item.energy = energy(1, -1, -1)
        first.item.powerHistory = history
        second.item.powerHistory = history
    }
    Timer {
        property int step: 0
        interval: 250; repeat: true; running: true
        onTriggered: {
            step++
            if (step === 1) {
                arrows(first.item, 4, "now, set after creation")
                first.item.energy = energy(-1, 1, 1)
            } else if (step === 2) {
                arrows(first.item, 4, "now, every flow turned")
                first.item.energy = energy(1, -1, 0)
                second.item.energy = energy(1, -1, -1)
                first.visible = false
                second.visible = true
            } else if (step === 3) {
                arrows(second.item, 4, "now, second view")
                second.visible = false
                first.visible = true
                arrows(first.item, 3, "now, battery idle")
                first.item.view = "today"
            } else if (step === 4) {
                hourLabels(first.item)
                first.item.view = "power"
            } else if (step === 5) {
                check(first.item.shown === "power", "power view shown")
                first.item.view = "balance"
            } else if (step === 6) {
                check(first.item.shown === "balance", "balance view shown")
                first.item.view = "@VIEW@"
                console.log("C300X_ENERGY_QT4_PASS " + checks)
                running = false
            }
        }
    }
}
