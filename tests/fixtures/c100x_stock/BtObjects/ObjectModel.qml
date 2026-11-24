import QtQuick 2.7
QtObject {
    id: model
    property var filters: []
    property int count: 0
    property QtObject binder: QtObject {
        function getObject(index) { return global.stubObject(model.filters) }
    }
    function getObject(index) { return null }
    function remove(object) {}
}
