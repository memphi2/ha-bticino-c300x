import QtQuick 2.7
import "js/c100x_memos.js" as Memos
import "js/c100x_text.js" as Labels

C100XPage {
    id: page
    headerLabel: label("memos")
    readonly property bool blocked: c100xHost.blocked
    property var reader: null
    property var entries: []
    property var selectedMemo: null
    property bool busy: false
    property bool failed: false
    property bool available: false
    property alias deadline: timeout
    function label(key) { return Labels.label(c100xHost.language, key) }
    function aboutToShow() {
        if (!reader) reader = Memos.create(page)
        reader.load()
    }
    function aboutToHide() {
        if (reader) reader.stop()
        selectedMemo = null
        entries = []
    }
    onBackClicked: {
        resetInput()
        if (selectedMemo) selectedMemo = null
        else back()
    }
    Timer { id: timeout; interval: 8000; onTriggered: if (page.reader) page.reader.timeout() }
    Component.onDestruction: if (reader) reader.destroy()
    C100XAction {
        x: parent.width - 180; y: 4; width: 168; height: 46
        enabled: !page.busy
        onClicked: page.reader.load()
        C100XText {
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
            text: page.label("refresh"); color: "white"; font.pixelSize: 20
        }
    }
    C100XText {
        x: 24; y: 90; width: parent.width - 48; height: 80
        visible: !page.selectedMemo && (page.busy || page.failed || !page.available || !page.entries.length)
        text: page.busy ? page.label("loading") : page.failed ? page.label("loadFailed")
              : !page.available ? page.label("unavailable") : page.label("noMemos")
        wrapMode: Text.Wrap; color: "white"; font.pixelSize: 22
    }
    C100XScroll {
        x: 24; y: 70; width: parent.width - 48; height: parent.height - 86
        visible: !page.selectedMemo && !page.busy && !page.failed && page.available
        clip: true; contentWidth: width; contentHeight: rows.height
        Column {
            id: rows
            width: parent.width; spacing: 10
            Repeater {
                model: page.entries
                Rectangle {
                    width: rows.width; height: 100; color: "#244a59"
                    C100XText {
                        x: 12; y: 8; width: parent.width - 24; height: 25
                        text: modelData.date; color: modelData.unread ? "#ffcf66" : "#bdd5df"; font.pixelSize: 18
                        elide: Text.ElideRight
                    }
                    C100XText {
                        x: 12; y: 38; width: parent.width - 24; height: 54
                        text: modelData.text; color: "white"; font.pixelSize: 20
                        wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                    }
                    C100XAction {
                        anchors.fill: parent
                        onClicked: { page.resetInput(); page.selectedMemo = modelData; detail.contentY = 0 }
                    }
                }
            }
        }
    }
    C100XText {
        x: 24; y: 70; width: parent.width - 48; height: 30
        visible: !!page.selectedMemo
        text: page.selectedMemo ? page.selectedMemo.date + (page.selectedMemo.truncated ? " - " + page.label("truncated") : "") : ""
        color: "#bdd5df"; font.pixelSize: 18; elide: Text.ElideRight
    }
    C100XScroll {
        id: detail
        objectName: "memoDetail"
        x: 24; y: 112; width: parent.width - 48; height: parent.height - 128
        visible: !!page.selectedMemo; clip: true; contentWidth: width; contentHeight: body.height
        C100XText {
            id: body
            width: detail.width - 12; height: paintedHeight
            text: page.selectedMemo ? page.selectedMemo.text : ""
            color: "white"; font.pixelSize: 22; wrapMode: Text.Wrap
        }
    }
}
