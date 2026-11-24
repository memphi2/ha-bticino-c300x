import QtQuick 1.1
import "../../device_qml/js/c300x_ha.js" as Api
import "../../device_qml/js/c300x_memos.js" as MemoSync

Item {
    Component.onCompleted: {
        if (Api.baseUrl() !== "http://127.0.0.1:8090")
            throw new Error("default")
        Api.useBaseUrl("http://127.0.0.1:18123")
        Api.useBaseUrl("http://192.0.2.10:80")
        MemoSync.useBaseUrl("http://127.0.0.1:18124")
        if (Api.baseUrl() !== "http://127.0.0.1:18123" || MemoSync.BASE_URL !== "http://127.0.0.1:18124")
            throw new Error("base url: " + Api.baseUrl() + " " + MemoSync.BASE_URL)
        console.log("QT4_UI_PORT_PASS")
    }
}
