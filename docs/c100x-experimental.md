# C100X 1.5.8: Experimental Branch

This document applies only to `c100x_1.5.8`, not the separate stable 2.8.2 or
3.0.6 beta worktrees/packages. C100X 1.5.8 has been inspected and tested
offline against extracted firmware and synthetic fixtures. No C100X device
or Home Assistant installation was accessed for this work. ABI compatibility
does not establish runtime or hardware support.

For the separately scoped issue #51 first test, use the
[agent-only test preparation and recovery checklist](c100x-test-release.md).
The release number/channel remain undecided; publication is blocked locally.

A contributor has since supplied observations from a 1.5.8 device with Companion
installed and non-stock routing. See the [field-report cross-check](c100x-field-report.md) for verified
binary matches, readback evidence and the remaining coexistence limits. These
observations do not validate installation or runtime of this branch's agent.

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
| Model, firmware and SIP identity | Implemented; hardware unproven | Detects `BtClass100`, reports C100X and uses vendor SIP account `c100x`. Existing ID, hostname and `_bticino-c300x-agent._tcp` discovery service remain unchanged; default discovery name/model are C100X. |
| Agent build / ABI | Offline validated | Oldest C300X build baseline retained; C100X 1.5.8 remains an additional ABI check. This is not a process-start or endurance test. |
| Routing / media user | Implemented; hardware unproven | C100X-specific `bt_answering_machine` table matches all nine stock patch ranges. Patch apply on a temporary firmware copy passed; registration, ring answering and vendor-app coexistence still require a device. |
| HA entities and callbacks | Capability-gated; hardware unproven | Door, stair light, ring/call events and supported maintenance controls retain their existing paths. Physical outputs, event timing and callback reachability are not proven. |
| Ringer volume | Retained; hardware unproven | Independent from mute; the vendor volume command still needs physical-level and persistence checks. |
| Ringer mute / key tone | **Unavailable to HA; offline bridge implemented** | The separate Qt5 bridge uses stock AudioState/beep properties with readback and call/commissioning guards. The bundle carries its source but does not activate it through the supported installer. Mute remains advertised false and rejected before device I/O; volume/events retain their paths. |
| Device dashboard / display notify | **Unavailable to HA; offline adapter and verified disk trial implemented** | All additional pages remain the target, tracked in [Display Parity](c100x-display-parity.md). Separate Qt5 pages, Loader hooks, key navigation, settings, compact file-set-7 delivery, silent/wake Notify and read-only text memos have focused offline tests. Persistent trials now require a fresh GUI challenge response and automatically restore prior files on failed confirmation; agent startup recovers pending trials. Supervised GUI restart/runtime rollback and production activation remain incomplete. Notify sound and memo mutations lack the specific contracts documented in the parity matrix. Setup/options, patch apply and bridge setup remain suppressed. Saved display configuration is retained but ineffective; Alarmo configuration remains independently available. |
| Camera / snapshot / RTSP | Implemented; hardware unproven | C100X is fixed to the low-resolution branch; no resolution selector. Stock settings describe 640x480, 12 fps and 800 kbps. Decoding, quality changes, snapshots, ring capture and multi-client behavior need device tests; these values are not a quality guarantee. |
| Listen / talkback | Implemented; hardware unproven | Stock Speex/8000 remains the first-test baseline. Firmware-PCMU apply is blocked in core/API/CLI and not offered by HA; read-only status and Speex recovery from validated managed backups remain available. Client-side PCMU transport/transcoding is unchanged. SIP negotiation, SRTP/RTP, both directions and stop/teardown still require separately authorized hardware acceptance. |
| Announcements / TTS | **Unsupported; incompatible backend explicitly blocked** | Model guards reject C300X playback, startup cleanup and legacy-worker takeover on C100X even if foreign tools are present. The original memo/WAV route requests an unsupported HAL profile; ringtone/global-stop paths lack safe per-owner cancellation. No C100X speaker backend was implemented. See the [original-firmware audio evidence](c100x-audio-analysis.md). |
| Memo / answering-machine features | **Text display implemented offline; recording/playback unproven** | A separate key-operated text page reads the existing bounded loopback snapshot, without changing read flags or files. Stock binaries identify the text storage/metadata and AnsweringMachine methods; these are not runtime acknowledgement or recording/playback proof. Voice controls and display-side mutations are not exposed. Do not treat generic entity availability as confirmation of working recordings. |
| Install / authentication / update / uninstall | Offline guards and fixtures; hardware unproven | Actual credentials, service startup/reboot, runtime library loading, uninstall recovery and vendor operation afterward still require a device. Uninstall is not a factory reset or unroot operation. |

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
2. Use the separate agent-only checklist first: install only the approved package
   on an authorized C100X and check startup, API/maintenance auth and discovery.
   Before any later display trial, finish supervised GUI restart/runtime recovery
   and verify the complete rebuilt bundle/update path offline.
   A package whose display gate remains false must not patch/restart the GUI
   or expose display controls. Do not force the gate through metadata changes.
3. For an explicitly enabled display trial, verify original backups, safe
   activation, failed-start rollback and reboot persistence. Exercise every
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
