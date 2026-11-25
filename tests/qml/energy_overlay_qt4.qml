import QtQuick 1.1

Item {
    id: host
    width: 748; height: 300
    Item {
        id: page
        anchors.fill: parent
        Loader { id: loader; anchors.fill: parent; source: "C300XEnergyConsumers.qml" }
    }
    function payload(factor) {
        var items = []
        for (var i = 0; i < 7; i++)
            items.push({entity_id: "sensor.c" + i, label: "C" + i, watts: (i + 1) * 1000 * factor, value: "x", color: "#ff0000"})
        return {items: items, status: "s" + factor}
    }
    function rowItems(item) {
        var count = item.objectName === "consumerRow" ? 1 : 0
        for (var i = 0; i < item.children.length; i++) count += rowItems(item.children[i])
        return count
    }
    Component.onCompleted: {
        var checks = 0, view = loader.item
        function check(condition, label) {
            if (!condition) throw new Error("consumers under an overlay: " + label)
            checks++
        }
        view.consumers = payload(1)
        check(view.rows.length === 7 && rowItems(view) === 7, "rows shown")
        check(view.rows[0].watts === 7000 && view.statusText === "s1", "first data")
        var high = view.leftScale.high
        page.visible = false
        check(view.visible === false, "a hidden page hides the view")
        view.consumers = payload(0.001)
        check(view.rows[0].watts === 7000 && view.statusText === "s1", "refresh held back while hidden")
        view.consumers = payload(0.002)
        check(view.rows[0].watts === 7000, "second refresh held back")
        page.visible = true
        check(view.rows[0].watts === 14 && view.statusText === "s0.002", "newest data when shown")
        check(view.leftScale.high === high && view.leftScale.deadline > 0, "scale kept, shrink planned")
        view.consumers = payload(0.002)
        check(view.rows[0].watts === 14, "visible refresh applies at once")
        console.log("C300X_OVERLAY_QT4_PASS " + checks)
    }
}
