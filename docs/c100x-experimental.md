# C100X 1.5.8: Experimental Branch

This document applies only to `c100x_1.5.8`, not the separate stable 2.8.2 or
3.0.6 beta worktrees/packages. C100X 1.5.8 has been inspected and tested
offline against extracted firmware and synthetic fixtures. No C100X device
or Home Assistant installation was accessed for this work. ABI compatibility
does not establish runtime or hardware support.

## Prerequisites

- An independently SSH-enabled C100X with a **known, working privileged SSH
  credential** is required for the initial install. This project does not
  enable SSH on stock firmware or supply rooting instructions.
- The automatic C300X factory login does **not** match the root password hash
  in the inspected stock C100X 1.5.8 image. After that login is refused, enter
  the device's actual SSH credentials in the installer. There is no verified
  C100X default password in this project. Credentials are not stored in the
  HA entry. An already installed agent can instead use its configured API and
  maintenance tokens; these are different credentials, not SSH passwords.
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
| Ringer mute | **Unavailable** | Requires a supported GUI hook. Advertised false; HA creates no mute switch. The native API rejects mute before device I/O. Volume/events are not disabled with it. |
| Device dashboard / display notify | **Unavailable** | Stock GUI is Qt5 `BtClass100`. No C100X patch or GUI restart is implemented. Setup/options omit display configuration; saved display preferences/layouts are retained but ineffective. Notify registration, patch apply and bridge setup are suppressed, including after an offline restart once support is known. Alarmo configuration remains available separately. |
| Camera / snapshot / RTSP | Implemented; hardware unproven | C100X is fixed to the low-resolution branch; no resolution selector. Stock settings describe 640x480, 12 fps and 800 kbps. Decoding, quality changes, snapshots, ring capture and multi-client behavior need device tests; these values are not a quality guarantee. |
| Listen / talkback | Implemented; hardware unproven | Stock configuration uses Speex/8000. SIP negotiation, SRTP/RTP, both directions, stop/teardown and codecs beyond the stock setting need a device. |
| Announcements / TTS | **Unavailable on inspected stock firmware** | Existing prerequisite checks disable this: `/bin/zl38005_ioctl-v2` and `/home/bticino/microsemi/MEMO_AM_PLAY.cr` are absent. Other Microsemi scripts are not interchangeable proof. No C100X substitute was implemented. |
| Memo / answering-machine features | **Unproven** | Generic capability paths exist and vendor binaries contain relevant functions, but file layout, recording, playback and service behavior have not been verified on C100X. Do not treat entity availability as confirmation of working recordings. No speculative implementation was added. |
| Install / authentication / update / uninstall | Offline guards and fixtures; hardware unproven | Actual credentials, service startup/reboot, runtime library loading, uninstall recovery and vendor operation afterward still require a device. Uninstall is not a factory reset or unroot operation. |

## Package Protection

This branch's generated `device_agent/bundle.json` declares
`"c100x_compatible": true`. The declaration participates in the generated
bundle hash; it expresses package compatibility, **not** proven hardware
features or a public release designation.

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

## Minimum Device Acceptance Plan

These steps require separate explicit authorization and have **not** been run:

1. Confirm SSH credentials and backup/recovery access. Record firmware/model,
   vendor app operation, SIP provisioning and original changed-file hashes.
2. Install the verified local package. Check startup, API/maintenance auth,
   discovery identity, HA entity set, reboot persistence and inactive saved
   display settings. Confirm no `BtClass100` patch/restart occurs.
3. Verify door/stair outputs, ring/call events, volume and vendor-app
   coexistence. Confirm mute, display and stock announcements remain absent.
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
