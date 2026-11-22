# C100X Issue #51: Complete Test Package

Status: local preparation, not a published beta or authorization to install.
Target: **C100X, original firmware 1.5.8**, branch `c100x_1.5.8`.
No release number has been selected. The current `2.8.2` metadata is inherited
development metadata, not a C100X release designation. Do not distribute an old
local ZIP merely because it has that version.

The download is a **complete HA integration ZIP**, including the freshly built
ARM agent, generated device bundle, all Lovelace card modules and documentation.
"Agent-only" describes the first hardware acceptance phase, not a reduced ZIP.
Unfinished GUI activation remains disabled even though adapter assets are included.

## What This First Test Covers

The first authorized device test should establish agent startup, authenticated
status/setup reads, model/firmware reporting, discovery, and continued vendor
operation. It is not a display, routing migration, camera or audio trial.

- The C100X-aware agent, installer and update guards are implemented offline.
  Routing restoration checks complete known firmware identity; GUI-free restore
  and uninstall recovery guards have temporary-copy regression tests.
- Additional display pages, physical-key navigation, silent/wake Notify and
  read-only text memos exist as offline implementations. **They are not activated.**
- Display pages, GUI restart, ringer mute and key tone remain unavailable through
  the supported C100X installation. Explicit GUI-install requests must fail
  before writing device files, not silently report a successful activation.
- Notify sound, speech/TTS, voice memos and memo mutations are not part of this
  test. No alternative sound script or forced capability flag is supported.
- Starting the agent is not permission to create a media user, patch routing,
  migrate Companion/MQTT, activate streams, change codecs or operate a door.

The issue #51 field report describes Companion installed and non-stock SIP
routes. SIP users come from official app provisioning; Companion's presence
does not establish that it created those users. Preserve accounts, credentials,
routes and existing Companion configuration. The four reported tool/service/hash
questions are cleared offline and are **not** outstanding prerequisites. Exact
GUI activation/readiness/recovery on the device remains unproven. See the
[field-report evidence](c100x-field-report.md).

## Package and Channel Isolation

| Boundary | Current protection and limitation |
| --- | --- |
| Local artifact name | Builder defaults to `ha-bticino-c100x-issue51-local.zip` and refuses the normal C300X asset name in this branch. |
| Device bundle | `c100x_compatible: true` and `c100x_only: true` participate in the bundle hash. Neither is a hardware-support or signature assertion. |
| HA update / SSH repair | This branch rejects the C100X-only package for C300X, including firmware 3.0.6, before upload/write. SSH installation requires a manifest, strict C100X declarations and matching agent hash; missing, invalid or relabelled metadata cannot relax the code-level C100X restriction. API updates also reject unknown model identity. |
| Native updater | The new updater rejects C100X-only bundles on a non-C100X device and rejects unmarked incompatible bundles on C100X. Older updaters cannot enforce a field they never implemented: use the reviewed HA preflight, never a raw old updater upload. |
| Legacy shell installer | Blocked in this checkout: its generic upload path has no C100X model preflight. Do not remove the policy file to enable it. |
| Public publication | `publish_release.py` refuses this checkout while `c100x-test-policy.json` exists. There is no bypass flag. The existing workflow additionally requires canonical-main validation evidence; this branch is not a working alternate release channel. |
| HA integration | Domain, discovery service and config-entry identity remain `bticino_c300x`. This package would replace the existing integration on the same HA instance. **Use a separate disposable HA test instance**, with no C300X stable or firmware-3.0.6 beta entries. Renaming the ZIP is not HA isolation. |

These guards prevent accidental use through this branch's supported paths, not
manual privileged overwrites or deliberately relabelled packages. They do not
retrofit guards into old C300X software. Do not use HACS to replace a production
integration for this test, or attach this ZIP to the stable/fw306 release.

### Download Delivery

The user uploads the verified ZIP directly as an attachment to **issue #51**.
The accompanying issue comment identifies the exact source commit, ZIP filename,
SHA256 and completed validation. There is no C100X tag, GitHub release, separate
repository or HACS channel. Do not use a stable-release download with the same
displayed version, GitHub's source-code archive, or an earlier issue attachment.

Before external delivery, the final frozen source must pass the full local gate,
browser checks and complete-package verification. Keep the public release block
intact. Download the attachment and compare its SHA256 with the maintainer's
comment, for example `sha256sum ha-bticino-c100x-issue51-local.zip` on Linux or
`Get-FileHash .\ha-bticino-c100x-issue51-local.zip -Algorithm SHA256` in PowerShell.
Do not continue on a mismatch. A checksum binds the delivered bytes; it does not
prove hardware compatibility or create an independent firmware update channel.

## Before Any Installation

1. The maintainer approves the exact commit, artifact SHA256, tester, device and first-test
   scope. Rebuild/verify from that commit; keep the matching source and recovery
   package. No installation follows automatically from producing a ZIP.
2. Confirm the device is C100X 1.5.8 and retain working privileged SSH/recovery
   access. Explicit credentials take priority; the original-firmware-verified
   factory default does not prove the device still uses it. Never put credentials,
   tokens, SIP secrets or complete configuration in an issue report.
3. Record the existing agent, startup entries, GUI/routing identities, vendor app
   operation and Companion configuration. Securely preserve exact pre-test files
   and metadata outside the device as well as on-device recovery data. Do not
   overwrite a non-stock route with a stock original to make a check pass.
4. Complete the private backup below, verify its contents and retain a working
   SSH session. On this Companion-modified device, generic uninstall is not
   equivalent to restoration of its pre-test state. Stop if the specified paths
   differ, are unexpected symlinks, or cannot be read.
5. Prepare the separate HA test instance with only this package. Check the
   displayed device/model and explicit host before accepting SSH installation.
   Existing production HA instances and their stable/beta packages stay untouched.

## Private Pre-Test Backup

These are **tester instructions**, not commands run by the maintainer on the
device. Execute them only for the explicitly authorized device while no call,
recording or installer is active. Replace `C100X_HOST` with its confirmed address.
Use the device's current SSH credentials and verify its host-key fingerprint;
never disable host-key checking or put a password in a command line.

On the tester's workstation, create a private directory (`umask 077` on Linux).
The following SSH operations only read device files; archive output goes to the
workstation. The archive contains credentials, user configuration and vendor
files. **Never attach it, its contents or raw device configuration to GitHub.**

```sh
umask 077
mkdir c100x-51-private
cd c100x-51-private
ssh root@C100X_HOST 'for p in \
  /home/bticino/cfg/extra/c300x-native-agent \
  /home/bticino/cfg/extra/c300x-device-file-backups \
  /etc/init.d/c300x-native-agent /etc/rc5.d/S40c300x-native-agent \
  /etc/network/if-pre-up.d/iptables /etc/network/if-pre-up.d/iptables6; do
    if [ -e "$p" ] || [ -L "$p" ]; then
      printf "present %s\n" "$p"
    else
      printf "absent %s\n" "$p"
    fi
  done' > presence.txt
```

Stop if SSH fails. Check `presence.txt`; keep both present and absent entries.
Then stream a metadata-preserving archive of the configuration, relevant startup/
firewall files and GUI/routing identity files:

```sh
ssh root@C100X_HOST 'set --
  for p in home/bticino/cfg \
    etc/init.d/c300x-native-agent etc/rc5.d/S40c300x-native-agent \
    etc/network/if-pre-up.d/iptables etc/network/if-pre-up.d/iptables6 \
    home/bticino/bin/gui/BtClass100 home/bticino/bin/BtClass100_qws \
    home/bticino/bin/gui/skins/default/main.qml \
    home/bticino/bin/gui/skins/default/MainPage.qml \
    home/bticino/bin/gui/skins/default/EventManager.qml \
    home/bticino/bin/bt_answering_machine; do
      if [ -e "/$p" ] || [ -L "/$p" ]; then set -- "$@" "$p"; fi
    done
  exec tar -C / -cpf - "$@"' > pretest.tar.partial
```

Only after a zero exit status rename `pretest.tar.partial` to `pretest.tar` on the
workstation. Run `tar -tvf pretest.tar` and `sha256sum pretest.tar`; record the hash
privately. Confirm that configuration, the GUI/routing identity files, and every
path marked present are represented with their expected modes/owners/link targets.
Do not install after a tar warning, read failure, incomplete archive or unexpected
layout. This live-file archive is not a disk image or a power-loss recovery method.

Record whether the agent was running (`pidof c300x-agent-native`: exit 0 means
present; exit 1 with no output means absent; errors are unknown), its previous
version if already known, and the current GUI/routing SHA256 values. Keep the
archive outside HA and outside the device. Preserve official-app and Companion
accounts unchanged; their presence is not permission to migrate them.

## Manual HA Installation

1. Use a separate disposable HA instance meeting the minimum in `hacs.json`.
   Create a full HA backup before the test. It must have no production C300X or
   fw306 beta entries. Do not install this ZIP through HACS or a custom repository.
2. Verify the issue attachment's SHA256. Inspect the ZIP: `manifest.json`,
   `__init__.py`, `frontend/`, `device_agent/armhf/c300x-agent-native` and
   `device_agent/bundle.json` must be at the ZIP root. This is not a standalone
   agent binary and not a source-code checkout.
3. Stop HA Core using the normal control for that test instance. Extract the
   **entire ZIP** into `/config/custom_components/bticino_c300x/`. It must yield
   `/config/custom_components/bticino_c300x/manifest.json`, not another nested
   `custom_components` or repository folder. If a previous test integration is
   present, move its entire directory outside `custom_components` first; do not
   overlay files from different builds. Retain the old directory for rollback.
4. Start HA Core. Check **Settings > System > Logs** for import/dependency errors.
   A stopped or failed HA startup does not authorize any device changes.
5. Under **Settings > Devices & services > Add integration**, search for
   **BTicino C300X** (the integration retains its existing name). Enter only the
   confirmed C100X host. Use SSH bootstrap only when offered and authorized.
   Explicit current SSH credentials take precedence over any factory default.
   Use a trusted isolated network: the legacy bootstrap SSH client currently does
   not pin host keys (`known_hosts=None`). The manual backup SSH connection above
   must still verify its host key; model/package guards are not host authentication.
6. Follow the first-test restrictions below. Do not enable display, MQTT migration,
   media-user setup or media features just to clear a Repair or populate a card.

## Lovelace Card Setup

The ZIP includes all current card ES modules; there is no separate npm build or
card download for the tester. HA registers the bundled resource automatically
after integration setup. The card picker currently calls it **C300X Doorbell Call
Card**, also on C100X. Its type remains `custom:c300x-doorbell-call-card`.

On the test dashboard select **Edit dashboard > Add card**. For the initial
agent-only phase, confirm registration but do not enable media merely to obtain
a camera entity. A missing/unavailable camera must leave media start buttons
disabled and must not request the microphone. GUI restart, device ringer mute,
key tone, Notify sound and TTS are not card features to enable in this test.

Only in a separately approved media phase, select the camera entity belonging to
the C100X test entry. A conservative card configuration is:

```yaml
type: custom:c300x-doorbell-call-card
entity: camera.REPLACE_WITH_C100X_TEST_CAMERA
mode: doorbell_call
ringback_tone: false
show_door_unlock: false
show_stair_light: false
show_media_history: false
```

Use the actual entity picker/name, not the placeholder. Do not press play, answer,
Home Call, door or light during the first acceptance phase. Hidden controls are
not an authorization boundary; the test plan and backend capability checks remain
necessary. Later media tests require their own authorization and hardware evidence.

For a missing/stale card, hard-reload the browser and inspect dashboard Resources
(advanced mode). Keep one JavaScript-module entry beginning
`/bticino_c300x/frontend/c300x-doorbell-call-card.js?v=`. The value is a content hash,
not the inherited integration version. Do not replace it with a stable/HACS URL or
maintain duplicate resources. YAML-managed resources need that same local URL
with `type: module`; obtain its exact current `?v=` value from this test instance's
registered resource or the package's validated handoff, not a guessed version.

## First Authorized Installation and Checks

The supported entry point is the reviewed package's HA SSH bootstrap, not the
blocked developer shell installer. Bootstrap writes agent payload/configuration,
startup integration and, by its current default, the firewall allowance; it
starts/restarts the **agent**, not the vendor GUI. Review these writes explicitly.
The C100X bootstrap must leave legacy MQTT/Companion migration untouched.

1. Install the approved package on the isolated HA test instance; authorize only
   the agreed C100X host. Leave GUI/display installation disabled.
2. After agent installation, pause at feature selection for the first inspection.
   Leave video/audio, display and media-user creation disabled. After confirming
   the host/model and unchanged vendor operation, finish setup with those features
   off; do not invoke device actions or MQTT migration. If setup or a Repair demands
   a routing/user change, stop instead of accepting it to complete the wizard.
3. Check authenticated setup/status, C100X/1.5.8 identity, discovery and available
   capabilities. Display/mute/key-tone/GUI-restart capabilities must remain false.
   An exposed unsupported toggle is a failed acceptance check, not an invitation
   to try it. No-auth access must remain disabled.
4. Compare GUI/routing/provisioned-account identities and Companion state with
   the pre-test record. Check normal physical keys and vendor app operation.
   A changed binary hash or missing account is a stop condition.
5. Observe agent uptime and errors while idle. Record the actual observation
   duration, not a generic stability claim. Reboot persistence, door actions,
   ring/media/audio and update/remove tests need separately agreed phases.

## Recovery and Stop Conditions

Stop on unexpected reboot, loss of vendor calls/app service, GUI changes,
authentication loss, non-stock identity refusal, or failed restoration. Do not
repeat a failing installation, force a capability, delete backups, restart the
entire vendor stack, or replace provisioned SIP accounts to recover.

Use the exact pre-test backup and recovery steps below.
Keep installation errors, hashes and recovery files. Report whether the agent
is stopped, still running, or unknown; a retained file is not process readiness.
Restoring files on disk does not unload QML or an executable already in memory.
No automatic GUI rollback or successful device recovery is claimed here.

Uninstall first verifies that the agent has stopped. After TERM it waits at most
ten one-second intervals; an unknown process state, failed signal without verified
exit, or timeout aborts before restoration or deletion. C100X display and routing
restoration still require their verified identities and recovery paths; unknown
modified files are not overwritten to force removal.

Startup recovery stays armed through final cleanup. If deletion fails, private
startup recovery files are retained and no reboot is scheduled. Startup entries
are restored only if the entire remaining agent tree still matches its pre-delete
identity, including content, modes, ownership and symlink targets. If the agent
tree is partial, changed or unverifiable, startup remains disabled; use the printed
recovery location to repair the installation before restoring startup or rebooting.
This does not recreate already deleted files. Keep the external pre-test backup.

Uninstall acceptance remains a separately authorized hardware phase with verified
routing backups. It cannot establish recovery of arbitrary Companion changes or
unload an already running GUI. Do not run uninstall on the issue #51 device as a
substitute for its pre-test backup.

### Concrete First-Test Rollback

This procedure restores only the paths changed by the agent-only installer. It
does not recover an unknown GUI restart, media/routing migration, app provisioning
change, power loss or inaccessible SSH. Stop and request assistance for those cases;
do not substitute stock firmware files for the device's own pre-test files.

1. Disable the C100X entry on the separate HA test instance and close its cards.
   Retain the failed installation's redacted logs and the private backup. Verify
   `pretest.tar` still has its recorded SHA256 before using it.
2. Through the already verified SSH session, stop only `c300x-agent-native`, not
   `bt_daemon`, the GUI, SIP server or Companion. If `pidof c300x-agent-native`
   reports it running, send `killall c300x-agent-native` (TERM), then check once
   per second for at most ten seconds. Proceed only after `pidof` returns exit 1
   with empty output and no error. If it remains running, signalling fails without
   a verified exit, or process state is unknown, stop recovery before changing files.
3. Transfer the private archive back to a private temporary location on this
   device, verify its SHA256 there, and keep SSH connected. Do not blindly extract
   the full archive over `/`: it contains official-app/Companion configuration.
4. Move the failed agent directory to a new private sibling name such as
   `c300x-native-agent.issue51-failed-TIMESTAMP`; do not delete it or the managed
   backup root. Reject unexpected symlinks and an already-existing destination.
   If the agent directory was present before the test, restore **only**
   `home/bticino/cfg/extra/c300x-native-agent` from the archive using metadata-
   preserving tar extraction. If it was absent, leave the original path absent.
   For example, after verifying the private archive at `/tmp/c100x-pretest.tar`,
   `tar -C / -xpf /tmp/c100x-pretest.tar home/bticino/cfg/extra/c300x-native-agent`
   restores that one archived tree. Never add the whole `home/bticino/cfg` tree
   to this command; official-app/Companion state must not be rolled back wholesale.
5. Restore the four startup/firewall paths in the table below. Remount `/` writable
   only for these writes and return it read-only afterwards; a failed remount is a
   stop condition, not permission to reboot. For paths recorded present, extract
   the exact archived entry, preserving owner, permissions and symlink target.
   For paths recorded absent, remove only that newly created file/link, never its
   parent directory. Do not restore startup until the old agent tree is complete.
   The root remount commands are `mount -o remount,rw /` and
   `mount -o remount,ro /`. Extract each present entry by its relative archive path,
   for example `tar -C / -xpf /tmp/c100x-pretest.tar etc/init.d/c300x-native-agent`.
   Inspect an existing destination first; never extract through an unexpected
   symlink. A file recorded absent can be removed with `rm -f` on that exact path
   only after confirming it is the test-created file/link, not a directory.

| Managed path | Pre-test present | Pre-test absent |
| --- | --- | --- |
| `/etc/init.d/c300x-native-agent` | Restore archived file and executable mode. | Remove only the test-created file. |
| `/etc/rc5.d/S40c300x-native-agent` | Restore archived link/file exactly. | Remove only the test-created link/file. |
| `/etc/network/if-pre-up.d/iptables` | Restore archived content, owner and mode. | Remove only the test-created file. |
| `/etc/network/if-pre-up.d/iptables6` | Restore archived content, owner and mode. | Remove only the test-created file. |

6. Compare restored files against the private archive, including modes/ownership
   and link targets; verify GUI/routing hashes still equal the pre-test record.
   Leave new backup/recovery material intact. If any comparison fails, leave the
   agent stopped and startup disabled; do not reboot or retry installation.
7. Start the restored agent via its restored init script only if it was running
   before the test and the original tree/startup have been verified. If no agent
   existed before the test, leave it absent and stopped. No automatic reboot is
   part of this rollback. Check the vendor menus/app locally without operating a
   door or starting media outside the agreed acceptance phase.
8. To undo HA-side installation, stop HA Core, move this test integration directory
   out of `custom_components`, and restore the previous directory or HA backup.
   Restore/remove only this test instance's card/resource as appropriate, restart
   HA and reload the browser. HA rollback does not undo device writes.

Keep the failed agent directory, archive and recovery materials until recovery is
confirmed. If SSH is lost or these paths differ from the captured layout, there is
no claimed automatic recovery; this is a reason to stop before the first install.

### Diagnostics for Issue #51

Report the attachment filename, SHA256, source commit, HA version, agent version,
reported model/firmware, observation duration and exact step that failed. Include
the integration's **Download diagnostics** output only after reviewing/redacting
identifiers, addresses and any sensitive fields. Add short redacted HA log excerpts,
capability flags, whether the agent is stopped/running/unknown, and whether GUI/
routing hashes stayed unchanged. For card problems include browser/version,
resource URL/hash, screenshot and console error with private details removed.
Never upload the private tar archive, config files, tokens, passwords, SIP accounts
or complete routing configuration. Do not retry or force unsupported controls.

## Evidence and Remaining Work

Existing offline evidence includes exact original-firmware routing checks,
temporary-copy display upgrades/recovery, old-reader bundle delivery, host key/
layout tests and compilation of 29 generated QML files using original Qt 5.10.1
under QEMU. Compilation does not instantiate vendor QML or validate hardware.
See [experimental support](c100x-experimental.md) and the
[page/control matrix](c100x-display-parity.md) for commands and scope.

Before issue attachment delivery: complete the exact-source review, full local
gate, browser tests and fresh complete-package/build-lock verification. This full
gate is now explicitly authorized; earlier preparation used focused checks only.
It does not create canonical-main release evidence. Before display trials: establish isolated call-safe GUI supervision,
failed-start readiness and runtime rollback, then test them on authorized hardware.
Those are real remaining gaps; this agent-only test does not complete page parity.

The tester report should contain commit, artifact SHA256, agent/model/firmware,
test steps and outcomes, observation duration, capability flags, recovery result,
and redacted errors. Never include credentials, tokens or private SIP routes.

### Local Preparation Checks

The preparation ran focused groups, not a full suite:

- 150 tests for package/model isolation, legacy delivery, publication and package
  contracts. Native update fixtures use temporary paths and synthetic system calls.
- 238 tests for bootstrap/identity, factory login, display gating and translations.
  The existing separate Alarmo option remains available even with display disabled.
- 278 tests for removal, routing identity and shutdown regression after the safety
  port. These include original C100X BusyBox under QEMU, actual native restoration
  on temporary firmware copies, installed-adapter failure recovery, bounded stop
  and partial cleanup, plus host/ASan/UBSan shutdown tests. System operations are
  mocked; firmware originals are read-only. This is not device recovery evidence.
- 83 tests for the refreshed build lock, compact bundle delivery/old-reader
  bootstrap and C100X-only test-package isolation. The rebuilt manifest is
  6,532 bytes with 29 entries, below the old 8,192-byte reader limit. Old updaters
  still lack the new model guard; these delivery tests do not remove that limit.
- The SSH admission follow-up passed 199 focused installer/package tests and six
  display-kind helper tests. Real staged metadata is tested with missing,
  truncated, invalid and relabelled manifests; rejected targets perform no device
  writes or service start/stop. Missing packaged metadata aborts before SSH.

The ARM rebuild passes the 24,576-byte stack limit (maximum 24,200 bytes) and
ABI checks against original 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8 sysroots.
These results do not establish GUI startup or device readiness. No generated QML
changed in this preparation; the earlier original-Qt compile evidence is not
represented as a new hardware or compile run.

Reproduce the local artifact after reviewing the final build lock:

```sh
PY=../ha-bticino-c300x/.venv/bin/python
"$PY" scripts/build_hacs_release.py --skip-build
"$PY" scripts/check_release_contents.py .release/ha-bticino-c100x-issue51-local.zip \
  --agent-binary native_agent/build/armhf/c300x-agent-native \
  --build-lock native_agent/build-lock.json
"$PY" scripts/native_build_lock.py --zip .release/ha-bticino-c100x-issue51-local.zip
sha256sum .release/ha-bticino-c100x-issue51-local.zip
```

The ZIP includes this checklist and the linked C100X support/evidence documents.
It is a **local test candidate**, not an approved release or install request.
