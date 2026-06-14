# Device QML UI

This directory contains native Qt/QML pages for the C300X display.

It intentionally does not embed Lovelace. The C300X GUI runs QtQuick/QML and can use local HTTP, so the device UI talks to the optional local display bridge at `http://127.0.0.1:8090`.

## Files

- `Alarm.qml`: native page with alarm state, PIN input, and arm/disarm buttons.
- `HomeAssistant.qml`: native dynamic Home Assistant board page backed by the local display bridge. It renders dashboard pages, badges, flow items, images, switches, and buttons without a refresh timer.
- `js/c300x_ha.js`: local HTTP helper used by the QML page.
- `js/c300x_memos.js`: loopback-only local memo/message metadata helper used by patched device memo pages.
- The stock `HomePage.qml` and `MemoPage.qml` are not stored in this
  repository. The native agent patch script transforms the original files
  already present on the device and keeps a one-time original backup there.

## Safety

- Apply the device UI only through the native agent QML maintenance API. It
  installs generated project QML files, transforms original device pages, and
  backs up original device files first.
- Store device file backups under
  `/home/bticino/cfg/extra/c300x-device-file-backups/original/`, mirroring the
  original GUI path.
- Do not create on-device backups of generated project code such as the agent,
  display bridge, or their configs.
- Restarting the GUI is required after a patch, but this repository does not run any device commands.
- PINs are sent only to the local loopback agent API and must never be logged.
