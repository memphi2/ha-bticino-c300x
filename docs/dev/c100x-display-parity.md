# C100X Display Parity

Scope: **all** additional native C300X pages, not a reduced dashboard. The
original C100X 1.5.8 `main.qml` specifies 800x480, QtQuick 2.7 and Controls 2.0.
Its wrapper selects EGLFS/fb1 and event0/event1. This is not a touchscreen
contract. No device/HA access is authorized by this offline work.

## Page and Input Matrix

| Existing source | Required C100X parity | Physical input |
| --- | --- | --- |
| `HomeAssistant.qml` | Status, badges, weather/forecast, images, configured pages and navigation | Carousel of pages with dots and a last EXIT; Return enters a page, Up/Down move the selection and scroll it into view |
| `C300XDetailControl.qml` | All supplied light, cover, climate, fan, media, sensor and other entity controls | Discrete actions, choices and numeric adjustment; no drag-only controls |
| `C300XPageNavigation.qml` | Same page enable/order, favourites and More | Every enabled page reachable |
| `C300XEnergy.qml` | Now, Today, Power, Consumers, Balance; only enabled views | Tabs and exact supplied history buckets selectable with keys |
| `C300XEnergyConsumers.qml` | All configured consumer readings, independent column scaling | Read-only, no new polling |
| `C300XEnergyReadout.qml`, `C300XEnergySums.qml` | Exact selected interval and sums, dismissal | Return/dismiss |
| `Alarm.qml` | Blue Alarmo page, conditional PIN, modes, readiness, blockers, bypass, configured quick action | Full keypad and actions reachable; PIN cleared on exit/preemption |
| `C300XAgenda.qml` | All supplied events and error/empty states | Scroll every event |
| `C300XLeaveHome.qml` | Contacts, lights, Alarmo link and allowlisted actions with confirmation | Confirm/cancel within existing deadline |
| `C300XSituations.qml`, `C300XChecks.qml` | Configured situations, contacts, tasks and states | Scroll all rows |
| `C300XAlerts.qml` | Notify display, bounded wake/sound, acknowledge | Call/protected-page preemption, no deferred effects |
| `C300XRingerControl.qml` | Confirmed mute/unmute through stock AudioState | Core hook independent of dashboard visibility |
| Patched General settings | Vendor beep setting plus HA feedback preference | Stock beep control untouched; one on/off item **Status messages** in the stock Settings carousel before its EXIT |
| Patched MemoPage and `c300x_memos.js` | None: text memos are not offered on a C100X | No page, no menu entry, no list request; HA creates no memo entities and refuses `write_text_memo` |

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
is about 6.5 KB (29 entries), below the unchanged old 8,192-byte reader limit;
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
guard access. The notice covers the screen; Up/Down scroll, Return acknowledges, and C/H/1-8 propagate to
EventManager. Focus returns after dismissal, but never overrides call focus.
Host Qt5 tests cover wake ownership/expiry, user interaction, call preemption,
failed acknowledgement/retry, real intercepted XHR and a nonblank screenshot.
All requests stay in a memory-only transport. Sound-bearing commands are
rejected: the stock queued beep lacks a verified call-safe cancellation contract.
This proves neither device wake behavior nor enabled Notify delivery.

The display adapter is installed and advertised only through the
[activation by reboot](#activation-by-reboot): the disk trial below switches
the files, the next boot runs them and the agent confirms them in that trial
boot. A supervised GUI restart does not exist and is not needed for it.
Notify's silent/wake alerts follow the confirmed adapter; sound stays
unavailable. Disk apply/restore report `runtime_verified: false`; successful
disk installation alone must not enable a capability, only the trial-boot
confirmation does.

The text memo page (`C100XMemos.qml`) is removed: text memos are not offered on
a C100X. The adapter makes no `/ui/memos` request, the bundle carries no memo
script, Home Assistant creates no memo entities for a C100X and refuses
`write_text_memo` there.

Entry and operation follow the station's own pattern. The menu hook keeps a
mirror list beside the vendor's menu list and never inserts into the vendor
list, so the vendor's fixed-index helpers keep their positions; **Home
Assistant** and **Alarmo** appear after the ringtone item only while the bridge
reports something to open (a failed read hides them and is retried at most six
times with doubling delays, a good read is not repeated). Every page is a
carousel with dots and a last EXIT, because the firmware keymap has no back
key. Our pages draw that chrome themselves in full-screen mode, on the
station's background picture, with a 40 px header icon instead of the stock
80 px header to keep the height for content. Text is at least 18 px except in
the energy charts, whose fixed rows keep their sizes.

The bridge now holds a generation-bound sleeping connection to the native
C100X-only loopback presence endpoint. It reports the vendor guard, cancels on
guard/generation changes and disconnect, and renews once per minute. The native
side expires stale sockets, rejects duplicates/cross-origin/non-loopback input,
and checks the exact generation requested by an observer. A live blocked GUI
is distinguished from an idle one. This introduces no periodic disk writes.
An open socket is not readiness: a fresh random challenge must pass through the
GUI event loop and return on a new request within two seconds. Readiness also
requires the concrete alert Loader/screen contract and runtime compilation of
the additional page components. This does not prove every page's bindings or
hardware behavior. Presence reports `installation_verified: false`; the disk
transaction, not a TCP connection or marker, verifies installation identity.
All four previous reviewed hook recipes remain recoverable.

### Persistent Trial and Recovery

`prepare` stores the authenticated pre-trial QML files and modes before switching
the entry point. Failure restores the exact prior generation, not necessarily
factory stock. Backups and archived trials are retained. Late remount failures
cannot reinstate a rejected candidate.

### Activation by Reboot

`BtClass100` cannot be restarted (TERM rebooted the tested station), so the
switched files only take effect with the next boot. Each step records the boot
it ran in (`/proc/sys/kernel/random/boot_id`) in small markers next to the
backups:

| Boot | Agent service start (`payload boot`) | Agent |
| --- | --- | --- |
| The boot that prepared the trial | keeps it | asks for one reboot once the station is idle |
| The first boot after it (trial boot) | records it as the trial boot, keeps it | waits for the trial display's lease, lets it settle for 15 s, then runs `boot-confirm` (up to three attempts, a minute apart) |
| Any later boot with the trial still pending | rolls back to the prior generation | – |

A trial is confirmed only in its trial boot. A power loss or crash in that boot
before the confirmation rolls back at the next start; there is no second trial
boot. A display without its lease after 10 minutes, or three failed checks,
leave the trial pending and the agent asks for one more reboot, after which the
start rule rolls back. `restore` withdraws the confirmation first and then asks
for a reboot, because the running display keeps the restored files' pages until
then.

The agent reboots only when Maintenance and its reboot are enabled, it hears the
door-entry frames, no call frame was seen for 120 s (an unanswered call counts
for at most 10 minutes), no media session, announcement or maintenance job runs,
the display is not in a call or another vendor state, and the station has been
up for 2 minutes. It asks once per reason and once more after 10 minutes if the
station is still up; otherwise it reports `reboot_blocked` and waits. There is no
forced reboot and no night window.

If the service start cannot check a pending trial (the payload is missing or not
a single-link regular file, or `payload boot` fails, for example after a vendor
firmware change), the agent still starts. Init writes the reason
(`payload_unavailable` or `boot_check_failed`) to `boot-check-failed` next to
the backups and clears it at the next start. The `payload boot` rule has
already rolled back where it could. While the mark is there, the agent reports
`boot_check`, keeps the display functions off, refuses `activate` with
`c100x_display_boot_check_failed`, and neither checks the trial nor reboots for
it; a `restore` and its reboot still work. The backups stay in place.

`GET /api/v1/maintenance/c100x-display` reports the phase, the confirmation, the
last result, a failed boot check and why a reboot waits; `POST …/actions/activate` and
`…/actions/restore` start the transactions. The confirmed adapter unlocks the key
beep, the display alerts (without a tone), the display bridge and the ringer
mute, and Home Assistant switches its device-UI setting on. Turning that setting
off restores the original display with its reboot.

The paths are exercised against original firmware copies with the actual host
native HTTP server and response parser, under the firmware `bash` and BusyBox
`sh` in `qemu-arm`, including hung connections, tampered journals,
missing/corrupt payloads and service-start failures. No GUI process is
signalled.

### Remaining Firmware Contracts

| Area | Exact evidence and remaining gap |
| --- | --- |
| GUI restart | Stock `bin/BtClass100_qws` ends with one `./bin/gui/BtClass100 &` and `wait`, with no restart loop. `cfg/stack_open.xml` names this wrapper with `working_mode=0` and `gui_check_conf=0`. The stock `bt_daemon-apps.sh` offers whole-stack start/stop, not an isolated GUI restart. A call-safe restart/respawn contract and recovery from a nonresponsive GUI have not been established; neither killing the GUI nor restarting the whole stack is an acceptable substitute. Stock `bin/bt_daemon` offline: a changed `/var/tmp/conf.xml` mtime first zips the file into flash (`0x14ee0`), then takes one of two branches. "update conf.xml without reboot process" (`0x15014`) restarts nothing. The other branch SIGTERMs every managed process (`0x1f6e0`), logs "EXIT AND REBORN!!" and exits 10 (`0x151b8`); the parent re-forks the stack on exit 10 (`0x1b0b0`). The branch depends on internal conf status and `restart_on_config_change` (`General Parameters`, no stock ini), so a touch is not a deterministic GUI restart. The software watchdog reboots via `hal_board_reboot` when a `/var/tmp/bticino/bt_wd/<name>` file is missing (`0x15520`); only `bt_av_media`, `bt_vct`, `scsserver` and `bt_device` import `bt_wd_common`, `BtClass100` does not, and `bt_daemon` installs no SIGCHLD handler. Why TERM to the GUI rebooted the tested station is therefore not explained offline. "RESTARTING SYSTEM DETECTED" is only a boot-time ramoops check (`0x186a8`). |
| Notify sound | In the exact stock `bin/gui/BtClass100`, the `startBeep` signal activation at `0x36af4` uses signal index 15. The worker at `0x1aeb0` calls `hal_beep_on(int)` and starts a timer; timer setup at `0x1ad8c` selects 170 ms, and `0x1aeac` calls `hal_beep_off()`. This is evidence of a short beep, not a cancellable Notify sound contract. There is no verified QML acknowledgement/cancel path for a queued beep when a call preempts it. `global.beepEnabled` is the stock key-tone preference, not proof of sound cancellation. Sound commands remain rejected. |
| Memo writes/voice | `lib/BtObjects/libbtobjects.so` exports `AnsweringMachine::getMemos()` (`0xd2a4c`), `addTextMemo` (`0xd4f40`), `saveTextMemo` (`0xd49a8`), `updateTextMemo` (`0xd4ff4`), `recordVocalMemo` (`0xd2d64`), `playVocalMemo` (`0xd2dcc`), `stopVocalMemo` (`0xd2d98`), `saveVocalMemo` (`0xd2e00`) and `discardVocalMemo` (`0xd2e94`). No stock `MemoPage.qml` supplies the corresponding UI/object/acknowledgement lifecycle. The display page reads text through the verified store contract; display-side writes, voice ownership and call-preempting cancellation remain unverified and are not exposed. Creating a text memo from HA is a separate agent path (`*8*87#4*##`, as on a C300X), not a display write. |

The four field-report tool/service/hash questions are cleared, not blockers.
These remaining contracts concern activation and side effects, not source
firmware recognition or official-app provisioning.

This matrix is a target, not a declaration that every row works. Capability
flags must stay false until the matching hook, command acknowledgement,
state readback, transactional installation and rollback are implemented and
tested together. Host Qt5 5.15 tests are useful but are not firmware Qt5 5.10.1
or hardware proof. Separately, `tests/test_c100x_firmware_compile.py` compiles
all 29 generated QML files using original ARM Qt 5.10.1 under QEMU (four tests,
including invalid syntax/import/property controls). This is compile-only:
no instances, binding evaluation, vendor/platform plugins or GUI startup.
Vendor imports, restart supervision, wake/sound and memo
runtime behavior require explicit evidence; missing evidence stays documented.
