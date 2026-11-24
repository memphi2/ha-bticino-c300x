# Architecture

Internal ownership, data flow, resource limits and open design work. For what
users see, read the [Reference](../feature-reference.md); the HTTP contract is in
the [Native Agent API](../../native_agent/API.md); runtime packaging is in
[Native Agent](native-agent.md).

## Operating Model

The integration is local-first:

- Home Assistant talks to the native agent on the C300X through the local
  `/api/v1` HTTP API with bearer auth.
- The agent pushes events back to Home Assistant webhooks.
- Camera, Ring Call, Home Call and talkback use Home Assistant's WebRTC
  provider/go2rtc path.
- Core device state is event-driven. Doorbell, call, ringer, forwarding, memo
  and message changes need no polling.
- Device writes happen only through explicit setup, options or Repair actions
  (see [Configuration Writes](#configuration-writes)).

Design constraints:

- No polling architecture for core device state; idle traffic near zero.
- No Node.js runtime on the device.
- Mutating APIs use POST (one `DELETE`, for event subscriptions) and explicit auth.
- Show only capabilities the agent actually reports.

## Components

### Home Assistant Integration

Path: `custom_components/bticino_c300x/`

- Config flow and options flow. The options flow is a settings menu: each area
  saves on submit and returns to the menu; Done closes it. Display areas sit in
  a Display submenu; display pages are a list that opens one page per form.
- Capability-gated entities and services.
- Authenticated API calls to the agent; event webhook registration and
  event-state handling.
- Discovery: zeroconf, and following a station to a new IPv4 address after an
  identity proof (`discovery_move.py`, see
  [Native Agent](native-agent.md#discovery-and-address-changes)).
- Diagnostics and repair issues.
- Bundled Lovelace card registration and resource refresh.
- WebRTC provider/go2rtc media delegation.

Display requests use `dashboard.py` to assemble read-only payloads. User commands
go through `executor.py`, which the service use cases share. Both use
`dashboard_config.py` for the configured allowlist and `alarm_state.py` for alarm
readiness and code policy; neither shared module imports the command executor.

The optional energy page uses pure formatters in `dashboard_energy.py` and
`dashboard_energy_charts.py`. `dashboard_energy_consumers.py` selects up to ten
consumers from the live power sensors configured in HA Energy, without recorder
queries or inferred sensor mappings; values are current watts, unavailable
sensors are omitted. `dashboard_energy_data.py` reads HA's Energy setup and
daily recorder statistics; `dashboard_energy_power.py` aggregates recorded power
into 15-minute curves. Both share bounded five-minute caches in HA RAM, only
while their views are enabled; disabling all views releases both caches and
stops new reads. Nothing is stored on the C300X. `dashboard_energy_updates.py`
owns subscriptions and the five-minute refresh; Now and Consumers share live
power subscriptions, throttled to ten seconds. Unloading releases them.
`C300XEnergy.qml` draws the page only while open and creates curve segments only
for the visible Power view; `C300XEnergyConsumers.qml` is loaded only for the
visible Consumers view.

Each config entry keeps its live state in `BticinoC300XRuntimeData`, with a typed
agent API. `resources` owns its tasks, subscriptions and media preparation
callbacks; unloading closes this owner and clears the references. `diagnostics`
holds snapshots and operation results, not running tasks. Message-refresh
completion callbacks keep their original resource owner across an entry reload.

Camera event tasks have their own `CameraBackgroundTasks` owner. Entity removal
rejects new work, cancels and awaits pending tasks, then finishes session
cleanup; interrupted closes keep their session for that cleanup. Removing an old
camera does not clear the replacement runtime's callbacks or stop its device
media. CPU-watchdog device commands belong to the entry runtime; the camera
subscriber only closes local WebRTC sessions.

### Native Device Agent

Path: `native_agent/`. Source docs: [Native Agent](native-agent.md),
[source README](../../native_agent/README.md),
[API contract](../../native_agent/API.md).

- Local `/api/v1` HTTP API with bearer auth, plus a loopback-only UI listener
  for the station's QML pages.
- Push callbacks for ring, lock, call, ringer, forwarding, video-message and
  memo events.
- OpenWebNet command execution.
- Optional local doorstation media module and display bridge.
- mDNS responder (`mdns.c`) and identity proof (`http_identity.c`).
- Explicit maintenance and update actions: agent update, display, firewall,
  MQTT migration and media-user setup.

This is not a fully asynchronous device-I/O design. The
[HTTP Maintenance Boundary](#http-maintenance-boundary),
[Request Workers](#request-workers) and [MQTT Output](#mqtt-output) describe
what runs beside the main poll loop; [Remaining Blocking Work](#remaining-blocking-work)
lists what still waits on it.

### Device QML UI

Path: `device_qml/`. Source doc: [Device QML UI README](../../device_qml/README.md).

- Renders native C300X dashboard pages.
- Calls the local agent UI API on loopback.
- No Lovelace embedding on the device; never stores or exposes HA tokens.

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

### Event Contract

The agent publishes canonical dotted event names such as `doorbell.pressed`,
`door_unlock.started`, `stair_light.activated`, `stair_light.released`,
`activation.executed`, `answering_machine.messages_changed` and
`memos.changed`. HA maps these to its stable event entity values. Old controller
aliases are not part of the contract.

Doorbell, call and media state derive from agent/device events. Browser/card
state may request or display media but is never the authority for the call
lifecycle.

## Media Flow

### Retained Visitor Images

`snapshots.py` owns each entry's persisted capture switch, latest-image cache
and hourly retention cleanup. `snapshot_capture.py` reacts to ring events and
camera video-window transitions, deduplicates a physical session and schedules
one bounded read after the configured delay. It neither opens a stream nor
answers a call. Closing a session, disabling capture or unloading invalidates
pending work. The card and the camera still-image method only consume the
retained preview.

The agent's snapshot endpoint checks that the media process is using `/dev/fb0`,
validates framebuffer geometry and reads it without changing display state. A
full-frame vertical page flip during the read is accepted; a change of layout,
pixel format or media ownership rejects the image. It returns a bounded
in-memory BMP in exactly the requested width and height (at most the 800x480
display), mixing neighbouring columns when the image is narrower; no device file
is created. HA validates the image, optionally writes the capture time into it
and encodes it as JPEG once in an executor, without rescaling.
`snapshot_store.py` owns per-entry storage, quota and expiry under the same HA
media root as recordings. `snapshot_http.py` applies authentication and camera
read permissions; Media Source exposes retained images without an open frontend.

### Live Media

```text
Browser/Card
  -> Home Assistant camera WebRTC provider
  -> go2rtc
  -> native-agent RTSP source
  -> C300X local media path
```

Preview, answered Ring Call, on-demand and Home Call paths are separate at the
integration/card state layer but share the same native media ownership rules.
Talkback needs a secure browser context with microphone access. RTSP sources
carry interleaved RTP over TCP only. A viewer that briefly stops reading loses
whole media packets; a partly sent packet is finished before more media or an
RTSP reply. There is no backlog buffer; a sustained stall ends the session.

### Native Media Modules

`media_bridge.h` is the caller-facing media lifecycle contract.

- `media_rtsp_reader.c` reads one request (with body) or interleaved frame from
  a caller-owned per-connection buffer. Only `c300x_media_rtsp_read` is
  exported; it allocates nothing and starts no background work. The bridge's
  client handler owns the buffer, chooses the authenticated/unauthenticated,
  playing and TEARDOWN deadlines, handles authentication and backchannel
  dispatch, and closes the connection.
- `media_rtsp_io.c` holds readiness waits and serialised bounded writes;
  `media_rtsp_clients.h` holds client-slot helpers whose callers must hold the
  bridge mutex.
- `media_sip_dialog.c` sends the stateless ACK, BYE, Home Call CANCEL, Ring
  Call BYE and generic OK messages. Inputs are borrowed for one synchronous
  call; it reads no responses, closes no sockets and takes no session locks.
- `media_sip_io.c` holds `c300x_media_sip_send_all`, the two-second bounded
  sender. `media_sip.c` holds the shared repeated-header copying helper.

Ring Call responses, REGISTER and INVITE stay in the bridge because they depend
on session UUID creation and setup decisions; so do CANCEL/BYE selection and
stop-response draining. `media_bridge.c` is the sole owner of `media_bridge_t`,
`g_bridge`, the lifecycle and bridge mutexes, on-demand cancellation, Ring Call
and Home Call state, device takeover, worker creation and joins, stop flags,
SRTP state lifetime and socket closure. A future split must define a narrower
session ownership contract first, rather than expose the bridge structure, and
keep lock order, join-before-free, retry intervals and media pacing.

`test_native_media_protocol_modules.py` links each module without bridge state
and runs socket framing and byte-for-byte dialog regressions, also under
ASan/UBSan; symbol contracts limit each module's exports and dependencies.

## HTTP Maintenance Boundary

### Module Ownership

| Module | Owns |
| --- | --- |
| `http.c` | API admission, global busy-write guard, poll integration, diagnostics and event accounting. |
| `http_auth.c` | Bearer, admin, bootstrap and confirmation policy; shared header lookup. Route modules never bypass admission. |
| `http_maintenance.c` | QML/GUI routes and the single job slot: one child process, retained client socket and completion context. Exposes a write-accounting callback, not the runtime structure. |
| `http_device_user.c` | Device-user validation and responses, synchronous label writes, asynchronous read-only status phase. |
| `http_service_commands.c` | SSH probe/start/stop and the ordered SSH-before-reboot/removal continuations. |
| `http_audio_codec.c` | Codec status/action validation and responses. The file transaction stays synchronous; only the reboot tail is a job. |
| `http_camera_quality.c` | Camera quality routes, like the codec. `camera_quality.c` reads the state and runs an apply under the update lock; `camera_files.c` and `camera_update.c` own the file transaction (backup, write, verify, rollback), `camera_settings.c` and `camera_crop.c` the key edits, `camera_sizes.c` the offered sizes and limits; `camera_quality_body.c` only formats the response. |
| `http_clients.c`, `http_client_input.c` | Bounded slot admission and deferred dispatch; request receive, framing and deadline. |
| `command_job.c` | Spawn, bounded nonblocking pipe reads, monotonic deadline, process-group cancellation and reap. Capture buffers are borrowed, never freed by the job. |
| `command_transaction.c` | Synchronous label-write spawn, bounded output drain and reap. No deadline, cancellation, worker or timer; signal interruptions retry the read/wait so commit/rollback cleanup can finish. |

### Jobs and Deadlines

QML status/patch, GUI reload, the read-only device-user status script, SSH
probe/start/stop and SSH-before-reboot/removal share one `command_job` slot.
The main loop never waits for these scripts; there is no queue and no thread.

| Job | Deadline |
| --- | --- |
| QML status, standalone GUI reload, device-user status | 10 s |
| QML write (incl. failed start, file rollback, restart of the previous GUI) | 30 s |
| SSH start/stop | 60 s |
| SSH status | 15 s |
| Label apply/restore | none (synchronous, see below) |

At a deadline the process group is killed. While a job owns the slot,
authorized maintenance writes and competing QML or device-user reads get
`409 maintenance_busy`; the global write guard runs before route validation. An
authorized, enabled SSH GET instead waits in its input slot (no new 409, no
extra queue); deferred slots have no poll FD or timer, and job completion drives
them. A disconnected client keeps its slot until completion: device work is not
cancelled, restarted or duplicated. Shutdown kills the active process group and
releases the socket and context without invoking a completion.

Service commands discard stdout/stderr, close descriptors up to 4096 and use the
active-only 50 ms reap tick; an idle job has no timer.

Label writes run through `command_transaction.c` synchronously, including
commit/rollback, remount cleanup and reap, then start the status job. They have
no deadline or forced cancellation on purpose: a `SIGKILL` would skip the
script's rollback/remount traps. A hung label script therefore blocks HTTP and
graceful shutdown; power loss and forced termination are outside the
guarantee. QML write transactions keep their previous active files until the
GUI start check succeeds and restore them on a failed start. Process presence is
not a QML-readiness handshake, and QML-write job cancellation is not certified
as transaction-safe.

### Preserved Response Contracts

- Unmatched methods/paths: 501. API rejection: 401 with bearer challenge;
  maintenance rejection: 403. Bootstrap needs both noAuth flags and enabled
  maintenance. Disabled QML/GUI features: 404.
- QML actions `status`, `apply`, `core-apply`, `core-restore`, `restore`; GUI
  action `reload`. The camel-case dynamic-homepage field wins over snake-case
  and only apply uses it. QML responses use the leading-object check; GUI
  non-object output counts as a successful reload. A QML write records a change
  when `changed_files` is absent or positive.
- Device-user ensure: routing apply, user setup, label apply with JSON
  `ok:true`, write accounting, then refreshed status. Restore: optional label
  restore, routing restore, accounting, status; label restore checks exit
  status only. Failed or unparsable status output still returns 200 with
  unavailable/unknown label status. No SIP identity fields are exposed.
- SSH GET and setters return 200 with probe results (a failed probe reads
  `enabled:false,running:false`); failed start/stop return
  `502 maintenance_command_failed`. Reboot/removal return 202 after
  delayed-launch acceptance, not after execution (removal 500 ms delay, reboot
  the configured delay); SSH failure before them is ignored.
- Codec mutation failure returns 500 with its detail; success returns 200 and
  the status body even when reboot scheduling fails (`rebooting:false`).
  Changed-file accounting precedes the reboot attempt.

### Focused Tests

Loopback tests cover responsiveness during slow scripts, busy/auth ordering,
exact route matching, disconnect/reuse, closed-stdout deadlines, shutdown and
process groups, and no idle FD/write/timer churn. Device file operations are
stubbed. Host and ASan/UBSan variants cover output boundaries, truncation, spawn
failure and single-slot ownership.

- `test_native_service_command_jobs.py`: real jobs with fake SSH/probe/reboot/
  removal scripts, concurrency, confirmations, delayed-launch order, deferred
  input, pool saturation and UI reservation.
- `test_native_service_reboot.py`: shared reboot continuation, scheduling
  failures, cancellation without advancing to reboot.
- `test_native_command_job_wait.py`: exit-only jobs, missing executable, one
  active process, descriptor closure.
- `test_native_device_user_shutdown.py`: the real QML script against temporary
  GUI files; commit, rollback, shutdown during start and recovery, read-only
  remount cleanup, writes longer than ten seconds.
- `test_native_command_transaction.py`: output bounds, interrupted reads and
  waits, early stdout close, child and FD cleanup.

## Request Workers

OpenWebNet exchanges (`openwebnet_async.c`) and media operations
(`video_control.c`, handlers in `http_media_actions.c`) run on worker threads
that exist only while one runs (`request_worker.c`). The request stays in its
client slot; the handler returns at once and runs again when the worker is done,
and receives the stored result of the same call, so every command is sent once.
Requests take the worker in arrival order. A caller that left does not cancel
or repeat a running command; shutdown lets a running sequence or operation
finish (a pressed lock is released). If no thread or wake pipe can be created,
the call runs on the loop.

Covered requests: stair light, activation run, unlock, smartphone forwarding
GET/POST, ringer GET/POST, answering machine GET/POST, message and memo delete;
video activate/stop, Ring Call answer/hangup, Home Call start/stop.

Queueing (`request_queue.c`): three waiting places shared by both workers,
beside the two running requests. Other open requests (an SSH read deferred
behind a job, a configuration write held behind worker jobs, an unfinished
upload) also count against the six API client slots.

- No place free: `openwebnet_busy` (502) or `media_busy` (503).
- When all places are taken, a waiting request whose caller has left loses its
  place to the new one and is later answered `client_gone`.
- A waiting request whose caller has left (also a half-close) is answered
  `client_gone` (502/503) without running. A media stop that only waited still
  runs unless it lost its place.
- These answers come from the loop, not the handler, so a refused read is not
  taken for a failed one.

Handler rules:

- After a failed call with `c300x_openwebnet_deferred()` set, return without
  any effect; `send_json` writes nothing in that state.
- A handler runs again from its start, so a state checked before the first call
  must not be checked again once the request owns a command
  (`c300x_openwebnet_async_owns`); the ringer handlers do this for the display
  slot.
- The four configuration-replacing maintenance POSTs (auth, MQTT, legacy MQTT,
  MQTT migration) hold back, after their own admission check, while either
  worker has a job that is not theirs. Held writes take no waiting place and go
  by client slot; a write whose caller has closed (also only its sending side)
  is never applied. The media worker reads the live configuration on its
  thread; a re-run request checks its token again.
- After eight stored results of one request, further calls run on the loop.
- No handler uses both workers. One that will must take them in a fixed order
  and keep what the first holds while it waits for the second.

Stops from elsewhere (CPU watchdog, a departing RTSP client) bypass the worker
and can run beside an operation. Status routes take the media mutexes only
briefly; lifecycle waits happen under `media_lifecycle_mutex` or without a
lock, never under the bridge mutex. `/ui/media-closed` (the display's
`onCallEnded` hook) only wakes the display pages: it also fires when Home
Assistant answers a ring, so `doorbell.media.closed` comes only from the bus,
SIP and stream stops.

## MQTT Output

`mqtt_bridge.c` owns the broker socket in the poll loop. `mqtt_output.c` owns the
pending wire bytes: no thread, client or heap queue. CONNECT, SUBSCRIBE,
availability/start-date publications, events and PINGREQ share one ordered
output. POLLOUT is requested only while bytes remain; each flush is one
`MSG_DONTWAIT` send, and EAGAIN/EWOULDBLOCK/EINTR keep the bytes.

- Pending storage is 3077 bytes (largest payload 3072 plus a 5-byte fixed
  header). A whole frame must fit before any byte is admitted; accepted frames
  are never interleaved, reordered or replaced. Builder bounds stay CONNECT
  1024, SUBSCRIBE 256, publication 3072, receive 4096.
- Events are best-effort: an oversized or newly saturated frame is dropped
  whole without changing the HTTP response; nothing is replayed after a
  reconnect. Two bytes are reserved for one PINGREQ, which later events cannot
  overtake.
- Startup: CONNECT output, CONNACK receive (exactly four bytes, 1500 ms
  deadline reset by each partial receive), SUBSCRIBE output, ready. The agent
  reports connected only after SUBSCRIBE has left the buffer; there is no SUBACK
  wait. Retained availability, then start date, precede later events.
- A 500 ms no-progress deadline replaces the old writable wait; only positive
  writes reset it. Fatal or zero-byte sends, output timeout, failed CONNACK and
  close discard pending output and use the reconnect backoff. Close, shutdown,
  offline and reconfiguration clear output, deadlines and ping state.

Host, ASan/UBSan and full-agent loopback-broker tests cover capacity, whole-frame
rejection, short writes, EINTR/EAGAIN, startup phases, fragmented CONNACK,
ordered event and ping output, and responsive health/UI while the broker stops
reading.

## Resource Limits

| Area | Limit |
| --- | --- |
| HTTP input | 8 pending buffers, allocated on demand, 8192 bytes each; 2 reserved for the loopback UI listener; 500 ms total receive deadline for incomplete input. Ambiguous or incomplete framing is rejected. |
| HTTP output | Response body up to 1200 KiB (the largest visitor image); all queued output together 1712 KiB with at most eight waiting connections. A queued response ends after 2 s without progress and after 10 s in total; beyond the budget, output is rejected instead of blocking the loop or growing the queue. |
| Event callbacks | One worker (256 KiB stack), at most eight outstanding jobs; network I/O and DNS outside the main loop, results applied there in order. Overflow is `callback_queue_full`, not success. Jobs older than 30 s are discarded; replacing or removing a subscription discards pending jobs and ignores old completions. |
| Display forwarding | Separate worker with at most one outstanding request, so the HTTP loop stays free for nested HA commands. No retries, no queued physical actions; a callback timeout is no proof that the downstream action did not run. |
| Command output | Job output 4096 bytes incl. NUL, overflow fails. Device-user status 4096 and label writes 8192 bytes, bounded prefix. At most eight reads of 1024 bytes per job tick. |
| Request workers | Two running requests, three waiting places, eight stored OpenWebNet results per request. |
| MQTT output | 3077 bytes pending, see [MQTT Output](#mqtt-output). |

Home Assistant media downloads, conversions and cache retention have their own
explicit limits. These controls reduce resource-exhaustion risk; they do not
replace authentication, network isolation or dependency review, and they add no
packet capture or device polling.

## Remaining Blocking Work

Paths below still wait on the main loop. Their recovery, ordering and
cancellation semantics must be settled before moving them.

### Maintenance Transactions

Paths are under `/api/v1/maintenance/` except device-user.

| Request | Blocking path |
| --- | --- |
| POST `legacy-mqtt` | Config persistence and live replacement, `c300x_mqtt_close`; remount via `system(mount ...)`; `legacy_mqtt_restore_from_backup` -> `system(rm -rf ... && cp -a ...)`. Disable runs three synchronous `pkill -f` (`legacy_mqtt_stop_processes`); enable may run the legacy script with a blocking `waitpid`. |
| POST `mqtt/actions/migrate-legacy` | Import, persist, live replacement, MQTT close/reset, remount/unlink/remount, `legacy_mqtt_stop_processes`. |
| POST `mqtt` | Persistence, live replacement, MQTT close/reset; enabling native MQTT may remount, disable legacy startup and stop legacy processes. |
| POST `firewall/actions/apply`, `ipv6-firewall/actions/apply` | File backup/write/fsync, remount shell waits, synchronous `iptables`/`ip6tables` check/add commands. |
| POST firewall/IPv6 firewall `actions/restore` | Backup restore and remount shell waits. |
| POST `update/apply` | `apply_agent_update_files` (`agent_update.c`): hash/copy/backup transaction, `system(mount ...)`; may enter both firewall apply paths. |
| POST `audio-codec/actions/apply` or `restore` | Paired-file backup/patch/fsync and remount; only the SSH/reboot tail is a job. |
| POST `camera-quality` | Backup/write/fsync of the settings file and, for the high stream, the crop file, with `c300x_device_file_remount`; choosing or leaving 960x576 also patches or restores the media executable. Rollback included, all on the loop. |
| GET `/api/v1/device-user`; POST `device-user/actions/ensure-homeassistant`, `restore-homeassistant-setup` | Status reads hash files; ensure/restore patch routing (`c300x_patch_remount_root` -> `system`, copies, fsync) and persist user credentials; label writes via `c300x_command_transaction_capture`. |

Positive-delay `run_detached_command` calls (agent restart, update restart)
return after fork and are not waits; their acceptance semantics must not turn
into execution-success semantics.

Design direction:

- First candidate: the legacy MQTT command tail. Keep the file/config phase as
  one transaction, then run the stop commands or startup script as ordered
  exit-only job phases, keeping ignored exit statuses, final status observation
  and write-accounting order. Cover native-enable and migration too. Define a
  reconnect transition gate and a bounded deferral for affected reads first; do
  not add a public 202/409 or let a worker mutate `agent_runtime`.
- File/remount transactions: an allowlisted private helper mode run through
  `command_job`, with copied bounded inputs and a fixed result record, keeping
  backup, rollback and remount cleanup together; commit runtime state on the
  main loop. Never run native transaction code after `fork()` in the
  multithreaded agent or hand live runtime pointers to a cancellable thread.
  This needs a recovery decision first (safe cancellation checkpoints, durable
  recovery after forced termination, observation during the transition, and the
  outcome to return), because the job's process-group kill is unsafe mid-update.

### OpenWebNet on the Loop

`openwebnet.c` uses blocking IPv4 `connect`/`send`/`recv` with socket timeouts and
`select` for draining (250 ms per readable check, repeatable; four frames for
non-ACK readback); hosts are numeric, no DNS. Sequence hold and settle delays use
`nanosleep`. Still on the loop, each waiting for a running worker first:

- the GUI-confirmed ringer write (`/ui/ringer/next` -> `c300x_ringer_control_next`
  -> `handle_ringer_post(..., gui_confirmed=1)`),
- the forwarding read at startup,
- the 3-second `wait_for_path_absent` (100 ms polls) of the two delete handlers.

Candidate design (not built): a bounded transaction state machine in the poll
loop with nonblocking connect/send/receive, active-only hold and settle timers,
copied inputs, bounded result frames and main-loop completion; keep the
per-operation timeouts and error strings, admit within existing slots. Decide
first how shutdown after a press guarantees the release without repeating it.
Delete confirmation should keep its 3-second outcome with an active-only timer
or file notifications, not idle polling.

### Media and Network

- The forwarding completion (`sync_ring_receiver_for_forwarding` ->
  `c300x_media_ring_receiver_stop`, a ring-thread join when disabling) runs on
  the loop after waiting for a running operation.
- MQTT reconnect (`c300x_mqtt_open_if_needed` -> `socket_connect_timeout`) still
  resolves DNS and waits for TCP establishment; command draining
  (`handle_mqtt_commands` -> `send_mqtt_command_to_device`) has its own
  DNS/device-socket waits.
- Event delivery and display forwarding already use bounded callback workers.

### Local I/O

Codec, firewall and device-user status reads, update prepare/file/status, config
persistence, memo writes and listing, discovery, snapshots and file transfer
still do local reads, writes, hashing, fsync or device ioctl/mmap work. Keep
their bounds and recovery semantics in separately scoped work; no blanket
filesystem wrapper.

## Configuration Writes

Most runtime work is read-only or event-driven. Device writes come only from
explicit user actions:

- install, update and removal of the agent,
- token/bootstrap changes,
- Home Assistant media-user setup or repair,
- forwarding, ringer, answering-machine and memo/message commands,
- Display patch and GUI reload,
- firewall, MQTT, audio codec, camera quality, SSH and reboot maintenance,
- the display's local Status messages preference,
- configured device activation synchronization.

## Test Boundaries

Dashboard/executor, config-flow, camera and runtime-manager unit tests use the
installed Home Assistant modules and test-scoped replacements for external
operations. Isolated runs check module identities before and after execution.
Legacy entity tests still contain module stubs, but all tests share the real HA
exception types; fixtures verify that. Full HA lifecycle, Recorder and
media-contract scenarios run in separate processes under `tests/runtime_lab/`.
Release-level checks are in [Release Validation](release-validation.md).
