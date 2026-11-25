# C100X Issue #51: Complete Test Package

Status: test package for the current round in issue #51, not a release or a
published beta.
Target: **C100X, original firmware 1.5.8**, branch `c100x_1.5.8`.
No release number has been selected. The current `2.9.2` metadata is inherited
development metadata, not a C100X release designation. Do not distribute an old
local ZIP merely because it has that version.

The branch includes the stable release `2.9.2` completely, plus the fixes made
after it that have no release of their own yet. The shared code and the C300X
display pages are those of that state; the changes of 2.9.2 are listed in the
[changelog](../CHANGELOG.md). This guide and the C100X notes list only what the
branch adds for the C100X.

The download is a **complete HA integration ZIP**, including the freshly built
ARM agent, generated device bundle, all Lovelace card modules and documentation.
The functional test scope is agent setup, the two HA buttons below, one video
stream and one ring call, and the
[display activation by reboot](#display-activation-by-reboot-device-test).
The display pages become active only through that supervised activation; no
other GUI install path is enabled.
The selected test-package scope excludes local speaker/TTS. Investigation of
a safe audio backend continues separately; no unsupported audio path is enabled.

## Test Plan at a Glance

Run the steps in order, after the [private pre-test backup](#private-pre-test-backup)
and the [manual installation](#manual-ha-installation). Each step links to its
detailed checks. Stop at the first failure and follow the
[stop conditions and rollback](#recovery-and-stop-conditions).

| # | Do | Expected |
|---|---|---|
| 1 | Add **BTicino C300X** with the C100X host ([details](#first-authorized-installation-and-checks)) | Setup completes without a workaround; model C100X, firmware 1.5.8 |
| 2 | Press **Stair light** once | The light comes on |
| 3 | Press **Door unlock** once, with an authorized person at the door | The door releases |
| 4 | Start the live stream on the card | Picture and sound; the stream ends cleanly |
| 5 | Ring at the outdoor station and answer in HA | Picture, two-way audio, hang-up works |
| 6 | Move brightness, contrast and saturation on the card | The picture changes; a new stream shows the station's own values again |
| 7 | Enable Maintenance with reboot, press **Activate display pages** ([details](#display-activation-by-reboot-device-test)) | One reboot after two minutes idle, then **Home Assistant** and **Alarmo** follow the ringtone item in the station's main menu ([what to check](#display-pages-what-to-check)) |
| 8 | Press **Restore original display** | One reboot, stock display back |
| 9 | Optional: repeat step 7 and pull the power within 60 s after the reboot | Stock display back, repair message in HA, no further reboot |

### Display pages: what to check

After step 7, with the station's keys only (Up, Down, Return):

1. Main menu: Ringtone, then **Home Assistant**, then **Alarmo**, then the
   station's own items in their usual order. Without a dashboard or without
   Alarmo the matching item is missing.
2. **Home Assistant** opens the dashboard. Up and Down change the page, the
   dots follow, the last entry is **EXIT**; Return on EXIT returns to the menu.
3. Return on a page with controls selects its first control (white bar). Down
   walks through all of them and the page scrolls along; arrows show more
   content above or below. Past the last control the page title is marked again.
4. A light tile opens its detail page on the switch. Select the brightness,
   press Return, change it with Up or Down, press Return: the light follows.
5. **Alarmo** opens the Alarmo page (blue, titled Alarmo). With a PIN the keypad
   follows the modes.
6. Send a display notification without sound: it covers the whole screen and
   Return marks it read. Afterwards Up, Down and Return work again. Also send
   one and, while it shows, ring the station: the call menu reacts to Up, Down
   and Return, and after the call the main menu does too. The same after a
   notification on the Home Assistant page that was still open when the screen
   went off.
7. Settings: **Status messages** stands before EXIT; Return switches it on and
   off, and the routine confirmations on our pages follow.
8. A door call during any of these pages shows the call as usual.

Report what differs, with a photo of the screen.

Stop on an unexpected reboot, if a vendor call, the BTicino app or a physical
key stops working, or if setup fails. Report **pass / fail / not tested** per
step with firmware and HA version, as described in
[Diagnostics for Issue #51](#diagnostics-for-issue-51).

## What This First Test Covers

The first authorized device test should establish agent startup, authenticated
status/setup reads, model/firmware reporting, discovery, and continued vendor
operation, plus one on-demand video stream and one ring call (video is on after
bootstrap, as on a C300X). As on a C300X, the first HA start after setup creates
the HA media user in Flexisip and patches the routing binary
`bt_answering_machine`; [step 2](#first-authorized-installation-and-checks)
lists what changes. Display pages have their own
[activation phase](#display-activation-by-reboot-device-test). It is not an
audio trial.

**Test baseline:** use C100X firmware 1.5.8 in its normal manufacturer
configuration, with at most the changes needed to obtain root/SSH access.
Normal vendor-app provisioning is part of that baseline. Companion, another
third-party controller or custom SIP/media/display changes make results
unsuitable for acceptance. Parallel operation with Companion is not
supported. Do not reset or dismantle a working station to participate.

**First functional checks:** on the C100X device page in HA, press **Stair
light** once and verify that the intended light switches on. For **Door
unlock**, have an authorized person at the intended door; press the
corresponding button once and verify the physical release. If the target is
unknown, skip the action. Report each result separately; an accepted HA
service call is not proof that the output operated. Neither action uses the
camera, the HA media user or the routing change.

The C100X firmware codec is stock Speex/8000; HA and the browser still get
PCMU through the agent's transcode. Firmware PCMU is unsupported on the
C100X: the station runs its device-side PCM at 16 kHz, its PCMU send pipeline
has no resampler and the RTP PCMU payloader accepts only 8000 Hz, while the
audio DSP clocks all its profiles at 16 kHz, so 8000 Hz would play at the
wrong speed ([details](dev/c100x-audio-analysis.md)). Firmware-PCMU apply is
therefore blocked at the native core, API and CLI; HA does not offer the
firmware codec selector.
Read-only codec status remains available. Explicit restore and removal retain
Speex recovery only when both managed backups pass stock-Speex field validation;
missing, partial or incompatible recovery backups are refused. Unpatched removal
with neither codec backup remains a no-op. Recovery is not a first-test action.
The agent's PCMU transcode for HA is separate from the firmware codec setting.

- The C100X-aware agent, installer and update guards are implemented offline.
  Routing restoration checks complete known firmware identity; GUI-free restore
  and uninstall recovery guards have temporary-copy regression tests.
- Additional display pages, physical-key navigation and silent/wake Notify
  exist as offline implementations; text memos are not offered on a C100X. **They stay inactive
  until the display activation below.**
- GUI restart remains unavailable; HA shows no Display reload button. Display
  pages, ringer mute and key tone stay unavailable until the separate
  [display activation](#display-activation-by-reboot-device-test) is confirmed
  in its trial boot. The C300X Display patch is refused before it writes device
  files.
- Notify sound, speech/TTS, the answering machine, voice memos and memo
  deletion are not part of this test; the C100X has no answering machine (see
  [Models and Features](feature-reference.md#models-and-features)). No alternative sound script or forced capability flag is supported.
  The [audio investigation](dev/c100x-audio-analysis.md) establishes concrete vendor
  playback/ownership hazards. Integrated safety guards block incompatible
  playback and startup cleanup; they do not add a local speaker/TTS backend.
- With video on, HA creates its media user and patches routing on its first
  start, as on a C300X; that is part of this test. MQTT/Companion migration,
  codec changes and door or light actions outside the agreed checks are not.

The issue #51 field report describes Companion installed and non-stock SIP
routes. SIP users come from manufacturer app provisioning; Companion's presence
does not establish that it created those users. The media-user setup only adds
its own lines and keeps every existing account and credential. It refuses a
`route.conf` that is a regular file or links anywhere but `route_int.conf` or
`route_ext.conf` (`unsupported_active_route`) and then writes nothing. The four reported tool/service/hash
questions are cleared offline and are **not** outstanding prerequisites. Exact
GUI activation/readiness/recovery on the device remains unproven. See the
[field-report evidence](dev/c100x-field-report.md).

## Package and Channel Isolation

| Boundary | Current protection and limitation |
| --- | --- |
| Package | One package serves the C300X and the C100X; it has the normal asset name. |
| Device bundle | `c100x_compatible: true` participates in the bundle hash. It is no hardware-support or signature assertion. |
| Setup | A C100X is recognised from the station itself (`webserver_type`, checked against the installed programs). Nothing is installed until the user confirms the experimental support in the setup dialog. A station whose two sources disagree is refused. A C300X is never asked. |
| HA update / SSH repair | A C100X takes only a package with a manifest, the `c100x_compatible` declaration and a matching agent hash, checked before any upload or write. API updates also reject unknown model identity. |
| Native updater | The updater rejects a package without the declaration on a C100X, and a package that names itself C100X-only on a C300X. Older updaters cannot enforce a field they never implemented: use the HA preflight, never a raw old updater upload. |
| Legacy shell installer | Serves the C300X only; it refuses a C100X before the first write. |
| HA integration | Domain and config-entry identity remain `bticino_c300x`; a C100X agent announces its own discovery service `_bticino-c100x-agent._tcp`. This package would replace the existing integration on the same HA instance. **Use a separate disposable HA test instance**, with no C300X stable or firmware-3.0.6 beta entries. Renaming the ZIP is not HA isolation. |

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

Keep the exact commit and **final ZIP SHA256 in an external issue comment or
handoff file**, not inside this ZIP. Inserting the ZIP's own hash would change it.
Use this external record after freezing the source and completing validation:

```text
Source: <full final commit ID on c100x_1.5.8>
Attachment: ha-bticino-c100x-issue51-local.zip
SHA256: <all 64 hexadecimal digits of the final ZIP>
C100X full gate: <result, date, command and retained log reference>
Browser/package/build-lock checks: <results for this candidate>
Scope: otherwise stock C100X 1.5.8, agent + stair light + door unlock + display activation by reboot + one video stream and one ring call; no other GUI change
```

Redact private paths from public log excerpts. Any later source or archive change
requires a newly bound candidate and corresponding validation. The remote
`c100x_1.5.8` branch is for source visibility, not a substitute for that attachment.

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
   agreed device identity and explicit host before accepting SSH installation.
   With no agent installed, HA may not yet know the model; the installer must
   independently pass its SSH identity check before writing.
   Existing production HA instances and their stable/beta packages stay untouched.

### Installer Write Set and Preconditions

These instructions assume default paths and API port 8091. Custom directories,
startup environment overrides or ports require a separately checked inventory.
Record present/absent state, file type, numeric mode/UID/GID, bytes and literal
symlink targets. Do not dereference links while recording their identity.

| Write surface | Default bootstrap behavior |
| --- | --- |
| `/home/bticino/cfg/extra/c300x-native-agent/` | Writes the executable, generated QML assets, helper scripts, `bundle.json`, `config.json` and `c300x-agent.env`; may remove obsolete generated source. The whole previous tree is recovery material. |
| `/etc/init.d/c300x-native-agent` | Replaces the rendered init script, mode 0700. |
| `/etc/rc5.d/S40c300x-native-agent` | Creates/replaces the link to `/etc/init.d/c300x-native-agent`. Record a pre-existing link's literal target, not only its referent. |
| `/etc/network/if-pre-up.d/iptables` | If present, adds/replaces the managed IPv4 block and retains file metadata. If absent, remains absent. |
| `/home/bticino/cfg/extra/c300x-device-file-backups/` | May gain `original/etc/network/if-pre-up.d/iptables` and parent directories. A new managed firewall backup is mode 0600 and omits managed blocks; it is **not** the exact pre-test firewall snapshot. Preserve any older recovery data. |
| Live IPv4 INPUT rules | With the vendor hook present, a fresh C100X install adds, as on a C300X, the configured API port (default TCP 8091), the RTSP port (default TCP 6554) and talkback (UDP 40004). A reinstall that keeps an explicit `video.enabled: false` adds only the API port. Without the hook, HA leaves the live rules alone. |
| Agent runtime | Restarts only the native agent, writes/removes its PID file in its directory; completing HA setup can save callback configuration there. |
| Staging | Uploads use `.new`; init uses `.c300x-native-agent-init.new` and `/etc/init.d/c300x-native-agent.new`. Firewall staging uses unique sibling files and `/tmp/c300x-firewall*` files. Inspect unexpected leftovers; never wildcard-delete them. |

The bootstrap does not write the IPv6 firewall, the vendor GUI, the routing
binary, SIP accounts or Companion. The first HA start afterwards, not the
bootstrap, adds the HA media user and patches the routing binary
([step 2](#first-authorized-installation-and-checks)). The snapshots are
comparison/recovery evidence, not permission to overwrite them during rollback.
The original C100X 1.5.8 firewall
paths above and `/etc/network/if-pre-up.d/iptables6` are regular files with mode
0100 in the extracted image; preserve the actual device's recorded metadata,
not a guessed 0755 mode.

Stop before bootstrap if an existing init entry belongs to another service,
writable targets/ancestors have unexpected symlinks, or the existing installation
cannot be identified. Also require
`/home/bticino/cfg/extra/c300x-device-file-backups/c100x-display/pending` to be
absent, including a dangling symlink. Init can run pending GUI recovery on agent
start, so such a marker is incompatible with this GUI-free first test. If that
check fails, the agent starts anyway with display activation off and records the
reason in `boot-check-failed` in the same directory; Home Assistant shows it as a
repair.

## Private Pre-Test Backup

These are **tester instructions**, not commands run by the maintainer on the
device. Execute them only for the explicitly authorized device while no call,
recording or installer is active. Replace `C100X_HOST` with its confirmed address.
Use the device's current SSH credentials and verify its host-key fingerprint;
never disable host-key checking or put a password in a command line.

Before capturing mutable agent configuration, record its running/stopped state
and have the maintainer stop only the old native agent with the bounded TERM
procedure in the rollback section. Do not stop vendor services or Companion.
If that cannot be verified, do not bootstrap. A live vendor configuration archive
is not a transactionally consistent snapshot of all vendor services.

**Original-firmware path evidence:** `/etc/flexisip` is a symlink to
`/home/bticino/cfg/extra/90/flexisip`. That persistent directory is absent from the
extracted original image; this does not prove anything about the live device's
users. `home/bticino/cfg` includes its contents only when the device still uses
that layout and there are no unarchived symlink targets. The archive below also
captures the `/etc/flexisip` link itself, without `-h`/dereferencing.

Before archiving, record `readlink /etc/flexisip` and inspect symlinks beneath
`/home/bticino/cfg` (`find /home/bticino/cfg -type l -print` is read-only).
For the reported provisioned device, verify that the resolved Flexisip tree is
readable and that its actual users/routes are included. Relevant paths include
`users/users.db.txt`, `users/accounts.txt`, `users/route.conf`,
`users/route_int.conf`, `users/route_ext.conf` and `domain-registration.conf` when
present. Preserve absent files as absent; never manufacture accounts from stock.
If a link resolves outside the captured tree, or its target is missing/unreadable,
stop and agree an expanded private backup before installing. Do not follow links
blindly. This is **not a complete Companion backup claim**: its executable,
startup/configuration/state locations must be inventoried separately on the
actual installation. First-test code must leave them unchanged.

On the tester's workstation, create a private directory (`umask 077` on Linux).
The following SSH operations only read device files; archive output goes to the
workstation. The archive contains credentials, user configuration and vendor
files. **Never attach it, its contents or raw device configuration to GitHub.**

```sh
umask 077
mkdir c100x-51-private
cd c100x-51-private
ssh root@C100X_HOST 'set -e
  for p in \
  /home/bticino/cfg/extra/c300x-native-agent \
  /home/bticino/cfg/extra/c300x-device-file-backups \
  /etc/init.d/c300x-native-agent /etc/rc5.d/S40c300x-native-agent \
  /etc/network/if-pre-up.d/iptables /etc/network/if-pre-up.d/iptables6 \
  /etc/flexisip; do
    if [ -e "$p" ] || [ -L "$p" ]; then
      printf "present %s\n" "$p"
      stat -c "metadata %a %u %g %h %F %n" "$p"
      if [ -L "$p" ]; then readlink "$p"; fi
    else
      printf "absent %s\n" "$p"
    fi
  done' > presence.txt
```

Stop if SSH fails. Check `presence.txt`; keep both present and absent entries.
Verify ancestor directories are readable/searchable before accepting absence;
permission errors must not be interpreted as a missing file.
Then stream a metadata-preserving archive of the configuration, relevant startup/
firewall files and GUI/routing identity files:

```sh
ssh root@C100X_HOST 'set --
  for p in home/bticino/cfg \
    etc/init.d/c300x-native-agent etc/rc5.d/S40c300x-native-agent \
    etc/network/if-pre-up.d/iptables etc/network/if-pre-up.d/iptables6 \
    etc/flexisip \
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

Capture the current IPv4 rules separately, before any installer invocation:

```sh
ssh root@C100X_HOST '/usr/sbin/iptables-save' > iptables-before.partial
```

Only after a zero exit status retain it as `iptables-before.txt`. The original
firmware provides `/usr/sbin/iptables-save`; if the live tool is unavailable,
stop rather than omitting this check. Keep this dump private. Repeat after the
authorized bootstrap as `iptables-after.txt` and compare exact rules; counters
alone can change naturally. Do not run `iptables-restore` or flush chains as a
generic rollback shortcut.

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
   **entire ZIP** into `/config/custom_components/bticino_c300x/`. For Container/Core,
   substitute the actual configured/mounted HA configuration directory for `/config`.
   It must yield
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
   The package refuses a Classe 300X: the SSH bootstrap stops before any write,
   and a station that already runs a C300X agent ends setup with "This test
   package is for the Classe 100X only".
6. Follow the first-test steps below. Video and the HA media user stay at their
   ticked defaults. The display settings appear only after the
   [display activation](#display-activation-by-reboot-device-test).

## Lovelace Card Setup

The ZIP includes all current card ES modules; there is no separate npm build or
card download for the tester. HA registers the bundled resource automatically
after integration setup. The card picker calls it **BTicino Doorbell Call
Card**; on a C100X its default title names the C100X. Its type remains `custom:c300x-doorbell-call-card`.

For a dashboard with just the first two actions, use Home Assistant's built-in
Entities card and select the stair-light and door-unlock buttons from this
C100X. Do not substitute a similarly named button from another entry.

On the test dashboard select **Edit dashboard > Add card**. Video is on after
setup, so the C100X camera entity exists. A missing/unavailable camera must leave media start buttons
disabled and must not request the microphone. GUI restart, Notify sound and TTS
are not card features to enable in this test; device ringer mute and key tone only
after the display activation below.

For an optional rendering-only check, first verify that
`camera.c100x_issue51_not_connected` does **not** exist in Developer Tools > States.
Add a Manual card with this intentionally unbound configuration on the isolated
test instance, with no notification-answer query parameter in the dashboard URL:

```yaml
type: custom:c300x-doorbell-call-card
entity: camera.c100x_issue51_not_connected
mode: doorbell_call
ringback_tone: false
show_door_unlock: false
show_stair_light: false
show_media_history: false
```

The unavailable-camera state is expected. Confirm the card loads and media-start
controls are disabled; no microphone request or device command is acceptable.
Do not replace the missing entity with a different device's camera. This checks
asset loading/inert UI only, not video, calls, device readiness or C100X GUI support.

For the video step of the agent-only test, select the camera entity belonging to
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
or Home Call during setup. Test door and light separately using the HA buttons
on the device page as described above. Hidden card controls are
not an authorization boundary; the test plan and backend capability checks remain
necessary. The video stream and the ring call are
[step 6](#first-authorized-installation-and-checks) below.

For a missing/stale card, hard-reload the browser and inspect dashboard Resources
(advanced mode). Keep one JavaScript-module entry beginning
`/bticino_c300x/frontend/c300x-doorbell-call-card.js?v=`. The value is a content hash,
not the inherited integration version. Do not replace it with a stable/HACS URL or
maintain duplicate resources. YAML-managed resources need that same local URL
with `type: module`; obtain its exact current `?v=` value from this test instance's
registered resource or the package's validated handoff, not a guessed version.

## First Authorized Installation and Checks

If the vendor IPv4 firewall hook is absent, bootstrap continues without
creating a hook, reading or restoring a backup, or changing live rules.
IPv4 firewall management by the agent is disabled in that configuration.
Existing network policy must already permit HA to reach the authenticated API;
skipping the hook does not guarantee connectivity. Do not create a placeholder.
A symlink in the hook path, a non-executable or unreadable hook, or an
inaccessible directory stops setup before writes. Do not change permissions
on a disabled vendor hook to make it pass.

The supported entry point is the reviewed package's HA SSH bootstrap, not the
blocked developer shell installer. Bootstrap writes agent payload/configuration,
startup integration and, by its current default, the firewall allowance; it
starts/restarts the **agent**, not the vendor GUI. Review these writes explicitly.
The C100X bootstrap must leave legacy MQTT/Companion migration untouched.

A fresh C100X agent configuration has video on, as on a C300X. A reinstall
preserves an explicit agent video setting. Bootstrap uses the merged agent
configuration for both its persistent IPv4 block and its live rule additions;
it does not remove previously open live ports. The HA feature form presets
video/media and the HA media user exactly as on a C300X: both are ticked, and
the user can untick them. Options and reconfiguration keep a saved media-user
choice while video stays on; switching video on from off ticks the media user
again, as on a C300X.

1. Install the approved package on the isolated HA test instance; authorize only
   the agreed C100X host. Leave GUI/display installation disabled.
2. After agent installation, pause at feature selection for the first inspection.
   Video/media and the HA media user are ticked by default, as on a C300X; keep
   them ticked and leave display installation disabled. After confirming the
   host/model and unchanged vendor operation, finish setup; do not invoke device
   actions or MQTT migration. The first HA start then sets up the media user,
   as on a C300X. Expect exactly these device changes:
   - `/home/bticino/bin/bt_answering_machine` changes from the stock 1.5.8 hash
     `cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12` to the
     patched `86caa9773895063b44e680e2508c7a9fb5579b89e2a484180d4c6a3536afa6b3`
     (computed offline from the stock file). The stock copy is kept under
     `/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin/`.
   - In the Flexisip `users/` directory, `users.db.txt` gains one
     `homeassistant-…` line, `accounts.txt` its label line, and the
     `alluser` route in `route_int.conf` gains that user as one more target
     (`route_ext.conf` never has it). Every existing account and target stays.

   Afterwards record `GET /api/v1/device-user`: `homeassistant_user_present`,
   `routes_consistent` and `device_routing_applied` true,
   `device_routing_state` `patched`, `device_routing_backup_present` true, no
   `error`. The **Home Assistant media user** switch is on. `unsupported_active_route`
   means a non-stock `route.conf` (for example Companion's): nothing was
   written and video/calls cannot be tested on that station; report it.
3. Check authenticated setup/status, C100X/1.5.8 identity, discovery and available
   capabilities. Display/mute/key-tone/GUI-restart capabilities must remain false
   until the display activation phase.
   An exposed unsupported toggle is a failed acceptance check, not an invitation
   to try it. No-auth access must remain disabled.
4. Compare GUI/routing/provisioned-account identities with
   the pre-test record. Check normal physical keys and vendor app operation.
   Stop on any of these: a GUI file (`BtClass100`, `BtClass100_qws`, the QML
   files) changed; `bt_answering_machine` has neither of the two hashes from
   step 2, or its stock copy is missing; a provisioned account from the
   pre-test record is missing or changed, or a route lost a target it had;
   any Flexisip change beyond those in step 2; the vendor app no longer
   rings or connects; a physical key stopped working.
5. Observe agent uptime and errors while idle. Record the actual observation
   duration, not a generic stability claim. Update and removal tests need a
   separately agreed phase; the display activation below reboots the station.
   After any reboot, download the HA diagnostics once the station is
   back: `agent_init_link_ok: true` and a small `agent_started_after_boot_seconds`
   (the boot link starts the agent early) show that it came up with that boot.
   A value close to the station's uptime means a later manual start, not
   reboot persistence; `uptime_seconds` far below it means it restarted since.
   **Discovery:** with the HA mDNS switch of the agent on and HA not yet
   connected, `avahi-browse -rt _bticino-c100x-agent._tcp` (or HA's discovered
   devices) shows the station with TXT `model=C100X` and its `id`, and
   `avahi-browse -rt _bticino-c300x-agent._tcp` does not list it. If a C300X is
   on the same network, its entry must not change when the C100X announces.
6. **Video.** Video is on after bootstrap. Start one on-demand stream from the HA
   card and check picture and sound; then ring from the outdoor station and
   answer the call in HA. Report both separately, with the agent diagnostics.
7. **Picture controls.** During on-demand video, open the picture panel (the
   sliders icon appears about two seconds after the picture). Move brightness,
   contrast and saturation one at a time and check that the picture changes
   each time. End the video and start a new one: the panel must show the
   station's own values again, not the ones you set.

## Optional Read-Only Audio Probe

Optional, and only after the base tests above. It prepares station-speaker
announcements, which are **not in this build**. The commands only read; they
change nothing on the station. Run them over SSH as root twice: once while the
station is idle, and once while a ringtone preview plays from the station's own
menu. Paste both outputs back in one block, each marked idle or preview.

```sh
grep Revision /proc/cpuinfo
ls -l /var/tmp/ringtones/
amixer cget name='Audio_State'
ls -l /var/tmp/audlock 2>&1
ls -l /proc/$(pidof bt_av_media)/fd 2>&1 | grep -i -e snd -e wav
sha256sum /home/bticino/bin/bt_av_media /home/bticino/bin/bt_answering_machine /usr/local/bin/Audio_State.sh /home/bticino/lib/liblghal.so.0.0
```

`/var/tmp/audlock` exists only while the vendor audio switch runs, so "No such
file or directory" is a normal result.

## Display Activation by Reboot (device test)

Only after the agent-only test above passed, and only with Maintenance and its
reboot enabled. Every step reboots the station at most once, and only after it
has been idle for two minutes; do not ring or call meanwhile unless a step says
so.

1. **Baseline.** Record `cat /proc/sys/kernel/random/boot_id`, the GUI hashes,
   `ls -l /home/bticino/cfg/extra/c300x-device-file-backups/c100x-display` and `GET /api/v1/maintenance/c100x-display`: `phase` `stock`,
   `confirmed` false, `activate` true.
2. **Activation.** Press **Activate display pages** in HA. Expect `phase`
   `prepared`, `reboot_blocked` `waiting_for_idle`, then one reboot about two
   minutes later. After the boot: a new boot id, `pending.trial-boot` holding it,
   the agent running, and within a minute `phase` `installed`, `confirmed` true,
   `last_result` `confirmed`. HA reloads, the device-UI setting is on and the
   additional pages open from the menu. A call during the wait must postpone the
   reboot (`call_active`/`call_recent`) and never interrupt the call.
3. **Power pull in the trial boot.** Repeat step 2 from a restored station, but
   pull the power within 60 seconds after the trial boot started (before
   `confirmed`). After power returns: the start rolls back, `phase` `stock`,
   `last_result` `rolled_back`, original GUI hashes, the repair "C100X display
   pages were rolled back" in HA, and no further reboot.
4. **Restore.** With confirmed pages, press **Restore original display** (or
   turn the device-UI setting off). Expect `confirmed` false at once,
   `reboot_pending` true, one reboot once idle, and afterwards the original display with
   the original hashes and `phase` `stock`.
5. **Ringer mute, after step 2** (analysis steps 2, 4, 5):
   - Stock path: on the device press Down to mute, then Up to unmute. Each time
     check `[Answering Machine] RingEnable` in
     `/home/bticino/cfg/extra/47/aswm_settings.ini`, `GET /api/v1/ringer`, the
     tile icon and an actual ring.
   - HA mute on/off three times; each time the icon, the ini value, GET, a ring
     and the HA state must agree.
   - Toggle on the device: the HA state follows. Reboot while muted: the icon is
     muted after the boot.
   - An HA command during a call is refused and causes no later change.
   - Unmute from outside the GUI (vendor app): the GUI icon follows within a few
     seconds, and a following HA mute works.
6. Afterwards the ini value, the GUI icon and HA agree.

## Recovery and Stop Conditions

Stop on an unexpected reboot (the display activation's own reboots are
expected), loss of vendor calls/app service, GUI changes outside the display
activation, authentication loss, non-stock identity refusal, or failed restoration. Do not
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

This procedure restores only the paths changed by the agent-only installer. If
the display pages were activated, press **Restore original display** first and
wait for its reboot and `phase` `stock`. Undo
the media-user setup next, while the agent still runs: turning the **Home
Assistant media user** switch off restores the stock routing binary from its
backup; the Flexisip user lines stay. The procedure does not recover an unknown
GUI restart, app provisioning change, power loss or inaccessible SSH. Stop and
request assistance for those cases; do not substitute stock firmware files for
the device's own pre-test files.

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
   Before starting a restored agent, remove only its restored
   `/home/bticino/cfg/extra/c300x-native-agent/c300x-agent-native.pid` if it is a
   regular file. This archived PID is historical evidence, not a live identity;
   stop on an unexpected file type. A future verified start must create a new PID.
5. Restore only the three installer-written startup/IPv4 paths in the table below.
   Remount `/` writable
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

   The IPv6 firewall snapshot is for comparison, not routine restoration: this
   bootstrap does not write it. Any IPv6, GUI or Companion change, or a Flexisip
   change beyond the media user from step 2, leaves this rollback's scope and requires investigation. Preserve all
   managed backup-root material for the maintainer; do not merge an archived
   backup tree over new recovery data or delete it merely because it was absent
   before the test.

6. Compare restored files against the private archive, including modes/ownership
   and link targets; verify GUI/routing hashes still equal the pre-test record.
   Leave new backup/recovery material intact. If any comparison fails, leave the
   agent stopped and startup disabled; do not reboot or retry installation.
7. Compare the saved live-rule snapshots. Only for a rule **absent before**, added
   by this bootstrap and still present exactly once, the maintainer may remove
   that exact addition. For a fresh install on the default API port, the only
   expected addition is:

   ```sh
   iptables -D INPUT -p tcp --dport 8091 -j ACCEPT
   ```

   For a media-enabled reinstall, compare the configured RTSP TCP port and
   talkback UDP 40004 separately against the pre-test snapshot. Never remove
   pre-existing Companion or firmware rules merely because their ports match.

   Never delete a rule present before the test; verify the SSH recovery connection does
   not depend on the rule being removed. Stop on ambiguity or command failure.
   Verify with a fresh private `iptables-save`; do not flush chains, replay the
   complete saved ruleset, or restart networking/vendor services.
8. Start the restored agent via its restored init script only if it was running
   before the test and the original tree/startup have been verified. If no agent
   existed before the test, leave it absent and stopped. No automatic reboot is
   part of this rollback. Check the vendor menus/app locally without operating a
   door or starting media outside the agreed acceptance phase.
9. To undo HA-side installation, stop HA Core, move this test integration directory
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
capability flags, whether the agent is stopped/running/unknown, whether the GUI
hashes stayed unchanged and which of the two step-2 hashes the routing binary has. For card problems include browser/version,
resource URL/hash, screenshot and console error with private details removed.
Never upload the private tar archive, config files, tokens, passwords, SIP accounts
or complete routing configuration. Do not retry or force unsupported controls.

## Evidence and Remaining Work

Existing offline evidence includes exact original-firmware routing checks,
temporary-copy display upgrades/recovery, old-reader bundle delivery, host key/
layout tests and compilation of 29 generated QML files using original Qt 5.10.1
under QEMU. Compilation does not instantiate vendor QML or validate hardware.
See the [C100X notes](c100x-experimental.md), the
[offline checks](dev/release-validation.md#c100x-offline-checks) and the
[page/control matrix](dev/c100x-display-parity.md) for commands and scope.

Before issue attachment delivery: complete the exact-source review, full local
gate, browser tests and fresh complete-package/build-lock verification. This
does not create canonical-main release evidence. Display trials now take effect
by reboot: only the trial boot confirms readiness, and a failed or interrupted trial
rolls back at the next start. This still needs the authorized hardware test above;
this agent-only test does not complete page parity.

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
  about 6.5 KB with 29 entries, below the old 8,192-byte reader limit. Old updaters
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
