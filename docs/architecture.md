# Architecture

## Goal

Provide a local, secure, push-based BTicino C300X integration for Home Assistant with a native device agent.

For the user-visible feature surface, see
[Feature reference](feature-reference.md). This page focuses on internal
ownership and data flow.

## Components

### Home Assistant integration

Path: `custom_components/bticino_c300x/`

Responsibilities:

- Config flow and options flow. The options flow is a settings menu: each area
  saves when it is submitted and returns to its menu; Done closes it. The
  display areas are in a Display submenu, and the display pages are a list
  that opens one page per form.
- Capability-gated entities/services.
- Authenticated API calls to the device agent.
- Event webhook registration and event-state handling.
- Diagnostics and repair issues.
- Bundled Lovelace card registration and resource refresh.
- Home Assistant WebRTC provider/go2rtc media delegation.

Display requests use `dashboard.py` to assemble read-only payloads. User commands
go through `executor.py`, also used by the existing service use cases. Both use
`dashboard_config.py` for the configured allowlist and `alarm_state.py` for alarm
readiness and code policy; neither shared module imports the command executor.

The optional energy page uses pure formatters in `dashboard_energy.py` and
`dashboard_energy_charts.py`. `dashboard_energy_consumers.py` selects up to ten
consumers from the live power sensors explicitly configured in HA Energy,
without recorder queries or inferred sensor mappings. Values are current watts,
not accumulated energy; unavailable sensors are omitted.
`dashboard_energy_data.py` reads HA's Energy setup
and daily recorder statistics; `dashboard_energy_power.py` aggregates recorded
power into 15-minute curves. These reads share bounded, five-minute caches in
HA RAM, only while their views are enabled. Shared daily data is retained when
another enabled view still needs it; disabling all views releases both caches
and stops new reads. Nothing is recorded or stored additionally on the C300X.
`dashboard_energy_updates.py` owns subscriptions and the existing five-minute
refresh; Now and Consumers share live power subscriptions, throttled to ten
seconds. Unloading releases these resources. `C300XEnergy.qml` draws the page
only while open and creates curve segments only for the visible Power view.
The separate `C300XEnergyConsumers.qml` component is loaded only for the
visible Consumers view. It draws two columns of five bars with independently
scaled logarithmic axes and explicit W/kW tick labels. Colors are stable per
entity; the component releases its scale timer when hidden.

Each config entry keeps its live state in `BticinoC300XRuntimeData`, with a typed
agent API. `resources` owns its tasks, subscriptions and media preparation
callbacks; unloading closes this owner and clears the references. `diagnostics`
contains snapshots and operation results, not running tasks. Message-refresh
completion callbacks retain their original resource owner across an entry reload.

Camera event tasks have their own `CameraBackgroundTasks` owner. Entity removal
rejects new work, cancels and awaits pending tasks, then finishes session cleanup.
Interrupted closes retain their session for that cleanup. The camera keeps its
original runtime; removing an old camera does not clear the replacement runtime's
callbacks or stop its device media. CPU-watchdog device commands belong to the
entry runtime; the camera subscriber only closes local WebRTC sessions.

### Native device agent

Path: `native_agent/`

Source docs:

- [Native agent runtime notes](native-agent.md)
- [Native agent source README](../native_agent/README.md)
- [Native agent API contract](../native_agent/API.md)

Responsibilities:

- Local `/api/v1` HTTP API with bearer auth.
- Push callbacks for ring/lock/call/ringer/forwarding/video-message/memo events.
- OpenWebNet command execution.
- Optional local doorstation media module.
- Optional display bridge endpoint for QML dashboard requests.
- Explicit maintenance/update actions for device-agent, display, firewall, MQTT
  migration and media-user setup.

HTTP authentication policy lives in `http_auth.c`; API admission remains in
`http.c`, before the extracted route dispatchers. `http_maintenance.c` owns
the QML/GUI routes and one child-process job, client socket and completion
continuation. It exposes a write-accounting callback, not the agent runtime
structure. `http_device_user.c` owns device-user responses and synchronous label
writes; only its read-only status phase uses that same job slot.
`http_service_commands.c` owns SSH probe/start/stop and SSH-before-reboot/removal
continuations. `http_audio_codec.c` owns codec routes and reuses the reboot
continuation while preserving its separate 200/status-body response contract.

QML status/patch scripts, GUI reload and the read-only device-user status script
run through `command_job.c`. The main poll loop never waits synchronously for these
scripts. Each status and standalone GUI reload script retains its
10-second deadline; QML writes retain 30 seconds for a failed start, file
rollback and restart of the previous GUI. There is no maintenance queue or
additional thread. While an asynchronous job owns the slot, maintenance writes
and competing QML/device-user reads are rejected as busy after authorization. A disconnected client retains its
slot until completion; it does not cancel, restart or duplicate device work.
Shutdown kills the active process group and releases the socket/context.
Label apply/restore instead use `command_transaction.c` synchronously, through
commit/rollback, remount cleanup and child reap. They have no execution deadline
or forced cancellation; graceful shutdown waits for the write to return. This
also removes the old synchronous capture's unsafe ten-second kill timeout.
A hung label script blocks HTTP and graceful shutdown indefinitely. The change
does not certify existing QML-write job cancellation as transaction-safe.
SSH status GETs instead wait in existing bounded input slots, without gaining a
new busy status. Service commands preserve their legacy absence of a deadline
and discarded output; no new worker, queue or idle polling is introduced.

QML/GUI output retains its 4096-byte buffer and overflow failure. Device-user
captures retain their legacy bounded-prefix behavior: 4096 bytes for status,
8192 for label apply/restore, including the terminator. A single request-scoped
context is allocated only while needed. The existing eight reads of at most
1024 bytes per job tick bound noisy-child work. Idle maintenance has no timer.
HTTP request/output/file-transfer and callback queue limits are unchanged.

Native MQTT broker output uses a fixed 3077-byte pending buffer owned by its
existing poll state. Complete frames are admitted in order; saturated new
events are dropped best-effort. CONNECT/SUBSCRIBE output, CONNACK receive and
PINGREQ progress without synchronous output waits. No worker or idle timer is
added. DNS/TCP establishment and MQTT-to-device command forwarding remain
synchronous; see [MQTT output ownership](native-mqtt-output.md).

2.7 is not complete: this is not a fully asynchronous device-I/O architecture.
Device-user routing hash/read/write, label write scripts, remount and fsync
operations still execute synchronously.
Codec mutation is still synchronous despite the route extraction. Firewall,
update, legacy MQTT, OpenWebNet and media lifecycle waits need further scoped
work. No generic worker thread or asynchronous filesystem transaction has been
introduced. See the [HTTP maintenance boundary](native-http-maintenance.md)
for compatibility details and focused validation, and the
[blocking-path inventory](native-http-blocking-inventory.md) for remaining
call paths and safe alternative designs.

QML write transactions retain their previous active files until the GUI process
start check succeeds. A failed start restores those files before attempting to
restart the previous GUI. Process presence is not a QML-readiness handshake:
offline compatibility checks and the pre-merge device test remain necessary.

### Device QML UI

Path: `device_qml/`

Source docs:

- [Device QML UI README](../device_qml/README.md)

Responsibilities:

- Render native C300X dashboard pages.
- Call the local agent UI API on loopback.
- Avoid Lovelace embedding on the device.
- Never store or expose HA tokens.

## Data Flow

```text
C300X event source
  -> native agent
  -> token-authenticated callback to HA event webhook
  -> HA updates entities/event state

HA service/action
  -> HA integration
  -> authenticated native agent /api/v1 command
  -> device execution
```

## Event Contract

The native agent publishes canonical dotted event names such as
`doorbell.pressed`, `door_unlock.started`, `stair_light.activated`,
`stair_light.released`, `activation.executed`,
`answering_machine.messages_changed`, and `memos.changed`. Home Assistant maps
these to its stable event entity values. Old controller aliases are
intentionally not part of the current contract.

Doorbell, call and media state should be derived from native-agent/device
events. Browser/card state may request or display media, but it should not be
the authority for call lifecycle.

## Media Flow

### Retained Visitor Images

`snapshots.py` owns each entry's persisted capture switch, latest-image cache
and hourly retention cleanup. `snapshot_capture.py` reacts to ring events and
camera video-window transitions, deduplicates a physical session, and schedules
one bounded read after the configured delay. It does not open a stream or answer
a call. Closing a session, disabling capture or unloading invalidates pending
work. The card and camera still-image method only consume the retained preview.

The agent's authenticated snapshot endpoint checks that the media process is
using `/dev/fb0`, validates framebuffer geometry and reads it without changing
display state. A normal full-frame vertical page flip during the read is
accepted; changes to the framebuffer layout, pixel format or media ownership
still reject the image. It returns a bounded in-memory BMP in exactly the
width and height the request names (at most the 800x480 display), mixing
neighbouring columns when the image is narrower than the display; no device
file is created.
HA requests the configured size, validates the image, optionally writes the
capture time into it and encodes it as JPEG once in an executor, without
rescaling it. The store checks the JPEG and keeps it as it is. `snapshot_store.py` owns
per-entry storage, quota and expiry under the same HA media root as recordings.
`snapshot_http.py` applies authentication and camera read permissions; Media
Source exposes retained images without depending on an open frontend.

```text
Browser/Card
  -> Home Assistant camera WebRTC provider
  -> go2rtc
  -> native-agent RTSP source
  -> C300X local media path
```

The preview, answered Ring Call, on-demand and Home Call paths are separate at
the integration/card state layer but share the same native media ownership
rules. Talkback is available only through a secure browser context that can
provide microphone access.

## Configuration Writes

Most runtime work is read-only or event-driven. Device writes are limited to
explicit user actions:

- first install/update/remove of the native agent,
- token/bootstrap changes,
- Home Assistant media-user setup or repair,
- forwarding, ringer, answering-machine and memo/message commands,
- Display patch and GUI reload,
- firewall, MQTT, audio codec, SSH and reboot maintenance,
- the display's local HA feedback preference,
- configured device activation synchronization.

## Design Constraints

- No polling architecture for core device state.
- Idle traffic should be near zero.
- No runtime Node.js dependency on device.
- Mutating APIs use POST and explicit auth.
- Show only capabilities the agent actually reports.

## Test Boundaries

Dashboard/executor, config-flow, camera and runtime-manager unit tests use the installed Home Assistant
modules and test-scoped replacements for external operations. Isolated test runs
check module identities before and after execution. Legacy entity tests still contain
module stubs, but all tests share the real Home Assistant exception types;
fixtures verify that these remain unchanged. Full HA lifecycle, Recorder and
media-contract scenarios run in separate processes under `tests/runtime_lab/`.
