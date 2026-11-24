import QtQuick 1.1
import "../../device_qml/js/c300x_memos.js" as MemoSync

Item {
    Component.onCompleted: {
        var objects = [{messageId: 1, type: 2}, {messageId: 3, type: 1}]
        var removed = []
        var model = {
            count: 2,
            binder: {getObject: function(index) { return objects[index] }},
            remove: function(object) { removed.push(object.messageId); model.count-- }
        }
        MemoSync.syncObjectModel(model, {ok: true, available: false, memos: []}, 2)
        MemoSync.syncObjectModel(model, {ok: true, available: true, memos: []}, 2)
        if (removed.length !== 0)
            throw new Error("removed without a deletion list: " + removed)
        MemoSync.syncObjectModel(model, JSON.parse('{"ok":true,"available":true,"memos":[{"id":"text/memo_1"}],"deleted":["voice/memo_3","text/memo_1"]}'), 2)
        if (removed.join(",") !== "3")
            throw new Error("wrong removal: " + removed)
        console.log("QT4_MEMO_SYNC_PASS")
    }
}
