# Device QML UI

This directory contains native Qt/QML pages for the C300X display.

It intentionally does not embed Lovelace. The C300X GUI runs QtQuick/QML and can use local HTTP, so the device UI talks to the optional local display bridge at `http://127.0.0.1:8090`.

## Files

- `Alarm.qml`: blue native Alarmo subpage with conditional PIN input, confirmed
  state/readiness feedback, guarded arm/disarm commands and an optional selected
  HA quick entity. No selection means no additional action button.
- `HomeAssistant.qml`: native dynamic Home Assistant board page backed by the
  local display bridge. Includes capability-based light, cover, climate, fan
  and media player controls, read-only sensor details, dashboard pages, badges,
  flow items, images, switches and buttons without a refresh timer. See
  [Display Device Controls](../docs/feature-reference.md#display-device-controls).
- `C300XRingerControl.qml`: core, page-independent ringer command receiver.
  Uses the same `AudioState` enable/disable calls as the stock mute button.
  One loopback HTTP request waits for work without periodic polling; a timer
  reconnects only after a connection/protocol failure. Commands and replies
  stay in RAM, with no runtime file writes. Installed and removed with the
  core `EventManager.qml` patch.
- `js/c300x_ha.js`: local HTTP helper used by the QML page.
- `js/c300x_memos.js`: loopback-only local memo/message metadata helper used by patched device memo pages.
- The stock `HomePage.qml` and `MemoPage.qml` are not stored in this
  repository. The native agent patch script transforms the original files
  already present on the device and keeps a one-time original backup there.

## Packaging

These sources are not written to the device as they stand. Packaging
(`scripts/stage_device_agent_bundle.py`) and the development installer
(`scripts/install_c300x_device.sh`) pass every `.qml` and `.js` file through
`scripts/device_file_strip.py`, which drops comment-only lines, blank lines and
indentation. That makes the installed display files about 30 % smaller, so
comments here cost nothing on the device.

The strip is line based on purpose. Keep it valid: no `/* */` block comments
and no string literal continued over a line break with a backslash; packaging
fails on either. A `//` comment after code on the same line is kept as is, so
put comments on their own line. Line numbers in a device log refer to the
stripped file; `scripts/device_file_strip.py --out <dir>` writes the same files
locally for comparison.

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

## Related Documentation

- [Architecture](../docs/architecture.md)
- [Native agent runtime notes](../docs/native-agent.md)
- [Native Agent API Contract](../native_agent/API.md#loopback-ui-api)
