import QtQuick 1.1
import Components 1.0
import Components.Styles 1.0

Item {
    id: root
    property variant agenda: ({})
    property variant events: agenda && agenda.events ? agenda.events : []
    property string errorText: agenda && agenda.error ? agenda.error : ""
    clip: true

    UbuntuLightText {
        id: errorLabel
        width: parent.width
        height: root.errorText ? 28 : 0
        text: root.errorText
        color: "#ffd166"
        font.pixelSize: 17
        elide: Text.ElideRight
    }

    ListView {
        anchors.top: errorLabel.bottom
        anchors.bottom: parent.bottom
        width: parent.width
        clip: true
        interactive: contentHeight > height
        model: root.events
        boundsBehavior: Flickable.StopAtBounds
        delegate: Item {
            width: ListView.view.width
            height: 70
            UbuntuLightText {
                x: 0; y: 3
                width: parent.width
                height: 28
                text: modelData.summary
                textFormat: Text.PlainText
                color: "white"
                font.pixelSize: 21
                elide: Text.ElideRight
            }
            UbuntuLightText {
                x: 0; y: 33
                width: parent.width
                height: 24
                text: modelData.when + "  |  " + modelData.calendar
                textFormat: Text.PlainText
                color: "#c7d0d9"
                font.pixelSize: 17
                elide: Text.ElideRight
            }
            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: "#c7d0d9"
                opacity: 0.25
            }
        }
    }
    UbuntuLightText {
        anchors.fill: parent
        anchors.topMargin: errorLabel.height
        visible: root.events.length === 0 && !root.errorText
        text: root.agenda && root.agenda.empty_text ? root.agenda.empty_text : ""
        color: "white"
        font.pixelSize: 21
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
