# Native Agent

Runtime packaging, setup defaults, security posture and release behaviour of the
agent on the C300X. The HTTP contract is in the
[Native Agent API](../../native_agent/API.md); internal ownership, workers and
resource limits are in [Architecture](architecture.md#resource-limits).

## Runtime Target

The device runtime is a native C binary built from `native_agent/`. Node.js and
`node_modules` are not part of the runtime path. The packaged agent version is
in [native_agent/VERSION](../../native_agent/VERSION); release notes name the
matching integration and agent versions.

## Build and Checks

Install a C compiler, `pkg-config` and the libcurl development headers
(`libcurl4-openssl-dev` on Debian/Ubuntu). The binary loads `libcurl.so.4` at run
time; it is not linked against the build host's TLS libraries. Without
`pkg-config`, or with the headers outside the system include path, set
`CURL_INCLUDE_DIR` to the directory that contains `curl/curl.h`; the Makefile and
the Python tests that compile `https_client.c` both honour it.

```bash
make -C native_agent
make -C native_agent check
make -C native_agent armhf armhf-abi-check armhf-stack-check
```

`make -C native_agent smoke` is optional and separate because it exercises
maintenance/write paths in a temporary runtime tree.

Run a host build locally with an untracked config:

```bash
cp native_agent/config.example.json native_agent/config.json
$EDITOR native_agent/config.json
native_agent/build/host/c300x-agent-native --config native_agent/config.json
```

### ABI and Stack Guards

`armhf-abi-check` keeps the ARMHF binary compatible with the firmware glibc
baseline and needs a C300X firmware sysroot through `C300X_DEVICE_SYSROOT`.
Public CI runners do not have that proprietary sysroot: they compile ARMHF and
run `armhf-stack-check`, and local release builds must run the ABI check against
the real sysroot. One binary serves every supported firmware: it is built
against the oldest (`1.7.19`), and the check also runs against each newer root
file system named in `C300X_ABI_SYSROOTS` (by default the extracted `3.0.6` and
C100X `1.5.8` ones, when present). For each it requires the libraries the agent
links against, every versioned C library symbol it imports, and every function
it loads at run time from `libcurl`, `libsrtp` and `libspeex`.
`armhf-stack-check` rejects oversized or dynamic stack usage records.

### Developer Checks

Repository validation:

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/python scripts/check_coverage.py
.venv/bin/python scripts/check_typing.py
.venv/bin/ruff check .
.venv/bin/python -m pytest
make -C native_agent check
```

## Packaging and Installed Files

HACS and Marketplace installs use the version-matched packaged ARMHF agent
bundle. The config flow can install it before the token and feature pages when
the agent is not reachable yet. A source checkout may use
`native_agent/build/armhf/c300x-agent-native`; the config flow never runs `make`.

`scripts/build_hacs_release.py` builds the ARMHF binary once, copies the device
display support files and the Display patch helper into the component package,
and writes a HACS-ready zip under `.release/`. Display `.qml` and `.js` files
pass through `scripts/device_file_strip.py` on the way into the bundle (see
[device_qml/README.md](../../device_qml/README.md#packaging)).

The bootstrap installer puts these files on the C300X:

- `c300x-agent-native`
- generated `config.json` with generated API and maintenance tokens (a
  reinstall keeps the sections Home Assistant does not own: MQTT, mDNS, events,
  answering machine, memos, metrics, video and display bridge)
- `/etc/init.d/c300x-native-agent` and `/etc/rc5.d/S40c300x-native-agent`
- display support files under the agent directory
- `qml_patch.sh`, `remove_agent.sh`, `bootstrap_firewall.sh`
- `bundle.json`

It never applies display, firewall or IPv6 firewall changes on its own during
Home Assistant startup. The installer runs no Python on the device: the stock
Python of the supported firmware has neither `json` nor `hashlib`.

## Config

Use `native_agent/config.example.json` as template and keep real configs
untracked. The example is a first-setup bootstrap profile: `api.noAuth=true`,
`maintenance.enabled=true` and `maintenance.allowNoAuth=true` with empty tokens.
Set the API and maintenance tokens through `/setup` or the HA maintenance
controls, then close noAuth access.

Installer-generated tokens are stored on the C300X in
`/home/bticino/cfg/extra/c300x-native-agent/config.json` as `api.token` and
`maintenance.adminToken`. Home Assistant keeps its own copy in the config entry
and uses it automatically; never edit HA `.storage` by hand or copy token values
into logs, issues, commits or documentation. The HA-side controls are
maintenance switch entities, not integration options; turning off the `noAuth`
entity after token setup also turns off noAuth maintenance access. `/setup`
never reads configured tokens back; it shows configured state and non-secret
fingerprints. A `/setup` save counts as bootstrap completion: once an API token
is configured, the save turns off `api.noAuth` and `maintenance.allowNoAuth`.

Defaults are low-load and local-first: token auth after bootstrap, video off
until HA enables it, media only on request, no display or firewall writes
without an explicit maintenance action.

Key sections:

- `listen`: API/UI bind and ports
- `api`: bearer token
- `openwebnet`: local OpenWebNet endpoint
- `events`: callback store and timeout
- `maintenance`: gated SSH, reboot and display-reload commands
- `mdns`: discovery responder (`mdns.enabled`)
- `systemMetrics`: optional low-frequency push of load and temperature
- `video`: optional local doorstation media
- `displayBridge`: optional dashboard proxy for QML; `feedbackEnabled` stores
  the local **Settings > Integration > Status messages** choice (default true).
  Changing it needs no HA connection or GUI restart and writes config only when
  the value changes.

## Callbacks

User-side setup (HTTP or HTTPS, which addresses to avoid, the override field) is
in [Callback URL](../advanced-maintenance.md#callback-url). The integration
overrides only the callback base URL; the webhook path and shared secret stay.
HA derives the agent's internal `callbacks.httpsEnabled` from the override.

- The HTTP transport neither loads nor initialises libcurl/TLS.
- With HTTPS enabled, the agent advertises `https_callbacks` when the device has
  a compatible `libcurl.so.4` (7.34 or newer, with HTTPS and asynchronous DNS).
  HTTPS uses TLS 1.2 or newer and verifies chain and hostname against
  `/etc/ssl/certs/ca-certificates.crt`; the device clock must be correct.
  Redirects and environment proxies are disabled; HTTPS errors never fall back
  to HTTP. A missing or unsuitable curl build needs a device-library update.
- Connections are not pooled. Device CPU and memory cost of HTTPS has not been
  measured.
- Switching mode writes the setting once and restarts only the agent. Active
  calls, streams and media teardown defer the restart through the callback
  registration retry; returning to HTTP restarts to release TLS state.
- The agent's own API listener serves plain local HTTP; put a local reverse
  proxy in front of it if HA must use HTTPS.

## API Contract

The agent serves a versioned API under `/api/v1` plus a loopback-only UI
listener for the station's QML pages. Paths, auth rules, payloads, side effects
and compatibility rules live only in [API.md](../../native_agent/API.md); keep
new endpoint details there. The user-facing mapping is in the
[Reference](../feature-reference.md).

Activation items use `addressMode: "manual"` when `address` holds the
OpenWebNet `where` value. `addressMode: "auto"` is reserved for read-only device
discovery; auto items without a discovered address or explicit command are
non-executable.

Maintenance capabilities are advertised only when enabled. During first setup
the example allows noAuth access to the auth/config maintenance surface so
tokens can be set without editing secrets over SSH; close that window afterwards.
Token-based maintenance keeps working when noAuth maintenance is off.

## Discovery and Address Changes

The optional mDNS responder (`mdns.enabled`, HA mDNS maintenance switch)
advertises `_bticino-c300x-agent._tcp.local` (C300X) or
`_bticino-c100x-agent._tcp.local` (C100X) with a per-device TXT `id` and host
name derived from the MAC address, falling back to the host name. It answers
queries only for its own type. HA lists both types in `manifest.json`; an
announcement of one model never matches, renews or moves an entry whose agent
reported the other model (`model_mismatch`).

- It stays quiet while Home Assistant is present: HA has reached the agent in
  this run (a successful callback) and an authenticated API request arrived
  within the last 15 minutes. HA renews every 5 minutes, so three missed
  renewals reopen the responder. The stamp is taken after the API auth gate, so
  UI-port requests and the agent's own outgoing callbacks cannot hold it closed.
  It uses the monotonic clock, and the poll loop wakes when the quiet period
  ends.
- Each announcement compares the station's current IPv4 address with the one
  the socket was opened for and reopens the socket on a change (multicast
  membership and `IP_MULTICAST_IF` are bound to that address).

Announcements never carry tokens. Home Assistant follows a known station to a
new IPv4 address only after an identity proof
([`POST /api/v1/identity/proof`](../../native_agent/API.md#post-apiv1identityproof),
`discovery_move.py`):

1. HA first asks the saved address. If it still proves the saved identity for
   its own address, nothing changes.
2. Otherwise HA sends a fresh random nonce to the announced address, without any
   credentials. The station answers with its id and an HMAC-SHA256 keyed with
   the API token over its id, the IPv4 address and port the request arrived on,
   and the nonce. The token never goes to the new address.
3. A valid proof updates host and port through the reconfigure path (clearing
   host/port overrides, then reloading); anything else keeps the entry.

Limits: only entries saved with an IPv4 address move (host names and IPv6 stay),
only to IPv4 announcements, only with a discovered station id and a token of at
least 32 characters, at most once per entry in 10 minutes, and not if the entry
changed while the requests ran. When the announced address gave no proof reply
or the saved one still proved, HA checks the same announcement again itself, up
to two more times, 10 minutes apart; a wrong proof is never retried, and a newer
announcement replaces the pending check. The agent refuses a proof with
`api.noAuth=true`, a shorter token or a non-IPv4 connection. Otherwise the user
runs **Reconfigure**; a DHCP reservation avoids address changes.

## Display Patch

The Display patch and Display reload maintenance paths only run the configured
local UI helper with fixed `status`, `apply`, `restore`, `core-apply`,
`core-restore`, `media-user-label-apply`, `media-user-label-restore` or `reload`
arguments. The patch wires MainApp navigation, transforms the device HomePage
(unread memo/video-message badges) and MemoPage (external-delete refresh), adds
the Home Assistant settings tab while keeping the stock General touch-tone
control, installs the project-owned Alarmo, Home Assistant and energy pages, and
installs the local QML JavaScript bridge. File list and safety rules:
[device_qml/README.md](../../device_qml/README.md); user view:
[Station Display Pages](../display.md).

On Qt 4 devices (firmware 1.7.x and 2.0.2) the patch also raises the swipe
threshold of the display library from 4 to 16 pixels, so a tap with a slightly
moving finger stays a tap. The helper calls the agent binary
(`--display-touch apply` or `restore`): the library is recognised by its
SHA-256, changed once in one place, written through a temporary file and
restored by the Display restore. A library of another build is left alone, and a
display that does not start with the changed library gets the original back at
once.

Original display files and the original display library are backed up under
`/home/bticino/cfg/extra/c300x-device-file-backups/original`; generated agent
files are not backed up on the device.

## Agent Removal

The remove-agent maintenance action is explicit and token protected. It stops
the agent with TERM and checks for exit for up to ten seconds; an unverifiable
or still-running agent aborts removal before any restore or delete (no SIGKILL
fallback). It then restores all display changes (Display patch, core hook,
media-user label), the IPv6 and IPv4 firewall scripts, the display library, the
stock routing executable of the Home Assistant media user, the original audio
codec and camera quality values and, if patched, the original media executable;
removes the init files, agent directory and agent-owned backups; and schedules
a reboot. SSH is started before and after the cleanup and
is not removed. A failed restore step stops the script before the backups are
deleted, with one exception: a display library without a valid stock backup
keeps the wider tap tolerance and removal continues. User steps:
[Remove Agent](../advanced-maintenance.md#remove-agent).

The media step checks the routing executable first. A verified stock file is
left as it is, and so is a file the agent never patched (no backup and no
patch). Otherwise the verified stock backup is put back through the same
restore as turning the media user off, and the result must be the stock file
of that firmware. A patched file without its backup, an invalid backup, an
unknown or missing executable next to a backup, or a failed read-only remount
stops removal with the agent and backups kept.

If removal cannot remount the root filesystem read-only after restoration, it
restores the original startup entries and keeps the agent and backups. The agent
stays stopped; earlier successful restore steps are not undone, and no reboot is
requested. A verified `media_reboot_required` result explains a still-running
patched media executable but never permits ignoring a remount failure. Once the
message confirms startup restoration, do a full device reboot and retry removal.
If the startup rollback itself fails, follow the reported recovery location and
restore the entries before rebooting.

The startup recovery copy is kept until final deletion succeeds. If deletion
fails, startup is restored only when the remaining agent tree matches its
pre-deletion hashes, permissions, ownership and link targets; otherwise startup
stays disabled. Keep the reported recovery directory and remaining backups,
repair the installation before restoring startup, and do not reboot until
recovery is complete. The recovery directory holds startup entries and an
identity manifest, not a backup of deleted agent files. A successful removal
requests the usual asynchronous reboot; the request is not confirmation that
the device restarted.

## System Metrics

The agent samples metrics every 30 seconds by default; HA does not poll. HTTP and
push use the same completed sample. CPU changes at one-decimal precision trigger
a push; load and memory use the configured percentage-point threshold,
temperature a percent change. A 600-second heartbeat covers unchanged values.
Only successful deliveries advance the push baseline. Instance/sequence metadata
keeps older responses from overwriting newer values in HA. Missing updates
expire the sensor after the heartbeat plus two sample intervals; reconnect
refreshes are one-shot and shared.

## Optional 960x576 High Video

**Configure > Camera quality** offers an opt-in **960x576** high stream only for
the exact verified media executables of firmware **1.7.19** and **2.0.2**. The
**688x480** and **704x576** choices keep their stock behaviour. Firmware 3.0.x
and its low-stream path are unchanged. User view:
[Camera Quality and Picture Size](../user-guide.md#camera-quality-and-picture-size).

Geometry:

- The camera delivers **720x576**. The high stream sends the crop that
  `stack_open.xml` names whenever the configured Width exceeds 1.5 times Height
  (800x480 from the factory); the other branch keeps fixed 720x576 caps. The
  stock crop is 16/48/688/480; 704x576 and 960x576 use **8/0/704/576**, all 576
  lines.
- The patch replaces two instructions in the media executable, at file offsets
  `0x14a24` and `0x14de4`: instead of copying the crop width, they load 960
  (`mov` into `r7` and `r5`). Both are needed: frame rates 0 and 25 use the
  first caps filter directly, other rates pass `vrate_high` and the second caps
  filter. The picture is scaled to **960x576 before the existing encoder**; no
  transcoding stage, no new camera detail.
- The LCD stays **800x480 (5:3)**; keep that configuration. HA snapshots read
  the display framebuffer (800x480 by default; explicit sizes such as 688x480
  stay).

Identity: the executable must match the full SHA-256 of a known stock image or
its exact patched image; each firmware has its own pair in
`media_geometry_patch.c`. The 1.7.19 and 2.0.2 images differ only in their
GNU build ID, which stays part of the identity. Unknown binaries are never
patched.

Backup and restore: before replacement the agent verifies the stock executable
and backs it up under the managed backup root at
`original/home/bticino/bin/<original-media-executable>`, keeping its
permissions and ownership (0755, UID/GID 1000:1000). Only a verified stock file
can create that backup; a patched executable requires a valid backup, and a
missing or invalid one blocks restore. No original instruction table or vendor
file is distributed, and no original executable is reconstructed. Choosing a
legacy size restores the verified original and writes the selected
configuration. Agent removal finishes this restoration before deleting backups.

Applying and restoring both need a **normal device reboot**; an agent or GUI
restart does not restart the vendor media pipeline. Compare a newly opened
stream after the reboot. The live picture is confirmed on 1.7.19; 2.0.2 is
checked offline only, and built-in answering-machine recordings at 960x576 are
unverified.

## Agent Updates

Agent updates are HA-orchestrated and explicit. The C300X never downloads
binaries on its own and does not check for updates when idle.

- HA compares the installed agent and bundle state with the packaged bundle and
  raises a Repair when an update is needed.
- The Repair uploads the packaged files through the maintenance API after user
  confirmation.
- The agent refuses the update with `409 update_root_already_writable` when
  `/` is already writable, so it never takes over a mount another operation
  left open.
- The agent verifies the complete staged bundle before replacing any file,
  keeps temporary backups of changed files, rolls them back on an apply error
  and writes bundle metadata only after activation. Config is preserved; restart
  is scheduled only after success.

These checks run in the installed agent: an update does not change the updater
that installs it. Rollback covers reported apply errors, not power loss or
storage failure during rollback. An update cut off midway (power cut, kill), or
one committed whose cleanup failed, leaves `<file>.update-backup` hard links
next to the agent files, the init script, the init link and the retired display
source. The next update clears them before it prepares its own transaction
(`update_recover_interrupted()` in `agent_update.c`): when every installed file
matches the installed `bundle.json`, the earlier update was committed and the
leftovers are removed; otherwise its rollback is finished and each backup is
moved back. Both go through the normal finish path with its rw/ro remount. The
agent never rewrites system files on its own at start-up; only an update does
this, and the power-cut case cannot be tested without a power cut on a device.

## Release Agent Reuse

Release builds accept an executable only when it matches the reviewed build lock
for the current source. The lock covers these native and bundle inputs:

- `native_agent/src`
- `native_agent/scripts`
- `native_agent/qt5`
- `native_agent/VERSION`
- `native_agent/Makefile`
- `native_agent/config.example.json`
- `device_qml`
- `custom_components/bticino_c300x/device_agent/init`
- `scripts/stage_device_agent_bundle.py`
- `scripts/device_file_strip.py`
- `scripts/c100x_bundle_builder.py`
- `scripts/c100x_qml_builder.py`
- `scripts/build_hacs_release.py`
- `scripts/check_agent_abi.py`
- `scripts/native_build_lock.py`

The release workflow checks the source digest and executable SHA-256 before
accepting a transferred agent. Native changes need a fresh ARMHF build and
ABI/stack checks. Display-content-only changes may keep the binary, but the
bundle and approval must be regenerated.

Release metadata describes the environment that generates it. Hosted CI has no
`C300X_DEVICE_SYSROOT`, so its sysroot evidence reads unavailable even when the
approved binary was built locally. Local metadata can record library hashes and
a combined fingerprint without paths; the ZIP-only handoff does not transfer it.
Keep local build/ABI logs separately. The build lock is maintainer approval, not
independent compiler/sysroot provenance. Procedure:
[Release Validation](release-validation.md#reviewed-local-native-build).

## Supported Firmware Versions

The `c100x_1.5.8` branch adds the C100X 1.5.8 (in test, issue #51):
detection, routing, package compatibility gates and the display activation by
reboot. The [model matrix](../feature-reference.md#models-and-features) and
the [C100X notes](../c100x-experimental.md) separate what is offered from what
is confirmed on a device; the C300X statements below do not imply the same
display, audio or credential support on C100X.

The agent is built and ABI-checked against the firmware `1.7.19` root file
system. Firmware `2.0.2` uses the same binary and display files because
everything they depend on is unchanged:

- the libraries the agent links against (`libc`, `ld-linux-armhf`,
  `libpthread`, `libdl`) and loads at run time (`libcurl`, `libsrtp`,
  `libspeex`) are byte-identical,
- the vendor GUI tree the Display patch edits is byte-identical,
- the device tools used by the installer and agent scripts are present.

`scripts/check_firmware_rootfs.py <1.7.19 rootfs> <other rootfs>` proves this for
a locally extracted root file system and fails on any difference. Run it before
adding a firmware version; a version that fails needs its own build or display
files, not just a routing table. It also lists the vendor programs that differ;
those are covered by the device tests in
[Release Validation](release-validation.md#firmware-versions).

Firmware `3.0.6` fails this check and is supported with its own display path:

- Its C library is glibc 2.35, and `libcurl` and `libsrtp` are other builds. The
  same binary runs there; `armhf-abi-check` checks it against the `3.0.6` root
  file system too.
- Its display is Qt 5 with the QML built into the vendor program `BtClass` as
  Qt resources. `qml_patch.sh` recognises it by `/usr/lib/libQt5Core.so.5` and
  then works on a copy in `display-qt5/` under the agent folder: the agent
  reads the seven display files the patch changes out of `BtClass`
  (`--display-qt5 extract`: at the known table offsets of the 3.0.6 build, for
  another build where exactly one resource tree with those files is found), the
  patch runs on them as on Qt 4, and every changed file is packed, back in Qt 5
  form, into `display-qt5.rcc` (`--display-qt5 pack`). The start script
  `BtClass_qws` gets `c300x-qrc-overlay.so` preloaded
  (`native_agent/qt5/qrc_overlay.c`, carried in the agent and written by
  `--display-qt5 overlay`); it registers `display-qt5.rcc` before `BtClass`
  registers its own resources, and Qt takes a file found twice from the first
  one. A display that ends with an error within a minute of such a start marks
  the overlay failed (`display-qt5.rcc.failed`, status `qt5_overlay: failed`)
  and starts as shipped. Started with the overlay, the display's error output,
  where Qt reports QML errors, goes to `/tmp/c300x-display-qt5.log` (at most
  64 KB). Full removal (`restore-all`) puts the vendor start script back, but
  only over the original with a block of this or an earlier agent in it. A start
  script that a firmware
  update or anyone else replaced stays as it is, and `status` reports
  `qt5_unsupported: display_wrapper_unknown`. A
  partial restore keeps the overlay for the remaining core hooks or user label.
  User view:
  [Display Patch on Firmware 3.0.6](../display.md#display-patch-on-firmware-306).
- Activation changes preserve the resource file, preload library, wrapper,
  original wrapper backup and quarantine marker as one rollback unit. A failed
  rollback retains its recovery copies and leaves the overlay blocked. Updates
  and partial restores never clear quarantine; full removal followed by an
  explicit apply is required to retry. Apply also compares the RCC, embedded
  preload and generated wrapper when QML is unchanged, repairing missing or
  stale activation files. RCC timestamps are zero and disk caching is disabled,
  so unchanged resources compare byte-for-byte without a restart. Runtime-only
  updates reconcile the preload even with optional pages disabled.
  `qt5_overlay: incomplete` means activation files are missing or incomplete.
  The preload checks every node/name/payload boundary of the generated v2 RCC
  before giving pointers to Qt. Rejected resources are quarantined and the
  stock resources remain available. See the
  [firmware display audit](firmware-3.0.6-display.md) for original-library
  evidence, the per-path matrix and device-only gaps. On a 3.0.6 station only
  the start with the pages and the home page buttons were checked; the other
  pages, the restart and recovery paths are offline only. Process presence is
  not proof of QML readiness or watchdog safety.
- Its vendor media process forwards only the low-resolution stream. The camera
  is fixed to that stream (`video.av.highResolution: false`) and the Camera
  resolution entity is not offered. Camera quality sets the low stream
  (`BitrateRtpL`, `FpsRtpL`, `WidthLow`, `HeightLow`); sizes other than the
  factory 400x288 are untested on a 3.0.6 device. The Low sizes 320x240,
  480x288, 640x384 and 720x432 come through configuration only, without a
  binary patch; evidence and limits:
  [Firmware 3.0.6 Low Camera Evidence](firmware-3.0.6-camera.md).
- `bt_answering_machine` is another build with its own routing table.
- As on the other versions, Ring Call and video need a device registered once
  through the Door Entry app, which creates the Flexisip SIP user, domain and
  keystore.

`device_routing.c` holds one patch table per known stock build of the routing
target and selects it by the file's SHA-256, or by the stock bytes of all its
patch ranges; a file of neither build is refused. A backup is restored only when
it is the stock file of the running build, so a backup left by earlier firmware
is replaced, never written back. Firmware `2.0.2` ships the `1.7.19` routing
target rebuilt with shifted offsets, so its table has the same writes at other
positions. The optional high-video patch has its own exact executable identity
and is never inferred from general agent compatibility.
