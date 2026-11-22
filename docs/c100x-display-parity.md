# C100X Display Parity

Scope: **all** additional native C300X pages, not a reduced dashboard. The
original C100X 1.5.8 `main.qml` specifies 800x480, QtQuick 2.7 and Controls 2.0.
Its wrapper selects EGLFS/fb1 and event0/event1. This is not a touchscreen
contract. No device/HA access is authorized by this offline work.

## Page and Input Matrix

| Existing source | Required C100X parity | Physical input |
| --- | --- | --- |
| `HomeAssistant.qml` | Status, badges, weather/forecast, images, configured pages and navigation | Up/Down focus and scroll, Return activate, explicit Back |
| `C300XDetailControl.qml` | All supplied light, cover, climate, fan, media, sensor and other entity controls | Discrete actions, choices and numeric adjustment; no drag-only controls |
| `C300XPageNavigation.qml` | Same page enable/order, favourites and More | Every enabled page reachable |
| `C300XEnergy.qml` | Now, Today, Power, Consumers, Balance; only enabled views | Tabs and exact supplied history buckets selectable with keys |
| `C300XEnergyConsumers.qml` | All configured consumer readings, independent column scaling | Read-only, no new polling |
| `C300XEnergyReadout.qml`, `C300XEnergySums.qml` | Exact selected interval and sums, dismissal | Return/dismiss and back |
| `Alarm.qml` | Blue Alarmo page, conditional PIN, modes, readiness, blockers, bypass, configured quick action | Full keypad and actions reachable; PIN cleared on exit/preemption |
| `C300XAgenda.qml` | All supplied events and error/empty states | Scroll every event |
| `C300XLeaveHome.qml` | Contacts, lights, Alarmo link and allowlisted actions with confirmation | Confirm/cancel within existing deadline |
| `C300XSituations.qml`, `C300XChecks.qml` | Configured situations, contacts, tasks and states | Scroll all rows |
| `C300XAlerts.qml` | Notify display, bounded wake/sound, acknowledge | Call/protected-page preemption, no deferred effects |
| `C300XRingerControl.qml` | Confirmed mute/unmute through stock AudioState | Core hook independent of dashboard visibility |
| Patched General settings | Vendor beep setting plus HA feedback preference | Keep stock InstallerPage beep control; additional settings keyed |
| Patched MemoPage and `c300x_memos.js` | Separate text-memo list/detail, bounded refresh and scroll implemented offline | C100X has no stock MemoPage; text display is read-only. Recording, playback, edit/delete/read-state mutation remain unverified and are not exposed |

Shared JS retains the existing HA snapshot, allowlisted command, confirmation,
timeout and sleeping-event-request contracts. No display refresh polling is
introduced. TTS remains separate and unavailable without a verified path.

## Original Firmware Anchors

| File | SHA256 |
| --- | --- |
| `main.qml` | `ff1740e9742951f5cda2225d605eae06141f43ee26d900ca21d7fdf14960e6fb` |
| `MainPage.qml` | `ba3edae9b9e670dad86894f93747f510f07c2389f498697e5d20dd95b4cb8e80` |
| `EventManager.qml` | `3ca4b5e8c27c8c8b283d533106091072e25632bb090d414ee4c1d93f3a06b181` |
| `BtClass100_qws` | `ad6d23db69795afb712751b3d92afbca3356d524b40bdb441de096b3d12c3612` |

`MainPage.qml` handles Up/Down/Return. `EventManager.qml` owns Call/Hangup
and keys 1-8, including door and stair actions. Those handlers must remain
unchanged. The adapter must yield to calls, commissioning and vendor pages.
`Components/RingtoneItem.qml` uses `AudioState.RingtoneMute`,
`isRingtoneMute` and `getVolume/setVolume`; `InstallerPage.qml` uses
`global.beepEnabled`. The original supervisor config names `BtClass100_qws`.
Never replace its framebuffer, input configuration or watchdog with guesses.

## Acceptance Boundaries

Implemented locally: separate QtQuick 2.7 conversion of 14 page/display
modules, C100X-owned frame/text/switch/skin components, physical-key focus,
scroll reveal, numeric edit/confirm/cancel and history-bucket selection. The
shared HA JS and original Qt4 pages are unchanged. Focused host Qt5 tests load
every converted module and exercise offscreen actions and edit cancellation.
The generated entity slider is also tested with the real page helpers: edit
starts at the current value, one key advances one configured step, fractional
and unaligned bounds are respected, and cancellation submits no command.
The separate loader now connects Dashboard, Alarmo and settings to this lifecycle.
The C100X core bridge uses the original mute and beep properties, sleeping
requests and actual state readback. It cancels requests and unloads the page on
call, active call, Soft-AP, commissioning or keyboard transition blocking.
Offline Qt5 tests check PIN disposal, foreign loader-source rejection and settings;
isolated protocol tests check expiry, replay, late replies and failed readback.
The Qt5 visual/key probe covers 80 component states at 800x480: navigation,
Agenda, Leave Home, entity controls, Situations/Checks and all five Energy views
(four languages, normal/stress data). It checks captured pixels, text bounds,
overlap and Up/Down reachability, with C/H/1-8 forwarded to the parent handler.
Container-fitted consumer-axis labels fix a measured Qt5 font overflow. This
does not yet cover every full Dashboard/Alarmo modal state or physical keys.
The separate `c100x_display.sh` disk transaction now verifies the exact original
GUI binary, wrapper, event manager and both edited QML sources. It stages a
complete hash-manifested adapter directory, installs an inert menu hook first,
and atomically replaces `main.qml` last. Restore reverses that order. Private
staging, an exclusive read-only vendor-inode lock, persistence barriers and
verified original backups protect failure/recovery paths. Unknown changes,
symlinks, hardlinks and foreign firmware fail closed. Original file modes remain
intact. Retired adapter directories and backups are deliberately retained: a
still-running old GUI may reference them. The wrapper/event manager are not
modified and the script does not signal processes or reboot.

Each prepared generation archives its manifest and reviewed hook recipe before
the GUI entry changes. Fixed recipe hashes and regenerated whole-file comparisons
authenticate the installed generation independently of the current package.
Upgrade A-to-B and restoration with missing/corrupt package input are tested;
failed upgrades retain A. Recovery also works when the installed payload is
missing, but never accepts arbitrary target edits or tampered recipe archives.

Focused tests execute this script on original firmware copies, including failed
writes, interrupted main-file switches, corrupt adapter files, symlinks and
remount failure. Hook-fragment Qt5 tests exercise actual Loader initialization,
vendor-stack back navigation and menu availability. These are host tests with
explicit vendor mocks, not proof of the complete firmware GUI process.
The hook probe also executes the original arrival and pop-return animation
branches. The full-screen adapter suppresses the vendor header and page dots
only while its page is active, then restores their previous visibility. Normal
vendor pages and EventManager remain unchanged. Both hook compositions compile
with original Qt 5.10.1; the prior hook recipe remains accepted for verified
upgrade and restoration.

The bundle now carries the adapter as one hashed `qml/c100x_bundle.sh` entry,
with fixed text members extracted into a private temporary directory. File-set
7 installs that entry; actual file-set-6 updater tests verify the two-pass
bootstrap and reject missing/corrupt completion payloads. The measured manifest
is 6,509 bytes (29 entries), below the unchanged old 8,192-byte reader limit;
staging rejects oversized manifests and stale adapter output directories.
Restore does not extract current QML sources. Source delivery does not modify
the vendor GUI, start a loader or change display capabilities.
Agent removal now verifies exact stock display files, or runs this payload's
verified restore and checks the resulting original hashes before deleting the
agent/backups. Missing recovery code, unknown edits, damaged backups and a
false-success response abort removal without reboot. Already-stock 1.5.8 can
be removed without a payload. Retired generation directories remain on disk
because a running GUI may still reference them; removal does not signal it.

The Notify overlay now has a separate Qt5/key adapter using the unchanged shared
expiry/acknowledgement controller. Original `libbtobjects.so` exports the
ScreenState simulateClick/disableState/stateChangedInt API; runtime shape checks
guard access. Up/Down scroll, Return/Back acknowledge, and C/H/1-8 propagate to
EventManager. Focus returns after dismissal, but never overrides call focus.
Host Qt5 tests cover wake ownership/expiry, user interaction, call preemption,
failed acknowledgement/retry, real intercepted XHR and a nonblank screenshot.
All requests stay in a memory-only transport. Sound-bearing commands are
rejected: the stock queued beep lacks a verified call-safe cancellation contract.
This proves neither device wake behavior nor enabled Notify delivery.

This build is not yet an installed or advertised display adapter. Supervised
restart/readiness/automatic rollback remain incomplete.
Notify's silent/wake UI is implemented offline; production activation and sound
remain unavailable. The script reports `runtime_verified: false`;
successful disk installation alone must not enable a capability.

`C100XMemos.qml` now provides a separate read-only text list/detail page through
the existing loopback `/ui/memos` endpoint. It bounds responses/entries, cancels
on call/hide, times out after eight seconds and performs no polling or writes.
The original answering-machine binary names `memos_text`, `message.txt`,
`msg_info.ini`, `Message Information`, `Read`, `Date`, `UnixTime` and `MediaType`;
original `libbtobjects.so` exports AnsweringMachine getMemos/addTextMemo and
voice-record/play methods. These establish static storage/API evidence, not
successful C100X recording/playback or write acknowledgement. Consequently no
voice controls or store mutations are exposed. Host tests cover all 64 text
entries, long plain-text detail scrolling, refresh/error/cancellation, reserved
keys and a rendered screenshot; original Qt compiles the component.

The bridge now holds a generation-bound sleeping connection to the native
C100X-only loopback presence endpoint. It reports the vendor guard, cancels on
guard/generation changes and disconnect, and renews once per minute. The native
side expires stale sockets, rejects duplicates/cross-origin/non-loopback input,
and checks the exact generation requested by an observer. A live blocked GUI
is distinguished from an idle one. This introduces no periodic disk writes.
Presence explicitly reports `installation_verified: false`: it is one input
to a future supervised transaction, not permission to restart or advertise
display capabilities. All three previous reviewed hook recipes remain recoverable.

This matrix is a target, not a declaration that every row works. Capability
flags must stay false until the matching hook, command acknowledgement,
state readback, transactional installation and rollback are implemented and
tested together. Host Qt5 5.15 tests are useful but are not firmware Qt5 5.10.1
or hardware proof. Separately, `tests/test_c100x_firmware_compile.py` compiles
all 28 generated QML files using original ARM Qt 5.10.1 under QEMU (four tests,
including invalid syntax/import/property controls). This is compile-only:
no instances, binding evaluation, vendor/platform plugins or GUI startup.
Vendor imports, restart supervision, wake/sound and memo
runtime behavior require explicit evidence; missing evidence stays documented.
