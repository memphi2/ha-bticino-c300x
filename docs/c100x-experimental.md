# C100X 1.5.8: Experimental Branch

This document applies only to `c100x_1.5.8`, not the separate stable 2.9.1 or
3.0.6 beta worktrees/packages. C100X 1.5.8 has been inspected and tested
offline against extracted firmware and synthetic fixtures. No C100X device
or Home Assistant installation was accessed for this work. ABI compatibility
does not establish runtime or hardware support.

For the separately scoped issue #51 test, use the
[test checklist](c100x-test-release.md): agent, stair light, door unlock, one
video stream and ring call, then the display activation by reboot.
Use otherwise stock C100X firmware 1.5.8; only the changes needed for
root/SSH access are in scope. Running alongside Companion is not supported.
The release number/channel remain undecided; publication is blocked locally.

A contributor subsequently installed the earlier agent-only package on a
modified 1.5.8 station with Companion. The agent started and served
authenticated requests after installer workarounds; the reporter then rolled
back manually without rebooting. See the [field-report cross-check](dev/c100x-field-report.md).
This was not a stock-station test or acceptance of Companion coexistence.

## Prerequisites

- An independently SSH-enabled C100X with a **known, working privileged SSH
  credential** is required for the initial install. This project does not
  enable SSH on stock firmware or supply rooting instructions.
- The C100X factory credential supplied by the user has been verified offline
  against the root password hash in the original C100X 1.5.8 image. This is not
  a device login test and does not imply that a device's password is unchanged.
  A known C100X uses that default directly. Before model detection, bootstrap
  permits at most two factory credentials: unchanged C300X first, then C100X
  only after authentication refusal. Connection/time-out failures do not cause
  a second attempt. Explicit credentials always take priority, with no fallback.
  Credentials are not stored in the HA entry. An installed agent can instead
  use its configured API/maintenance tokens, which are not SSH passwords.
- Keep the vendor SIP provisioning intact. The stock filesystem alone does
  not contain the runtime Flexisip users/domain/keystore data. Initial vendor
  app registration is an expected prerequisite, not something the integration
  synthesizes from the stock image.
- Use a package built from this branch and keep a recovery copy. A normal
  C300X stable/beta package is not a substitute, even if its version number
  is identical or newer. No public C100X channel/version policy is defined.

## Support Matrix

| Area | C100X 1.5.8 status | Evidence and limits |
| --- | --- | --- |
| Model, firmware and SIP identity | C100X / 1.5.8 reported on one modified station | SIP identity was not validated end to end. Discovery: **implemented offline; hardware unproven.** A C100X agent announces `_bticino-c100x-agent._tcp` (a C300X keeps `_bticino-c300x-agent._tcp`); HA discovers both, and an announcement of one model never matches, renews or moves an entry whose agent reported the other model. Manual setup by host worked. |
| Agent build / ABI | Offline validated | Oldest C300X build baseline retained; C100X 1.5.8 remains an additional ABI check. This is not a process-start or endurance test. |
| Routing / media user | Implemented; hardware unproven | As on a C300X, setup presets video and the HA media user, and the first HA start creates the user and patches `bt_answering_machine`. The C100X-specific table matches all nine stock patch ranges; patch apply on a temporary firmware copy passed. A `route.conf` that is not a link to `route_int.conf`/`route_ext.conf` is refused (`unsupported_active_route`) and nothing is written. Registration, ring answering and vendor-app coexistence still require a device. |
| HA entities and callbacks | Capability-gated; hardware unproven | Door, stair light, ring/call events and supported maintenance controls retain their existing paths. There is no Display reload button (the GUI cannot be restarted) and no firmware codec selector. Physical outputs, event timing and callback reachability are not proven. |
| Ringer volume | Retained; hardware unproven | Independent from mute; the vendor volume command still needs physical-level and persistence checks. |
| Ringer mute / key tone | **Only after the display activation; hardware unproven** | The separate Qt5 bridge uses stock AudioState/beep properties with readback and call/commissioning guards. Mute and key tone are advertised only once the adapter was confirmed in its trial boot; before that, mute is rejected before device I/O. The bridge acks the AudioState flag it reads back and undoes a change that caused no transition; the agent pushes an unmute seen on the bus to the GUI, which otherwise follows only a bus mute. Volume/events retain their paths. |
| Device dashboard / display notify | **Available after the display activation by reboot; hardware unproven** | All additional pages remain the target, tracked in [Display Parity](dev/c100x-display-parity.md). Separate Qt5 pages, Loader hooks, key navigation, settings, compact file-set-7 delivery, silent/wake Notify and read-only text memos have focused offline tests. The pages take effect by reboot: **Activate display pages** switches the files, the agent reboots the idle station, confirms the trial display in the next boot and otherwise rolls back at the start after it ([details](dev/c100x-display-parity.md#activation-by-reboot)). A confirmed adapter enables the display setting in HA; turning it off or **Restore original display** brings back the original display with one reboot. GUI restart stays unavailable. Notify sound and memo mutations lack the specific contracts documented in the parity matrix. Setup/options and bridge setup stay suppressed until the adapter is confirmed; the C300X Display patch is never applied, and its home-button layout is not offered. Until then, saved display configuration is retained but ineffective; Alarmo configuration remains independently available. |
| Camera / snapshot / RTSP | Implemented; hardware unproven | C100X is fixed to the low-resolution branch; no resolution selector. Stock settings describe 640x480, 12 fps and 800 kbps. Decoding, quality changes, snapshots, ring capture and multi-client behavior need device tests; these values are not a quality guarantee. |
| Camera picture controls | Implemented offline; hardware unproven | Brightness, contrast and saturation through the direct V4L2 path, as on a C300X HW rev 4: same `mxc_v4l2` capture signature and TVP5150 decoder; eligible only on C100X 1.5.8 with the TVP5150 bound, by the runtime model. HA writes the station's day steps (brightness 30-220, contrast 80-255, saturation 80-255, from its `stack_open.xml`); night values and off-grid menu steps read as the nearest day step. Picture effect, night switching and the start values of the next stream need a device test. |
| Listen / talkback | Implemented; hardware unproven | Speex/8000 is the C100X firmware codec; HA and the browser still get PCMU through the agent's transcode. **Firmware PCMU is unsupported on the C100X:** 1.5.8 runs the device-side PCM at 16 kHz (`<sampling_rate>16000</sampling_rate>`, C100X only), its PCMU send pipeline has no resampler and `rtppcmupay` accepts only 8000 Hz (the device's own gst-launch fails to negotiate at 16 kHz under qemu); 8000 Hz is not possible either, because the ZL38067 is the I2S clock master with all DSP profiles at 16 kHz ([details](dev/c100x-audio-analysis.md)). Firmware-PCMU apply is therefore blocked in core/API/CLI and not offered by HA; read-only status and Speex recovery from validated managed backups remain available. SIP negotiation, SRTP/RTP, both directions and stop/teardown still require separately authorized hardware acceptance. |
| Announcements / TTS | **Unsupported; incompatible backend explicitly blocked** | Model guards reject C300X playback, startup cleanup and legacy-worker takeover on C100X even if foreign tools are present. The original memo/WAV route requests an unsupported HAL profile; ringtone/global-stop paths lack safe per-owner cancellation. No C100X speaker backend was implemented. See the [original-firmware audio evidence](dev/c100x-audio-analysis.md). |
| Memo LED (Notify `led`) | **Unsupported; not driven** | No memo LED is proven on C100X hardware, so the agent never claims or lights `/sys/class/leds/led_memo` there and reports `memo_led` false, even when such an LED is present. HA then refuses Notify `led: true` (and `mode: led`) before anything is stored; `display` and `tts` follow their own rows. |
| Answering machine and voice memos | **Unsupported: the vendor HAL switches it off** | The C100X is the SHARK board (board id 16 in `liblghal`'s `hal_board()` table). Its `hal_get_aswm()` returns `0xff` for boards 16/18 and `hal_set_aswm()` refuses them; `bt_answering_machine` (stock key object 154) then logs "Force answering machine OFF" at start, and on a ring "Answering machine is not enabled!": nothing is recorded. `*8*91` would only write `Activated=1` to `aswm_settings.ini`. Voice memos need a GUI recorder the C100X lacks. The agent therefore reports `answering_machine` and voice memos unsupported and answers their routes, and memo delete, with `409 answering_machine_unsupported_model` before any device I/O; HA creates no answering-machine switch, video-message or voice-memo sensor, delete button or media entries for a C100X, and its video-message and voice-memo actions refuse a C100X entry. |
| Text memos | Read and write offline-verified; hardware unproven | The memo store format and the vendor's `memos_text` code are identical to C300X 1.7.19, where HA's text-memo write is established. As on a C300X, the agent saves a memo through the station: it writes `/var/tmp/records/message.txt`, sends `*8*87#4*##` and asks for the list. In the 1.5.8 `bt_answering_machine` the `*8*87` handler and the frame dispatcher that calls it are instruction-identical to 1.7.19 and check no answering-machine activation, and `/var/tmp/records` is created the same way; a save the station refuses answers `502 memo_create_refused`. A separate key-operated text page reads them through the agent, read-only. Memo delete is off on the C100X: HA offers it only with the C300X Display patch. |
| Install / authentication / update / uninstall | Earlier agent startup and token enforcement observed on one modified station | The test package installs only on a C100X: the SSH bootstrap refuses a C300X before any write, setup refuses a C300X that already runs an agent, and a C300X entry is told to use the regular package. Fresh standalone install without workarounds, survival across reboot, update and scripted removal remain unverified on hardware. Uninstall restores the original display files and the stock routing binary before it deletes the agent; it is not a factory reset or unroot operation. |

## Package Protection

This branch's generated `device_agent/bundle.json` declares
`"c100x_compatible": true`. The declaration participates in the generated
bundle hash; it expresses package compatibility, **not** proven hardware
features or a public release designation.

New local test bundles also declare `"c100x_only": true`, included in that
hash. This branch's HA/SSH paths and new native updater reject them on C300X,
including 3.0.6. Older updaters lack this reverse guard. The shared HA domain
still requires a separate test instance; this is not an independent HACS channel.

- HA marks a known-C100X/unmarked-package combination incompatible, with no
  self-update or SSH-reinstall repair offered. Direct API upload also checks
  current setup metadata before staging.
- The installed C100X-aware native updater independently rejects a missing,
  false or invalid declaration with `update_model_incompatible` before file
  replacement, even if an older HA client sends the package. The existing
  per-file SHA256 and transactional validation still apply to accepted
  packages. A rejected upload can leave staging files, not replaced runtime
  files; prepare of a later valid update clears/reuses the staging area.
- This branch's SSH installer detects C100X and refuses an unmarked/missing
  manifest or a binary that does not match the manifest's SHA256 before its
  first remote write. A source checkout without a staged, verified bundle
  cannot bypass this check merely by finding an ARM binary in `build/`.

These are compatibility guards, not a signature trust system. They cannot
stop arbitrary privileged SSH/manual overwrites, an older independent SSH
installer, or a deliberately falsely labelled package. Previously installed
C100X agents without this guard do not acquire native-side protection until
updated with this branch's guarded agent. Use only a reviewed branch package;
do not change the manifest to force an incompatible update through.

## Routing Recovery

Routing restore requires a known whole-file stock SHA256 and a matching
target firmware identity. Recovery of an interrupted patch is accepted only
when replacing its known patch ranges reconstructs that same stock hash.
Corrupt/foreign backups, symlinks, missing targets and damage outside those
ranges fail closed; recovery files remain available for manual investigation.
Restore stages and verifies the file privately before atomic replacement.

C100X media-user restore skips unsupported GUI label operations. Uninstall
also skips the C300X GUI/display-library paths and verifies routing restoration
before deleting the agent or backups. A verified stock target needs no backup
and no routing write. Failed restoration prevents deletion and reboot;
hardware recovery and vendor operation after uninstall remain untested.

## Minimum Device Acceptance Plan

These steps require separate explicit authorization and have **not** been run:

1. Confirm SSH credentials and backup/recovery access. Record firmware/model,
   vendor app operation, SIP provisioning and original changed-file hashes.
2. Use the [test checklist](c100x-test-release.md) first: install only the
   approved package on an authorized C100X and check startup, API/maintenance
   auth, discovery, the media user, video and a ring call.
   Until the display activation is confirmed, the package must not change the
   GUI or expose display controls. Do not force the gate through metadata changes.
3. For the [display activation by reboot](c100x-test-release.md#display-activation-by-reboot-device-test),
   verify original backups, the trial-boot confirmation, the rollback after an
   interrupted trial and restore by reboot. Exercise every
   enabled/ordered page at 800x480 with Up/Down/Return/back, including scrolling,
   entity controls, Energy subpages, Alarmo/PIN, notifications and settings.
   Verify mute/key-tone readback and call/commissioning preemption. Check door,
   stair, ring/call, volume and vendor-app coexistence before/after every phase.
   TTS and unverified memo operations must remain unavailable.
4. Exercise live camera, snapshots, ring answer/end, listen and talkback in
   each direction. Verify teardown releases media and preserves vendor calls.
   Test memo features separately; report unsupported behavior rather than
   treating advertising as proof.
5. Exercise compatible update/no-op retry and an incompatible-package
   rejection, then uninstall/reinstall and reboot. Verify expected backups,
   routing restoration, continued SSH recovery and original vendor behavior.

## Offline Regression Commands

Run in this worktree with the main repository's `.venv/bin/python`:

```sh
export CURL_INCLUDE_DIR="$HOME/.cache/c300x-https/headers/usr/include/x86_64-linux-gnu"
PY=../ha-bticino-c300x/.venv/bin/python
"$PY" -m pytest -q tests/test_native_ringer_response.py tests/test_native_agent_capabilities.py tests/test_switch.py tests/test_number.py
"$PY" -m pytest -q tests/test_c100x_display_support.py tests/test_options_display_menu.py tests/test_init_runtime.py
"$PY" -m pytest -q tests/test_c100x_update_compatibility.py tests/test_native_agent_update_runtime.py tests/test_device_installer_bundle_transactions.py
"$PY" -m pytest -q tests/test_native_mdns_runtime.py tests/test_discovery.py tests/test_entity.py
```

The fixtures create temporary directories; native tests redirect install/init
paths there and intercept system service operations. They do not access a
device. The full validation gate is coordinated separately and is not a
substitute for the acceptance plan above.

Additional focused C100X checks:

```sh
"$PY" -m pytest -q tests/test_c100x_display_transaction.py
"$PY" -m pytest -q tests/test_c100x_gui_presence.py
CURL_INCLUDE_DIR="$HOME/.cache/c300x-https/headers/usr/include/x86_64-linux-gnu" \
  "$PY" -m pytest -q tests/test_c100x_activation.py
PYTHONPATH=/tmp/c100x-qt5-runtime "$PY" -m pytest -q tests/test_c100x_qml_adapter.py
"$PY" -m pytest -q tests/test_c100x_firmware_compile.py
PYTHONPATH=/tmp/c100x-qt5-runtime "$PY" -m pytest -q tests/test_c100x_alerts.py
PYTHONPATH=/tmp/c100x-qt5-runtime "$PY" -m pytest -q tests/test_c100x_memos.py
```

The host Qt5 package path above is an optional isolated local test environment,
not a device dependency. Its visual probe covers 80 component scenarios and
key propagation. The independent firmware probe compiles all 29 currently
generated QML files against the original ARM Qt **5.10.1** under QEMU, with
negative syntax/import/property controls. It creates no QML instances or GUI,
loads no platform/vendor plugins and proves neither binding evaluation nor
hardware operation. Rerun it whenever generated QML changes.
