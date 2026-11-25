import QtQuick 2.7
QtObject {
    id: model
    property var filters: []
    // main.qml empties its own camera list five seconds after the start; the menu keeps its own.
    property bool cleared: false
    property int count: cleared ? 0 : global.stubCount(filters)
    property QtObject binder: QtObject {
        function getObject(index) { return global.stubObject(model.filters) }
    }
    function getObject(index) { return null }
    function remove(object) { cleared = true }
}
