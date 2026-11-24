# Firmware 3.0.6 Display Audit

Offline audit of beta `2.9.0b1`, 2026-11-22. The comparison firmware is
1.7.19. No device, HA instance, vendor executable or hardware plugin was
started. Model detection is deliberately outside this beta.

## Evidence Levels

- **F**: original firmware bytes, exported metadata, or original ARM libraries
  under QEMU. Each claim below identifies which of these was exercised.
- **H**: host runtime, isolated filesystem/HTTP fixture or substitute vendor
  objects. Useful regression evidence, not a device-runtime result.
- **D**: device verification still required. Supported does not mean proven
  operational on hardware.

The earlier full validation was stopped during pytest at the user's request.
It is **not passed**. No replacement full gate or coverage run was made.

## Original Artifacts

| Artifact | 3.0.6 | 1.7.19 |
| --- | --- | --- |
| `gui/BtClass` SHA-256 | `6e114e7d9ce17d4c587a13082720bb6b5e66d5683bfd12047321b9694f2971f8` | `0124e05e93988b27595c359bc88d521416ea38e8fef23f151216860dd0c13891` |
| `BtClass_qws` SHA-256 | `852a5b0f0755a738e4e25127cd10b903fbf9c2ebdb4109872d4e1d0aac13c59c` | `903eeca1eb142238f32345c6837125c29dcb2a5b63fb4eda935a82e70104229f` |
| Qt | ARM Qt 5.15.7; QtQuick 2.7 imports | ARM Qt 4.8.7; QtQuick 1.1 imports |
| Skin | 320 extracted resources, including `skins/default` | Files under `gui/skins/default` |
| Qt resource tables | v2; tree `0x35c6c`, names `0x3672c`, data `0x3791c` | Not used by the patch |

The Qt5 executable requests `qrc:/skins/default/main.qml`. Its dependencies
include Qt5Core, Qml, Quick, Gui, Widgets, Xml, `libqtobjects`, `libqtcommon`
and `libconnman-qt5`. `BtObjects/qmldir` names the vendor `qtobjects` plugin;
the original QtQuick.2 module is present. The resource probe registers the
original executable's tables as **data**, without loading its code.

Startup: `bt_daemon-apps.sh` starts `bin/bt_daemon` from `/home/bticino`;
`stack_open.xml` names `bin/BtClass_qws` as the GUI. The wrapper sets EGLFS,
Vivante, framebuffer/touch parameters, runs `local_alpha`, then `BtClass`.
`rc_mxc.S` is a console-login path, not the GUI supervisor. The daemon contains
restart/reboot handling, but its operational thresholds and the hardware
watchdog were not exercised. No reboot-loop absence is claimed.

## Confirmed Findings

1. **P1, fixed in `c34f8a2e`: unchecked RCC internal offsets reached Qt.**
   At baseline `0ae2093a`, `native_agent/qt5/qrc_overlay.c:85` checked header
   offsets only before calling `qRegisterResourceData`. With original
   firmware QtCore 5.15.7, corrupt child/name/data offsets and a short tree
   produced SIGSEGV; an oversized payload was exposed as a valid resource.
   A valid control resource read correctly. The loader now validates the
   complete generated v2 format before registration, rejects symlinks and
   marks rejected content failed. The original stock resource remains
   readable when the overlay is rejected. This proves a process-crash path,
   not a device reboot loop. Regression: `test_qrc_overlay_firmware.py` and
   `test_qrc_overlay.py`, including every truncation of the control resource.
2. **P2, fixed in `13e66f73`: HA action gates ignored Qt5 fallback.**
   At baseline `0ae2093a`, `capabilities.py:235`, `button.py:574` and
   `repair_issues.py:418` treated installed patch flags as sufficient.
   `patched=true, qt5_overlay=failed, gui_running=true` passed the action
   prerequisite; an inactive core overlay also cleared its Repair. Seven
   focused regression cases failed before the fix. Shared action predicates,
   button availability and core Repairs now use activation evidence while
   preserving the legacy Qt4 contract. No automatic quarantine retry added.

The earlier three fixes remain separate: `4c2781e4` transaction rollback,
`bfedea13` artifact reconciliation, `0ae2093a` installer/sync confirmation.

The subsequent restoration audit also confirmed a **P2** in the device-user
HTTP path (`http_device_user.c:263` at `fcca4a51`): a zero shell exit was enough
to continue routing restore even when label restoration reported `ok:false`.
Label setup/status also accepted an installed but quarantined Qt5 label.
The beta-specific adaptation validates structured outcomes and Qt5 label
activation, while still running the label restore on Qt5 and retaining any
unrelated quarantine. Original 3.0.6 QML/RCC restore runs through the actual
HTTP handler in the isolated fixture; device writes are substitutes.

## Installation And Runtime Matrix

| Path | Support and offline proof | Remaining uncertainty |
| --- | --- | --- |
| Extract original resources | **F** pinned real executable, six edited vendor files; complete resource manifest inspected | Different firmware builds need their own validation; scanner acceptance is not a support declaration |
| Shared QML generation | **F/H** actual 3.0.6 resources normalize and patch; 1.7.19 file patch restores byte-for-byte | Native context-object behavior during GUI startup: **D** |
| Pack/preload precedence | **F** original ARM QtCore reads valid overlay before the original resource tables; rejected overlay falls through to stock | Actual executable constructor sequence/complete boot: **D** |
| RCC validation | **F/H** bad internal offsets, lengths, cycles, short tables, headers, symlinks and all control-file truncations | Storage failure/power loss and concurrent external modification: **D** |
| Wrapper/environment | **F/H** exact original wrapper patch/restore; EGLFS settings and signal traps retained | EGLFS/Vivante, `local_alpha`, real signal delivery: **D** |
| Activation transaction | **H** RCC, wrapper, embedded preload, original-wrapper backup and failed marker snapshot/rollback; failed rollback retains recovery copies | Durability under physical power loss is not established |
| Backups/modes/ownership | **F/H** exact wrapper bytes and copied-tree mode/UID/GID restored; QML backups and unsafe-file checks exercised | Extracted-tree ownership is not evidence of on-device ownership or mount behavior |
| Unchanged apply | **H** deterministic RCC, current embedded preload, wrapper comparison; missing/stale artifacts repaired | A running PID is not a QML-ready handshake |
| Optional/core/label removal | **F/H** real core, label, full apply, optional restore and restore-all sequence; complete removal restores wrapper and removes overlay | Confirm native stock screen after removal: **D** |
| Early startup failure | **F/H** original wrapper under original ARM Bash 5.1.16 and host Bash; stock controls and bounded-log fixtures | Only errors within 60 seconds qualify; exits 0,137,138,140,143, later exits and hangs are not a general watchdog recovery mechanism |
| Quarantine recovery | **H** the mark holds for the boot that wrote it; partial restore and plain reloads keep it; the restart of an apply retries once (see Restart design) | Diagnose actual Qt error before retry: **D** |
| GUI versus agent restart | **F/H** bt_daemon starts the wrapper once and never again; one detached restart worker stops the old display completely before it starts exactly one new wrapper | Display release timing on eglfs/Vivante: **D** |
| Self-update | **H** changed QML and runtime-only preload reconciliation, optional pages on/off, pending follow-up retained on failure | Complete update/reconnect on firmware: **D** |
| Downgrade | **F/H** stable 2.8.2 payload refused without verified full removal; actual 3.0.6 restore-all then accepts it; Qt4 originals accepted | Guard requires this running updater; old agents and SSH/manual replacement bypass it; stock GUI restart: **D** |
| Python/shell installers | **H** require successful core/full status, GUI presence and Qt5 activation; Python publishes bundle identity after activation; an unknown display (below) ends only the display steps | Neither installer proves every page rendered |
| Unknown display | **H** an unknown program or start script leaves everything as shipped and reports `display_unsupported`; install, update and media user go on without the display pages (see Unknown Display) | A later vendor firmware build on a device: **D** |
| HA options/switch/sync | **H** quarantine/incomplete status is not success; optional-page setting is distinct from core hooks; no quarantine auto-retry | State freshness after spontaneous device failure: **D** |
| HA services/buttons/Repairs | **H** shared GUI action gates and core Repair honor Qt5 activation; notification storage is distinct from popup delivery | End-to-end physical action results: **D** |
| Native bridge | **Static/H** loopback UI listener, GUI headers for alert/ringer endpoints, bounded forwarding and cancellation; delivered QML targets port 8090 | Nondefault generic-agent UI ports are not adapted by delivered QML; use installer defaults |
| Qt4 compatibility | **F/H** original 1.7.19 patch round-trip, retained Qt4 rollback tests and dual-firmware ARM ABI check; Qt5-only RCC branch | Cold boot, touch fix, calls and media on Qt4: **D** |

## Pages, Hooks And API Matrix

All 15 custom QML components, after the package's source stripping and Qt5
import conversion, compile to `Ready` using **original ARM QtQml 5.15.7**.
This uses original stock QML and QtQuick imports but substitutes `BtObjects`
and `BtClass` types. No QML object is constructed in this probe. Separate
Host-Qt5 5.15.18 tests construct pages with substitutes and run layout cases;
these are not firmware rendering proof. No Qt6 result is used as Qt5 proof.

| Path | Evidence / parity | Device check still needed |
| --- | --- | --- |
| `MainApp`, `HomePage`, `MemoPage` | Actual vendor patch round-trip; home buttons, counters, memo hooks and settings compared with vendor baseline in host Qt5 | Real model binders, navigation and notifications |
| `Alarm.qml`, alarm JS | Firmware compile; host state/mode/PIN/command tests; unchanged shared Qt4 source | Alarmo states, PIN privacy, force/blocker handling and command feedback |
| `HomeAssistant.qml`, `C300XDetailControl.qml` | Firmware compile; host tiles, detail controls, lights/covers/climate/choices and action JS tests | Touch ergonomics, real HA responses and image latency |
| `C300XPageNavigation.qml`, `C300XOptionalPages.qml` | Firmware compile; optional Loader targets and host navigation/layout cases | Repeated back/page changes, standby/resume, cancelled late replies |
| `C300XEnergy.qml`, `C300XEnergyConsumers.qml`, `C300XEnergyReadout.qml`, `C300XEnergySums.qml` | Firmware compile; host fixtures; shared energy/consumer JS and stock assets | Chart rendering, scroll/drag and long-running updates |
| `C300XAgenda.qml` | Firmware compile and host layout; read-only event model | Locale/date labels and actual calendar refresh |
| `C300XLeaveHome.qml` | Firmware compile; host two-step confirmation, cancellation and offline/busy guards | Real actions and alarm navigation |
| `C300XChecks.qml`, `C300XSituations.qml` | Firmware compile; host checks/layout cases | Long names, changing availability and live state updates |
| `GeneralsChoice.qml`, preferences JS | Actual vendor patch; host feedback/touch-tone settings; optional removal restores stock settings | Persisted vendor touch tone and re-entry after restart |
| `CallBlockPopup.qml` | Real 3.0.6 label apply and full restore; label-only RCC retained until removal | Forwarding selection and actual native call behavior |
| `EventManager.qml` | Exact expected call/ringtone/key takeover hooks verified before full activation | Ordering of live calls, ringing, intercom, screen-on and alert preemption |
| `C300XRingerControl.qml`, ringer JS | Firmware compile; original AudioState methods/enums; request identity/expiry and teardown logic | Mute/unmute acknowledgement plus real device event/readback |
| `C300XAlerts.qml`, alerts JS | Firmware compile; host state-machine tests; original ScreenState/AudioState/GlobalProperties interfaces | Wake/sound duration, mute preservation, protected screens and preemption |
| `c300x_ha.js`, memos, i18n | Included in firmware compile; host page/action tests; bounded shared read queue, separate event long poll, generation-based cancellation | Network loss/HA restart/agent restart, translated text on physical screen |

All 20 literal image/JS references in delivered files resolve in both original
firmwares or the delivered source set. Original moc tables confirm
`ScreenState.stateChangedInt(old_state,new_state)`, `HwKeys.pressed/released(code)`,
`VdeAudioVideoController.ringtoneStarted/Finished(type)` and
`AnsweringMachine.isAssaabloy(name,where,lkid,brid)`. Normalizing these handlers
does not discard the parameter names used in their bodies.

Alerts do not toggle `RingtoneMute`: `shortBeep` temporarily owns only `Beep`.
Sound is restricted to Idle/Beep/RingtoneMute with no direct audio access;
calls and protected pages preempt it. Wake ownership is acquired only for an
observed alert-requested ScreenOff-to-Normal transition and relinquished on
interaction. The firmware metadata confirms the API surface, **not** audible
behavior, asynchronous wake cancellation or a real 30/30-second result.
Native alert acceptance is transport acceptance, not proof of wake or sound.

The follow-up executes the package-stripped alert controller in original ARM
**QJSEngine/QtQml 5.15.7**, without a GUI or vendor plugin. The test covers
0/30/300-second budgets, preemption, destruction, user interaction, delayed
native-wake replies, synchronous preemption before beep, protected pages, clock
rollback and pre-existing screen ownership. It reports `ALERT_LIFECYCLE_OK`.
This closes the pure-JS engine gap, not the substituted audio/screen IO or
vendor-signal delivery gap. Node tests still cover the QML transport boundary.

### GUI Restart And Quarantine

Redesigned after Dave's report in PR #126: a live apply left a sticky
`display-qt5.rcc.failed`, the core Repair stayed at `qt5_failed`, the agent
update stayed at `qml_patch_pending` and the media-user label could not be set.

Firmware facts (**F**, `bin/bt_daemon` of 3.0.6 disassembled; 1.7.19 has the
same `<gui>` entry and wrapper shape):

- The `apps_control` child of bt_daemon starts every configured process once
  with `call_nowait`, the `<gui>` entry `bin/BtClass_qws` included, and keeps
  the PID. There is no SIGCHLD handler and no restart of a single process. A
  PID is cleared and the process started again only by a working-mode switch
  or by the fault checker's `/var/tmp/flags/RESTART_SIGNAL_FLAG`, which stops
  and starts all processes.
- Supervision is a software watchdog. Every `wdt_timeout` seconds (at least
  32) bt_daemon checks `/var/tmp/bticino/bt_wd/<name>` of each running
  process, deletes it, and reboots the station if it is missing. `BtClass`
  writes `/var/tmp/bticino/bt_wd/BtClass_qws`, so a display that stays down for
  a whole period reboots the station.
- The wrapper's SIGTERM trap stops `BtClass` and exits; this is also how
  bt_daemon stops it.

So the earlier assumption that bt_daemon restarts the GUI was wrong: no second
starter exists on the device. The race was between the old display program,
still ending (eglfs/Vivante releases the framebuffer and GPU on exit), and the
new one, started after a fixed two seconds. The old `reload_gui` also returned
without starting anything when the old program was still alive after those two
seconds.

#### Restart design (rebuild, 2.10.0b1)

The first restart (`3876e2b4`) grew by patching and kept drawing findings: a
2 s presence check after the start defeated the wrapper's own retry, a stop
during the wrapper's `sleep 3` armed the vendor SIGTERM trap, which fired only
after that sleep and killed the next display, and back-to-back restarts left a
quarantine mark behind. It is replaced as a whole. Firmware 1.7.19 and 2.0.2
keep the restart of release 2.9.1 (`reload_gui_qt4`), unchanged.

**One restart worker.** Every Qt 5 restart (`reload`, a write's restart, the
rollback restart, `recover`) only files a request and waits for its answer.
The requests are served by one worker, `qml_patch.sh gui-worker`, started in
a session of its own and holding an `flock` on `<tmp>/c300x-gui-restart/lock`
for its whole life, so at most one restart is in flight. A worker takes all
waiting requests at the beginning of a cycle; requests that arrive during a
cycle are served together by the next one. A request is filed after its files
were written, so the cycle that takes it starts the display with them.
The agent's job time limit kills the requesting script's process group, never
the worker: a restart that has stopped the display always starts one again.
A request left by a worker that died is taken over by the next worker.

**One cycle:**

1. Stop: SIGTERM to the start scripts (`BtClass_qws`, all its subshells) and to
   `BtClass`; wait until every noted process is gone, at most
   `C300X_QML_GUI_STOP_SECONDS` (10), then SIGKILL the rest and wait 3 s more.
   A start script that does not end, for example one of an earlier beta
   sleeping before its retry, gets SIGKILL and cannot run its trap later. If a
   process survives that, nothing is started and the cycle fails.
2. Settle `C300X_QML_GUI_RELOAD_DELAY_SECONDS` (2) for eglfs/Vivante to release
   the framebuffer.
3. Start the installed start script once, executed directly, in its own
   session, without the worker's lock descriptor.
4. Verify within `C300X_QML_QT5_START_SECONDS` (30): ready when `BtClass` runs
   and has written its watchdog file after the start; failed when no start
   script and no `BtClass` run any more; the overlay failed when the start
   script wrote this boot's quarantine mark. A `BtClass` still running at the
   end counts as started (there is no QML readiness handshake).
5. Retry once: when the overlay failed in a cycle that should retry it (apply,
   core-apply, media-user-label-apply), stop again, settle, drop the mark and
   start again.
6. Fall back to stock: a second overlay failure keeps the mark for this boot,
   and the start script runs the vendor's own lines. When no display program
   runs at all after the start, the cycle marks the overlay failed for this
   boot and starts the verified original start script (the backup) directly.

**The start script** tries the overlay once per start, at boot and on a
restart alike: no retry loop, no `sleep`, so the vendor trap always runs at
once. An abnormal exit within 60 s writes the mark for this boot and starts
`BtClass` as shipped. The mark holds the boot id; a mark of an earlier boot
counts as absent, so the next boot tries the overlay once more.

**The mark** is written only by a failed overlay start (start script or
preload) and, while files change, by a write itself. It is dropped by the
retrying actions and by full removal; a successful overlay start leaves none.
A plain reload keeps a mark of this boot and starts stock.

**Time budget.** A request waits at most until 24 s after the script started
(`C300X_QML_GUI_BUDGET_SECONDS`), within the agent's 30 s job limit, and at
most 5 s after a signal. A cycle still running then is not a failure: the
write is committed and the worker finishes the restart; the status read
afterwards shows its outcome. Only a cycle that ended without any display
program fails the restart (and rolls a write back).

**Install and update.** A failed core-apply or apply on the Qt 5 display does
not fail the SSH install or the agent update: the agent is installed, the
display steps are reported (HA log, core Repair, Display patch switch), and
the core Repair retries them.

| Scenario | Behaviour |
| --- | --- |
| Boot, overlay crashes within 60 s | Mark for this boot, display as shipped. Next boot tries again. |
| Restart, first overlay start crashes (apply family) | The worker stops the stock fallback, settles, drops the mark and starts once more; a second crash keeps the mark and the stock display. |
| Back-to-back or concurrent restarts | One cycle at a time; requests waiting meanwhile share the next cycle. |
| Rollback while a start is in progress | Filed as a request; the cycle in flight ends first, then one cycle starts the restored files. No trap of an earlier start script survives. |
| Job deadline (SIGTERM, SIGKILL) in any phase | The worker finishes the cycle; a display runs afterwards. |
| Plain reload (button, service, CPU watchdog) | Keeps a mark of this boot; stock display. |
| Partial restore | Keeps a mark of this boot, drops an older one. |
| Display setting saves | Do not retry a quarantined overlay (`display_patch_sync`). |

### Unknown Display

The hash pins stay the safety gate: the overlay is only built for a display
program whose resource tables are known (pinned SHA-256 or the verified table
search) and only installed over the pinned original start script. When
`apply`, `core-apply` or `media-user-label-apply` meet anything else, the
script changes nothing and answers with exit 0:

```json
{"ok":false,"error":"display_unsupported","qt5_unsupported":"display_program_unknown","qt5_overlay":"off",...}
```

Reasons: `display_program_unknown`, `display_resource_missing` (the program
lacks a file the patch edits), `display_file_unsupported` (an edited file is
not in the expected form) and `display_wrapper_unknown`. The reason is kept in
`display-qt5/unsupported`; `status` reports it as `qt5_unsupported` until an
apply finds a known display again. Full removal (`restore-all`) only puts the
pinned original back over a start script that is this original plus one block
of the integration, of this or an earlier beta (from the `# c300x-qrc-overlay`
comment to the `fi` before `./bin/gui/BtClass &`). After a vendor update, or
any other change to the vendor's lines, it removes the overlay files,
leaves the start script as it is and records `display_wrapper_unknown`. Read and write errors (for example
`display_program_unreadable`) are not a reason: those steps still fail as
before. The check runs in a separate `qml_patch.sh qt5-prepare` process, so
`set -e` still guards every step of the extraction.

What follows from it:

- The SSH installer stops the display steps and still installs the agent
  (bundle identity published, warning in the HA log).
- The agent update follow-up counts as done; nothing stays pending.
- The agent's media-user setup completes without the label (the label lives in
  the display files); the HA media user switch counts it as complete.
- HA shows the non-fixable notice `device_display_unsupported` instead of the
  core hook Repair; the core Repair flow, if open, aborts with the reason.
  The Display patch switch shows off and names the reason in its attributes;
  turning it on fails with the reason. Settings saves do not ask again.
- Display-dependent features stay off as before: they already require a
  confirmed active overlay.

Firmware 1.7.19 and 2.0.2 are not affected: the check only runs on the Qt 5
display.

### Startup Guard Boundary

The guard is **startup-only**, not general reboot-loop protection. An abnormal
exit after 60 seconds, including a crash from a lazy-loaded page, does not
quarantine the overlay. Exit codes 0, 137, 138, 140 and 143 are excluded even
during startup. In particular, 137/SIGKILL may mean OOM or watchdog termination;
it is not evidence of an intentional restart. Hangs and successful exit after
an ignored preload are not detected by this guard either. Startup-only recovery
is the explicitly selected policy; late-crash quarantine is intentionally not
added. The existing timing and signal behavior remains unchanged.

Forty wrapper probes compare stock and patched wrappers under host Bash and
the original firmware `/bin/sh` (a link to `/bin/bash.bash`, Bash 5.1.16).
Only a harmless child runs; `local_alpha` and name-based signalling are
substituted. Early abnormal exit falls back to stock and creates quarantine;
excluded and late exits do not. SIGUSR1/2 reach the child and do not introduce
an extra launch. Both stock and patched wrappers return 2 under this POSIX Bash
probe on SIGTERM because the vendor trap uses bare `trap SIGTERM`; this is
retained vendor behavior, not an integration repair. Stock `wait` returns 0
after the child exits, while the patched wrapper propagates excluded/late exit
codes. The supervisor's response to those codes remains a device-only gap.
`qt5_overlay=active` describes installed artifacts, not an alive or ready GUI.

## Restoration Addendum

The separately requested routing/uninstall audit covers **C300X 1.7.19,
2.0.2 and 3.0.6 only**. It adapts the shared restoration logic from
`a371f84d` and `8a911207`; it does not import device detection, a C100X variant,
or the GUI-skipping guard from `aecb8104`. A C100X executable is used solely
as a rejected foreign-backup fixture. The Qt5 label path remains supported.

- **P1, complete backup identity:** the former `backup_is_stock` could accept
  matching patch ranges without authenticating the remaining file, and could
  accept another firmware's stock backup when the target identity was
  unknown. `fcca4a51` requires the backup's complete known hash and the target's
  complete original hash after replacing only the known patch ranges in
  memory. An interrupted patch is recoverable; unrelated corruption is not
  silently replaced. Installation uses a private sibling staging directory,
  verifies again before rename and checks the installed stock identity.
- **P2, label outcome:** `df2a2022` is the beta-specific HTTP correction
  described above. It runs Qt5 label restore instead of skipping it, checks
  reported failures, and does not advertise quarantined labels as applied.
- **P1, uninstall recovery retention:** before this addendum,
  `main.c:192` at `df2a2022` restored codec/camera patches but no routing, while
  `remove_agent.sh:233` could delete all backups. Removal now verifies that
  routing is already stock or restores it successfully before that cleanup.
  Bad backups, a patched target without a backup, and unknown or missing
  targets next to a backup block cleanup and reboot. A target the agent never
  patched (no backup and no patch) is left alone and removal continues.

| Original-copy test path | 1.7.19 | 2.0.2 | 3.0.6 |
| --- | --- | --- | --- |
| Apply, restore patched/stock/interrupted target, exact bytes and mode | Passed | Passed | Passed |
| Corrupt/patched/truncated/foreign backup, unknown/missing target, symlinks, rename/remount failure | Passed | Passed | Passed |
| Full uninstall with patched/stock/stale-backup/interrupted routing | Passed | Passed | Passed, with actual generated RCC and original wrapper |
| Failed uninstall retains agent/startup/backups, no reboot; retry after remount failure | Passed | Passed | Passed, without bypassing Qt5 restoration |

The removal fixture uses the real CLI and script, real firmware executable
copies and vendor QML. Process-control, mount and reboot commands are local
stand-ins. Earlier removal stages may already have restored QML/firewall and
stopped the agent before a later routing failure; retained files are recovery
material, not a claim that every preceding change was rolled back.

Focused tests: `test_native_routing_firmware_restore.py`,
`test_native_device_routing_backup.py`, `test_device_routing.py`,
`test_native_device_user_qt5.py`, `test_native_device_user_routes.py`,
`test_native_routing_removal.py` and `test_native_agent_removal.py`.
Results: 61 routing identity/backup tests, 76 device-user tests (including
ASan/UBSan cases), and 49 removal tests passed. These counts are separate
focused groups, not a full validation result.

## Follow-up Recovery Findings

**P2, baseline `b3192d0f`, `native_agent/scripts/qml_patch.sh:1516`:** full
removal unnecessarily repacked resources and relied on the disposable
`display-qt5/vendor` cache to distinguish stock from modified QML. Removing
that cache, one cached file, or altering one cached file left a new overlay
after `restore-all`; a failed packer prevented recovery altogether. Sixteen
regression cases failed before correction, including eight using original
3.0.6 resources and wrapper. Full removal now bypasses packing after restoring
the QML files, restores the stock wrapper and removes RCC/preload/quarantine.
Partial restore and the activation rollback remain unchanged. Regression:
`tests/test_qml_patch_qt5_recovery.py`, including rollback after reload failure.
Fixed in `3dfd7cbb`; its initial focused recovery/rollback group passed 106 tests.

**P1, baseline `3dfd7cbb`, `native_agent/scripts/qml_patch.sh:1367`:** wrapper
restore checked only that a backup file existed. Empty, syntactically invalid,
non-launching or already-patched backups could be copied over the live wrapper
and recovery reported successful with reload disabled. Eight regression cases
failed before correction (fixture plus original-firmware copies). The native
`--display-qt5 wrapper-check` now accepts only the complete known 3.0.6 wrapper
hash listed above, on a regular non-symlink file. Installation, no-op candidate
validation and restoration use that check; recovery checks both the staged copy
and final installed original. A same-length valid-shell change is rejected too.
The synthetic wrapper has a compile-time test-only entry, absent from production.
No model detection or basename whitelist is involved. Unknown custom wrappers
are intentionally refused, even if syntactically valid.

The original also needs an executable mode before activation writes begin.
Correct original bytes with modes `0644` or `0600` are rejected; fault tests
assert retained bytes, modes, inode identities and mtimes. This preflight does
not require an arbitrary host owner. Actual device ownership and mount behavior
remain separate checks. Recovery revalidates the copied and installed original.
The execute-mode recovery/transaction group passed 90 tests; the final
preflight group passed 34 selected nonregular-file, invalid-original and
copy/rename/remount cases after moving validation before writes. These overlap
the earlier groups and are not a full gate.

Failure injection includes missing/invalid backups, failed copy/rename,
successful-but-corrupt copy/rename and rw/ro remount failures. Failed recovery
restores prior activation artifacts and keeps backups. A final ro-remount
failure occurs after the new state is committed: it returns failure and keeps
original backups, but does not claim to roll back that already-committed state.
Fixed in `a052ff3b`. The follow-up Qt5 recovery/transaction/reconciliation/
overlay/packer group passed 147 tests, with 15 additional focused identity and
corrupt-copy cases and 17 original 3.0.6 removal/HTTP cases. These groups overlap
earlier runs; do not sum them into a unique full-suite result. Forty wrapper
lifecycle cases and three alert cases (one original QtQml, two host JS/QML
transport fixtures) passed separately. A private 1.7.19 patch/restore round-trip
and 23 selected Qt5 HA activation/update-follow-up cases passed too. The final
candidate build below now includes wrapper-check; these earlier tests alone
did not certify that older staged binaries contained it.

### Downgrade Recovery Guard

**P1, reproduced and fixed locally:** previously, the requirement to remove
the complete Qt5 overlay before installing stable 2.8.2 was documentation, not
an updater guard. Two isolated pre-fix updater probes (normal and ASan/UBSan) accepted a
2.8.2 bundle staged from local source commit `40cb1aa4`, replaced the native
payload and Qt5-aware `qml_patch.sh`, and retained the Qt5 artifact sentinels.
Both reported 28 changed files. The staged executable was synthetic and never
executed: this proves the file-installation path, not subsequent GUI/HA behavior
or the bytes of a published release binary. The stable source script has no
Qt5 overlay restoration implementation.

The probe is retained outside the repository as
`/var/tmp/c300x-beta-downgrade-probe.py`; its output markers are
`BETA_ACCEPTED_STABLE=1`, `QT5_RESTORE_SCRIPT_REPLACED=1` and
`QT5_ARTIFACTS_RETAINED=1`. No stable code was changed.

The beta bundle now declares integer `qt5_recovery_version: 1`, included in
the bundle identity. This is a publisher contract for the complete runtime
and recovery scripts, not a version-name heuristic or model detection. The
native updater still validates staged file hashes first. Before any installed
file backup, root remount, replacement or activation callback, it then requires
one of these conditions:

- The target declares exactly one top-level supported recovery version. Such
  updates retain recovery even with a quarantined or incomplete overlay; they
  do not clear quarantine or establish running-GUI activation.
- For older/unsupported targets, all three activation artifacts
  (`display-qt5.rcc`, `c300x-qrc-overlay.so`, `display-qt5.rcc.failed`) must be
  absent, and the live wrapper must be a regular executable with the full
  original 3.0.6 or shared 1.7.19/2.0.2 SHA-256. Empty files, dangling symlinks,
  directories, filesystem errors, missing/modified/non-executable wrappers and
  differing activation-path environment overrides are not proof of removal.

Rejection is HTTP 409 `qt5_recovery_required`, without deleting the stage,
scheduling a restart or replacing recovery. Existing maintenance serialization
rejects update requests during another maintenance job. Extraction caches and
original backups may remain after successful full removal; they do not activate
the overlay. File-set version stays 6 so old phased bootstraps remain valid.

`tests/test_firmware_beta_downgrade_guard.py` exercises the actual update entry
point on host and ASan/UBSan, including stable source `40cb1aa4`, real 3.0.6
resource extraction/patch/full removal, rejected removal with a non-executable
original backup, and successful downgrade only after verified restoration.
Negative cases assert unchanged installed bytes, modes, inodes and mtimes,
zero remounts/activation callbacks and no update backups. Original Qt4 wrapper
controls, malformed/duplicate capability metadata, payload corruption, retained
quarantine, capable beta updates and no-write retry are covered too. Synthetic
staged executables are never run; these tests do not prove firmware GUI startup.
The focused run passed 130 tests without skips: 80 downgrade-guard cases plus
50 update transaction, finalization, historical bootstrap and HA follow-up
regressions. Five additional selected staging/bundle-identity tests passed.
This is not a full gate or a firmware-runtime certification.

The guard applies only when the running updater contains this implementation.
Older beta/stable agents and direct SSH/manual installs are not retroactively
protected. Capability metadata is not cryptographic publisher authentication or
proof of the target binary's behavior. The manual full-removal prerequisite and
checking the running stock GUI remain mandatory. Startup quarantine remains
limited to the explicitly requested first 60 seconds and existing signal policy.

### Local Candidate Build

The deferred native build blocker is resolved for source commit `244e988c`, without
changing version `2.9.0b1`. This includes the stable shutdown-race port
(`20456010`, from `17c5aee3`) and pinned release-evidence checks from `c5a1e988`,
adapted without changing the beta release identity. The agent's shutdown signal
now wakes an idle poll even when delivered just before polling or to a worker;
this does not change GUI quarantine policy. Ten focused host/ASan/UBSan shutdown
tests and 320 offline pipeline/package/version tests passed without skips. The
80 downgrade-guard cases passed again after the ports; they are a rerun of the
guard coverage above, not additional unique cases.

The ARMHF agent and embedded Qt5 preload were rebuilt once after both ports
using the private original 1.7.19 libraries. Both passed `check_agent_abi.py`
against the original 1.7.19 and 3.0.6 roots. The stripped, packaged agent also
passed the same dual-firmware ABI check.

`native_agent/build-lock.json` now binds the current native/bundle inputs to
packaged executable SHA-256
`43834f896bed6acb0b72ed9aed8d9ed0ab559cd136b9b3477934bf5a8ecbbd88`.
The local staged bundle and HACS ZIP were regenerated. `check_release_contents.py`
verified exact source content and executable identity with both `--agent-binary`
and `--build-lock`; `native_build_lock.py --check-inputs` passed. The bundle
declares `qt5_recovery_version: 1` and retains file-set version 6.
The local ZIP SHA-256 is
`dffa30135763b05cc910cf4db9a5feb2d9d25d6cff13e0f406913f308413a696`;
the regenerated checksums and SPDX document also passed their package checks.
This ZIP also contains the HA-only camera-quality menu-order port `6bac29ff`
(13 focused tests passed), repackaged without another native rebuild or changes
to the beta release notes, version or reviewed native executable.

This resolves the stale binary/build-lock/package gap, not the device checks.
No full gate was run; the earlier interrupted full validation is not a pass.
Local release metadata remains `local-unverified`, not canonical CI evidence,
and lists no validated HA versions or jobs without verified evidence.
The startup-only first-60-second guard and excluded exit/signal statuses are
unchanged. This local build is neither a publication nor an activation approval.

## Focused Reproduction

Set `PYTHON` to the existing project virtualenv, `FW306` and `FW1719` to
private read-only extracted roots, and `AUDIT` to a new directory under
`/var/tmp`. Do not commit extracted firmware or the resulting manifests.

```sh
"$PYTHON" scripts/extract_btclass_resources.py "$FW306/home/bticino/bin/gui/BtClass" "$AUDIT/vendor"
export C300X_QT5_FIRMWARE="$FW306"
export C300X_QT5_SKIN="$AUDIT/vendor/skins/default"
export C300X_DEVICE_SYSROOT="$FW1719"
"$PYTHON" -m pytest -q -s tests/test_display_firmware_artifacts.py tests/test_qml_patch_firmware.py --basetemp="$AUDIT/artifacts"
"$PYTHON" -m pytest -q tests/test_qrc_overlay_firmware.py tests/test_device_qt5_firmware_compile.py --basetemp="$AUDIT/runtime"
"$PYTHON" -m pytest -q tests/test_qrc_overlay.py tests/test_display_activation_consumers.py
```

Expected markers: `REAL_QT5_PATCH_RESTORE_OK`, `SHARED_LITERAL_ASSETS=20`,
`FIRMWARE_METAOBJECT_CONTRACT_OK`, `NORMALIZED_SIGNAL_PARAMETERS_OK`.
The compile log records `FIRMWARE_QT_VERSION=5.15.7`, fifteen
`COMPILE_STATUS=1` lines and `COMPILE_FAILURES=0`. To reproduce the old RCC
failure, supply a pre-fix ARM overlay through `C300X_QT5_TEST_OVERLAY` to the
resource tests. Never run the malformed resources in a device GUI.

Follow-up reproduction (same private firmware environment, fresh temporary
directories):

```sh
"$PYTHON" -m pytest -q tests/test_qml_patch_qt5_recovery.py tests/test_qt5_wrapper_identity.py
"$PYTHON" -m pytest -q tests/test_qt5_firmware_wrapper_lifecycle.py
"$PYTHON" -m pytest -q tests/test_qt5_firmware_alert_lifecycle.py
"$PYTHON" -m pytest -q tests/test_firmware_beta_downgrade_guard.py tests/test_native_agent_update_legacy_bootstrap.py tests/test_firmware_beta_update_compatibility.py
```

The original-QtQml runtime probe emits `FIRMWARE_QT_VERSION=5.15.7`,
`JS_RESULT=ALERT_LIFECYCLE_OK`, `JS_ERROR=0`. The wrapper helper rejects unknown
content with `display_wrapper_unknown`; tests require nonzero restore exit and
unchanged recovery artifacts on failed restoration, not merely a diagnostic.

## Known Trap: One Marker For Camera And Display

`/usr/lib/libQt5Core.so.5` is the only firmware marker on this branch, and it
drives two unrelated paths:

- the camera: `c300x_device_display_is_qt5()` in `config.c` makes
  `camera_quality.c` (`low_stream()`), `camera_restore.c`, the capability
  `camera_resolution_fixed` and the video config in `http.c` use the
  low-resolution stream only (3.0.x has no high-resolution branch);
- the display: `qml_patch.sh` (`C300X_QML_QT5_MARKER`) and the installer take
  the rcc overlay path instead of QML files on disk.

The C100X (branch `c100x_1.5.8`) also ships Qt 5 (5.10), but with QML files on
disk, and its camera need not share the 3.0.x limit. When the C100X work is
merged, the marker would send it down both 3.0.x paths at once. Split the decision into a camera fact
and a display fact before that merge; until then, do not reuse this marker for
anything new.

## Before Merge On Devices

1. Cold boot 3.0.6 with full/core-only/off states; inspect GUI process and
   overlay status/log, daemon behavior, and stable stock fallback.
2. Explicit controlled startup failure: quarantine for this boot, no
   quarantine after a reboot, retry by apply and by the core Repair; live
   apply and back-to-back apply without a mark; test recovery access first.
3. Update QML and runtime independently; verify the running GUI uses new
   resources, not only that agent version/status changed.
4. Navigate every page, settings and native call screen; exercise language,
   touch, standby/resume, image loading and stale callback cancellation.
5. Receive/answer/end door, intercom and floor calls while alerts are active;
   verify immediate preemption without mute, audio or screen-lease leakage.
6. Verify wake/sound at 0, 30 and maximum duration, muted/unmuted states,
   protected screens, user interaction, clock changes and network loss.
7. Remove optional pages, label, core and then the complete agent; verify
   originals, modes/ownership, read-only remount and stock GUI operation.
8. Repeat the affected startup, removal, calls, ringer and touch paths on
   1.7.19. Stable downgrade on 3.0.6 requires complete beta overlay removal
   first; stable 2.8.2 has no Qt5 recovery support.
