import QtQuick 2.7
QtObject {
    id: g
    property bool beepEnabled: true
    property bool blockKeyboard: false
    property int commissioningStatus: 3
    property bool secureLock: false
    property bool bufferingStatus: false
    property string fwVersion: "1.5.8"
    property string myAddress: "1"
    property var mNetatmoCamera: null
    property var switches: []
    property int defaultEp: 0
    signal deviceIdentityReceivedSig()
    property QtObject networkInfo: QtObject {
        property bool connected: true
        property bool enabled: true
        property bool commissioned: true
        property bool isSoftAp: false
        property int strength: 70
        property string networkName: "HomeWiFi"
        property string ipAddress: "192.0.2.50"
        property string netMask: "255.255.255.0"
        property string gateway: "192.0.2.1"
        property string macAddress: "00:03:50:00:00:01"
    }
    property QtObject screenState: QtObject {
        property int state: 2
        property int screensaverInterval: 60
        signal stateChangedInt(int value)
        function enableState(value) { state = value }
        function disableState(value) {}
        function simulateClick() {}
    }
    property QtObject audioState: QtObject {
        property bool isRingtoneMute: false
        property int ringVolume: 60
        signal volumeChanged(int state, int volume)
        function getVolume(kind) { return ringVolume }
        function setVolume(kind, value) {}
        function isStateEnabled(value) { return value === 1 ? isRingtoneMute : false }
        function enableState(value) { if (value === 1) isRingtoneMute = true }
        function disableState(value) { if (value === 1) isRingtoneMute = false }
    }
    property QtObject ringtoneManager: QtObject {
        property var ringtoneList: []
        function stopRingtone() {}
        function playVolumePreview(kind) {}
        function playRingtone(a, b) {}
        function ringtoneFromType(kind) { return 0 }
        function setRingtoneForType(kind, value) {}
    }
    property QtObject configuration: QtObject {
        property bool isAutoOpenAllowed: false
        property bool isPagerAllowed: false
        property var items: []
    }
    property QtObject cctv: QtObject {
        property bool callInProgress: false
        property bool callActive: false
        property bool isIpCall: false
        property bool autoOpen: false
        property int callType: 1
        property int volume: 60
        property int contrast: 50
        property int brightness: 50
        property int color: 50
        property string talker: ""
        signal incomingCall()
        signal callAnswered()
        signal closeChannel()
        signal callEnded()
        function endCall() {}
        function answerCall() {}
    }
    property QtObject intercom: QtObject {
        property bool callInProgress: false
        property bool callActive: false
        property bool scsIntercomCall: false
        property bool sipIntercomCall: false
        property int volume: 60
        signal incomingCall()
        signal callAnswered()
        signal callEnded()
    }
    property int netatmoCount: 0
    function stubCount(filters) {
        var first = filters && filters.length ? filters[0] : filters
        return first && first.objectId === 3 ? netatmoCount : 0
    }
    function stubObject(filters) {
        var first = filters && filters.length ? filters[0] : filters
        var id = first ? first.objectId : -1
        return id === 1 ? cctv : id === 2 ? intercom : null
    }
    function blockKeyboardWithDuration(ms) {}
    function networkStatus() {}
    function deviceIdentity() {}
    function netatmoCameras() {}
    function turnOffScreen() {}
    function blinkLedOnce(which) {}
    function blinkLed(which) {}
    function setWifi(on) {}
    function setSoftAp(on) {}
    function qrCodeExit() {}
    function getQrCode(a) {}
    function getDns() { return "" }
    function networkReset() {}
    function deviceReset() {}
    function startCommissioning() {}
    function setDoNothing() {}
    function floorCall() {}
    function answerPress() {}
    function answerRelease() {}
}
