# Native Agent

## HTTP and Callback Resource Limits

Incoming HTTP requests use at most eight pending buffers, allocated only while
needed, with a 500 ms total receive deadline. Two of the eight are kept for the
loopback UI listener, so connections to the API port cannot lock the display
out. Incomplete clients are polled
without blocking other incoming requests. HTTP parsing rejects incomplete or
ambiguous message framing.

Event callbacks use one sleeping worker with a 256 KiB stack and at most eight
outstanding jobs. No periodic wakeups or device writes are added. Network I/O,
including DNS, runs outside the main agent loop; confirmed results are applied
there in order. Queue overflow is reported as `callback_queue_full`, not as a
successful delivery. Queued jobs older than 30 seconds are discarded. Replacing
or removing a subscription discards pending jobs and ignores old completions.
An already active request can finish against its original destination.

This page describes the Home Assistant and release-facing native-agent model.
For the full HTTP endpoint contract, use
[Native Agent API Contract](../native_agent/API.md). For source-local build
notes, use [native_agent/README.md](../native_agent/README.md).

## Runtime target

The device runtime is a native C binary from `native_agent/`. Node.js and `node_modules` are not part of the runtime path.

The packaged agent version is defined in [native_agent/VERSION](../native_agent/VERSION).
Release notes identify the matching integration and agent versions.

## Build

```bash
make -C native_agent
make -C native_agent armhf armhf-abi-check armhf-stack-check
```

For HACS/user installs the preferred path is a version-matched packaged ARMHF
agent bundle. The Home Assistant config flow can install that bundle before the
normal token and feature pages when the agent is not reachable yet. A source
checkout may use `native_agent/build/armhf/c300x-agent-native`, but the config
flow never runs `make` itself.

Release packages are built with `scripts/build_hacs_release.py`. The script
builds the ARMHF binary once, copies the device display support files and the
Display patch helper into the custom component package, and writes a HACS-ready
zip under `.release/`.

The bootstrap installer puts the following files on the C300X:

- `c300x-agent-native`
- generated `config.json` with generated API and maintenance tokens (a reinstall keeps the sections of an existing file that Home Assistant does not own: MQTT, mDNS, events, answering machine, memos, metrics, video and display bridge)
- `/etc/init.d/c300x-native-agent` and `/etc/rc5.d/S40c300x-native-agent`
- display support files under the agent directory
- `qml_patch.sh`
- `remove_agent.sh`
- `bootstrap_firewall.sh`
- `bundle.json`

It does not silently apply display, firewall, or IPv6 firewall changes during Home
Assistant startup.

## Config

Use `native_agent/config.example.json` as template. Keep real config untracked.
The example is deliberately a first-setup bootstrap profile:
`api.noAuth=true`, `maintenance.enabled=true`, and
`maintenance.allowNoAuth=true` with empty tokens. Set the API and maintenance
tokens through `/setup` or HA maintenance controls, then close noAuth access.
Installer-generated device tokens are stored on the C300X in
`/home/bticino/cfg/extra/c300x-native-agent/config.json` as `api.token` and
`maintenance.adminToken`. Home Assistant stores its own copy in the integration
config entry/options and uses it automatically; do not edit HA `.storage`
manually and do not copy token values into logs, issues, commits or
documentation.
The HA-facing controls for this are maintenance switch entities. They are not
normal integration options, and turning off the `noAuth` entity after token setup
also turns off noAuth maintenance access. `/setup` never reads configured token
values back from the agent; it only shows configured state and non-secret
fingerprints. Paste known tokens into the request fields when manual API calls
need authorization. Saves from `/setup` are
treated as bootstrap completion: once an API token is configured, that save
automatically turns off `api.noAuth` and `maintenance.allowNoAuth`.

Default runtime security is deliberately low-load and local-first: token auth
after bootstrap, video disabled until HA enables it, media starts only when Home
Assistant requests it, and no display/firewall writes unless a maintenance action is
explicitly invoked.

Key sections:

- `listen`: API/UI bind and ports
- `api`: bearer token
- `openwebnet`: local OpenWebNet endpoint
- `events`: callback store and timeout
- `maintenance`: gated SSH/reboot/display-reload commands
- `systemMetrics`: optional low-frequency push updates for load and temperature
- `video`: optional local doorstation media support
- `displayBridge`: optional dashboard proxy for QML; `feedbackEnabled` stores
  the local **Settings > General > HA feedback** choice (default true).
  Changing it requires no HA connection or GUI restart and writes configuration
  only when the value changes.

Callback URLs for event subscriptions and the display bridge support HTTP and
HTTPS. Use a Home Assistant endpoint reachable from the C300X. For HTTPS, keep
the hostname matching the server certificate; it is never replaced with a source
IP address. Do not use `homeassistant.local`, other `.local` names, or
link-local addresses for callbacks or media routing; those names can resolve to
different paths for Home Assistant, the C300X, browsers and HA Cloud.

For user-facing callback configuration and HTTP/HTTPS selection, see
[Callback URL](advanced-maintenance.md#callback-url). The integration overrides
only the callback base URL; the generated webhook path and shared secret remain
unchanged. The HTTP transport does not load or initialize libcurl/TLS.

HA derives the agent's internal `callbacks.httpsEnabled` setting from the override;
there is no second user-facing switch. Changing between HTTP and HTTPS persists
the setting once and restarts only the agent, not the device or its GUI. Active
calls, streams and media teardown defer that restart using the existing callback
registration retry. Returning to HTTP also restarts the agent to release TLS state.
Unchanged settings do not cause repeated config writes or restarts.

With HTTPS enabled, the agent advertises `https_callbacks` when the device provides a compatible
`libcurl.so.4` (7.34 or newer, HTTPS and asynchronous DNS support). HTTPS uses
TLS 1.2 or newer and verifies both the certificate chain and hostname using
`/etc/ssl/certs/ca-certificates.crt`. The device clock must be correct. Redirects
and environment proxies are disabled; HTTPS errors never trigger an HTTP retry.
A missing library or unsupported curl build requires a device-library update
before HTTPS can work. HTTP remains available independently.

HTTPS adds encryption and certificate verification work on the device. Connections
are not pooled in this implementation. A successful HTTPS delivery does not imply
that device CPU and memory overhead have been measured. HTTP-only installations
do not initialize these libraries or add background transport checks.

The agent's own API listener still serves plain local HTTP. A local reverse proxy
is needed if Home Assistant must connect to that listener through HTTPS.

## API contract

The agent exposes a versioned local HTTP API under `/api/v1`, plus a small
loopback-only UI listener for C300X QML pages. Endpoint paths, auth rules,
payloads, side effects, and compatibility notes are maintained in
[Native Agent API Contract](../native_agent/API.md).

The user-facing feature mapping for those endpoints is summarized in
[Feature reference](feature-reference.md).

Keep new endpoint details in that file. This page should stay focused on
runtime packaging, setup defaults, security posture, and release behavior.

Activation items use `addressMode: "manual"` when the configured `address`
contains the OpenWebNet `where` value. `addressMode: "auto"` is reserved for
read-only device discovery; auto items without a discovered address or explicit
command are returned as non-executable.

Maintenance capabilities are only advertised when explicitly enabled. During
first setup, the example allows noAuth access to the auth/config maintenance
surface so tokens can be set without SSH-editing secrets. Close that setup
window after configuration; token-based maintenance remains intact when noAuth
maintenance access is turned off.

The optional mDNS responder advertises `_bticino-c300x-agent._tcp.local` only
while the agent has no HA event subscription or display-bridge registration. It
uses a per-device TXT `id` and host name derived from the device MAC address
when available, with a hostname fallback, and is controlled by the `mdns.enabled`
config flag and the HA mDNS maintenance switch.

Discovery announcements never receive stored access tokens or change an existing
entry's host and port. If the device address changes, use **Reconfigure** in Home
Assistant to confirm the new address. A DHCP reservation avoids address changes.

The Display patch and Display reload maintenance paths are intentionally narrow: the
agent can only run the configured local UI helper with fixed `status`, `apply`,
`restore`, `core-apply`, `core-restore`, `media-user-label-apply`,
`media-user-label-restore` or `reload` arguments. The patch is a complete Display patch, not just two extra pages: it wires MainApp navigation, transforms the
device HomePage for unread memo/video-message badges, transforms the
device MemoPage for external-delete refresh, adds the HA feedback and touch-tone controls to Settings > General, installs
the project-owned Alarmo, Home Assistant and energy pages, and installs the
local QML JavaScript bridge.
On Qt 4 devices (firmware 1.7.x and 2.0.2) the Display patch also raises the
swipe threshold of the display library from 4 to 16 pixels, so a tap with a
slightly moving finger stays a tap instead of becoming a swipe. The helper
calls the agent binary for it (`--display-touch apply` or `restore`): the
library is recognised by its SHA-256, changed once in one place, written
through a temporary file and restored by the Display restore. A library of
another build is left alone, and a display that does not start with the
changed library gets the original back at once.
Original display files and the original display library are backed up under
`/home/bticino/cfg/extra/c300x-device-file-backups/original`; generated agent
files are not backed up on the device.

The remove-agent maintenance action is explicit and token protected. It first
restores all display changes (Display patch, core hook and media-user label),
then the IPv6 and IPv4 firewall scripts and the display library, stops the agent, restores the original
audio codec and camera quality values, removes the native-agent init files, agent directory and
agent-owned backups, and schedules a reboot.
SSH is started before and after the cleanup and is deliberately not removed. If
a restore step fails, the script stops before deleting the backups. The one
exception is a display library without a valid stock backup: it keeps the wider
tap tolerance and the removal goes on.

System metrics are sampled by the agent every 30 seconds by default, not polled
by Home Assistant. HTTP and push use the same completed sample. CPU changes at
one-decimal-place precision trigger a push; load and memory retain the configured
percentage-point threshold, and temperature uses percent change. A 600 second
heartbeat covers unchanged values. Only successful deliveries advance the push
baseline; a failed delivery leaves the latest state pending for the next sample.
Snapshot instance/sequence metadata prevents older responses overwriting newer
values in Home Assistant. Missing updates expire the sensor after the heartbeat
plus two sample intervals; reconnect refreshes are one-shot and shared.

## Agent updates

Agent updates are HA-orchestrated and explicit. The C300X does not download
arbitrary binaries on its own and does not check for updates in idle.

- HA compares the installed agent and bundle state with the packaged bundle.
- If an update is needed, Home Assistant raises a Repair.
- The Repair uploads the packaged files through the maintenance API only after
  user confirmation.
- The agent verifies the complete staged bundle before replacing any installed
  file. It keeps temporary local backups for changed files, rolls them back on
  an apply error, and writes bundle metadata only after activation succeeds.
  Existing config is preserved; restart is scheduled only after success.

These checks run in the currently installed agent; an update does not change
the updater that installs it. The rollback handles reported apply
errors, not power loss or storage failure during rollback. Recovery backups
left by an interrupted update are not overwritten; inspect and recover that
installation before trying another update. No update checks or backup writes
are added to idle operation.

If an update is refused after an interrupted one, look for files named
`<file>.update-backup` next to the installed agent files, the init script and
the init link. Each is a hard link to the file as it was before the update.
When the installed file next to it works, delete the `.update-backup` file;
when the installed file is missing or broken, move the backup over it first.
The agent does not do this by itself: it never rewrites system files on its own
at start-up, and this path cannot be tested without a power cut on a device.

## Release agent reuse

Release builds accept an executable only when it matches the reviewed build
lock for the current source. The lock covers these native and bundle inputs:

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
- `scripts/build_hacs_release.py`
- `scripts/check_agent_abi.py`
- `scripts/native_build_lock.py`

The release workflow checks the source digest and executable SHA-256 before
accepting a transferred agent. Native changes require a fresh ARMHF build and
ABI/stack checks. Display-content-only changes may retain the binary, but the
bundle and reviewed approval must be regenerated.

Release metadata describes the environment that generates it. Hosted CI does
not have `C300X_DEVICE_SYSROOT`, so its sysroot evidence is unavailable even when
the approved binary was built locally. Local metadata can record library hashes
and a combined fingerprint without paths; this evidence is not transferred by
the ZIP-only release handoff. Keep local build/ABI logs separately. The build
lock is maintainer approval, not independent compiler/sysroot provenance.

## Smoke tests

```bash
make -C native_agent check
```

`make -C native_agent smoke` is optional and intentionally separate because it
exercises maintenance/write paths in a temporary runtime tree.

## ABI and stack guards

`armhf-abi-check` ensures the produced ARMHF binary stays compatible with the
firmware glibc baseline and needs a C300X firmware sysroot through
`C300X_DEVICE_SYSROOT`. Public CI runners do not ship that proprietary sysroot,
so they still compile the ARMHF target and run `armhf-stack-check`, while local
release builds must run the ABI check against the real device sysroot.
One binary serves every supported firmware: it is built against the oldest
(`1.7.19`), and the check also runs against each newer root file system named in
`C300X_ABI_SYSROOTS` (by default the extracted `3.0.6` one, when it is there).
For each it requires the libraries the agent links against, every versioned C
library symbol it imports, and every function it loads at run time from
`libcurl`, `libsrtp` and `libspeex`.
`armhf-stack-check` rejects oversized or dynamic stack usage records for the
ARMHF build.

## Supported firmware versions

The agent is built and ABI-checked against the firmware `1.7.19` root file
system. Firmware `2.0.2` is served by the same binary and the same display
files, because everything they depend on is unchanged there:

- the libraries the agent links against (`libc`, `ld-linux-armhf`,
  `libpthread`, `libdl`) and loads at run time (`libcurl`, `libsrtp`,
  `libspeex`) are byte-identical,
- the vendor GUI tree that the Display patch edits is byte-identical,
- the device tools used by the installer and the agent scripts are present.

`scripts/check_firmware_rootfs.py <1.7.19 rootfs> <other rootfs>` proves this
for a locally extracted root file system and fails on any difference. Run it
before a firmware version is added to the supported list; a version that fails
needs its own build or display files and is not supported by adding a routing
table alone.

Firmware `3.0.6` fails this check and is supported experimentally:

- Its C library is glibc 2.35, and `libcurl` and `libsrtp` are other builds.
  The same binary runs there: `armhf-abi-check` checks it against the `3.0.6`
  root file system as well (see above).
- Its display is Qt 5 with the QML built into the vendor program `BtClass` as
  Qt resources. `qml_patch.sh` recognises it by `/usr/lib/libQt5Core.so.5` and
  then works on a copy in `display-qt5/` under the agent folder: the agent
  reads the six display files the patch changes out of `BtClass`
  (`--display-qt5 extract`: at the known table offsets of the 3.0.6 build, for
  another build where exactly one resource tree with those files is found), the patch runs on
  them as on Qt 4, and every changed file is packed, back in Qt 5 form, into
  `display-qt5.rcc` (`--display-qt5 pack`). The start script `BtClass_qws`
  gets `c300x-qrc-overlay.so` preloaded (`native_agent/qt5/qrc_overlay.c`,
  carried in the agent and written by `--display-qt5 overlay`); it registers
  `display-qt5.rcc` before `BtClass` registers its own resources, and Qt takes
  a file found twice from the first one. A display that ends with an error
  within a minute of such a start marks the overlay failed
  (`display-qt5.rcc.failed`, status `qt5_overlay: failed`) and starts as
  shipped. Started with the overlay, the display's error output, where Qt
  reports QML errors, goes to `/tmp/c300x-display-qt5.log` (at most 64 KB).
  Full removal (`restore-all`) puts the vendor start script back. A partial
  restore keeps the overlay for the remaining core hooks or user label.
  Activation changes preserve the resource file, preload library, wrapper,
  original wrapper backup and quarantine marker as one rollback unit. A
  failed rollback retains its recovery copies and leaves the overlay blocked.
  Updates and partial restores never clear quarantine; full removal followed
  by an explicit apply is required to retry. Apply also compares the RCC,
  embedded preload and generated wrapper when QML is unchanged, repairing
  missing or stale activation files. RCC timestamps are zero and disk caching
  is disabled, so unchanged resources compare byte-for-byte without a restart.
  Runtime-only updates reconcile the preload even with optional pages disabled.
  `qt5_overlay: incomplete` means activation files are missing or incomplete.
  The preload checks every node/name/payload boundary of the generated v2 RCC
  before giving pointers to Qt. Rejected resources are quarantined and the
  stock resources remain available. See the [firmware display audit](audits/firmware-3.0.6-display.md)
  for original-library evidence, the per-path matrix and device-only gaps.
  Not yet tested on a 3.0.6 device;
  process presence is not proof of QML readiness or watchdog safety.
- Its `bt_av_media` sends only the low-resolution video stream on to other
  receivers. The camera is fixed to that stream there
  (`video.av.highResolution: false`), and the Camera resolution entity is not
  offered. Camera quality sets that low stream there (`BitrateRtpL`,
  `FpsRtpL`, `WidthLow`, `HeightLow`); its sizes other than the factory
  400x288 are not yet tested on a 3.0.6 device.
- `bt_answering_machine` is another build with its own routing table.
- As on the other versions, Ring Call and video need a device registered once
  through the Door Entry app: that creates the SIP user, domain and keystore
  of Flexisip.

The routing target is the one file that differs between the supported
versions. `device_routing.c` holds one patch table per known stock build and
selects it by the file's SHA-256, or by the stock bytes of all its patch
ranges; a file of neither build is refused. A backup is restored only when it
is the stock file of the build the device runs, so the backup an earlier
firmware left behind is replaced and never written back. Firmware `2.0.2`
ships the `1.7.19` routing target rebuilt with shifted offsets, so its table
has the same writes at other positions.

The check lists the vendor programs that differ. They cannot be compared
statically and are covered by the device tests in
[release-validation.md](release-validation.md#firmware-versions).

The installer runs no Python on the device. The stock Python of these firmware
versions has neither `json` nor `hashlib`.
