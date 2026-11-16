# Native HTTP Blocking-Path Inventory

This is a source audit of `work/2.7-http`, not a device timing measurement or a
claim of complete nonblocking HTTP. **Architecture work 2.7 remains incomplete.**
The paths below were followed from request dispatch into their implementation,
including continuations and event publication. Ordinary filesystem calls are
listed separately from explicit process/socket/thread waits.

## Completed Command Boundaries

`http_maintenance.c`, `http_device_user.c` and `http_service_commands.c` share
one `command_job` and retained client/context. QML/GUI and device-user label
scripts, SSH probe/start/stop, and SSH-before-reboot/removal no longer wait for
child exit on the main loop. `http_audio_codec.c` also uses the shared reboot
continuation. No extra worker thread or command queue was added.

The codec native mutation and device-user native routing/user operations have
**not** become asynchronous. Write-accounting callbacks also still run on the
main loop and may reach MQTT publication below.

See [preserved contracts](native-http-maintenance.md) for exact statuses,
deadlines, capture limits, slot admission, disconnect and shutdown behavior.
Service commands retain no deadline because the previous waits had none.
The loopback tests demonstrate responsive `/api/v1/health` and UI dispatch
while the selected fake commands are held open, with device IO stubbed and
MQTT/video disabled. They do not establish responsiveness during other waits.

## Maintenance Transactions Still On The Loop

Paths in this section are under `/api/v1/maintenance/`, except device-user.
The names identify actual functions rather than proposed abstractions.

| Request | Request-reachable blocking path |
| --- | --- |
| POST `legacy-mqtt` | `handle_legacy_mqtt_post` -> config persistence/live replacement and `c300x_mqtt_close`; `firewall_remount_rw_if_needed`/`firewall_remount_ro_if_needed` -> `system(mount ...)`; `legacy_mqtt_enable_patch` -> `legacy_mqtt_restore_from_backup` -> `run_fixed_shell_command` -> `system(rm -rf ... && cp -a ...)`. Disable runs `legacy_mqtt_stop_processes` (three synchronous `pkill -f` calls). Enable may run `run_detached_command(C300X_LEGACY_MQTT_SCRIPT, NULL, 0)` -> blocking `waitpid`. |
| POST `mqtt/actions/migrate-legacy` | `handle_mqtt_migrate_legacy_post` -> import/persist/live config replacement, MQTT close/reset, remount/unlink/remount and `legacy_mqtt_stop_processes`. |
| POST `mqtt` | `handle_mqtt_post` -> persistence/live replacement and MQTT close/reset; enabling native MQTT can also remount/disable legacy startup and call `legacy_mqtt_stop_processes`. |
| POST `firewall/actions/apply` | `handle_firewall_action` -> `firewall_apply` -> file backup/write/fsync and remount shell waits; `firewall_apply_runtime_rules` -> `run_fixed_shell_command` -> synchronous `iptables` check/add commands. |
| POST `ipv6-firewall/actions/apply` | Equivalent `ipv6_firewall_apply` and `ipv6_firewall_apply_runtime_rules` path using `ip6tables`. |
| POST firewall or IPv6 firewall `actions/restore` | Corresponding restore function -> backup/file restore and remount shell waits. Restore does not run the apply-runtime-rules function. |
| POST `update/apply` | `handle_agent_update_apply` -> `apply_agent_update_files` in `agent_update.c`: hash/copy/backup transaction and `update_remount` -> `system(mount ...)`; callback `apply_agent_update_firewall_patches` can enter both firewall apply paths. |
| POST `audio-codec/actions/apply` or `actions/restore` | `c300x_http_audio_codec_route` -> `c300x_audio_codec_apply`/`restore` -> synchronous paired-file backup/patch/fsync and private `remount` -> `system(mount ...)`. Only subsequent SSH/reboot scheduling is offloaded. |
| GET `/api/v1/device-user`; POST its `actions/ensure` or `actions/restore` | `http_device_user.c` -> `c300x_device_user_read_status`/`c300x_device_routing_read_status` (files/hashes). Ensure calls `c300x_device_routing_apply` and `c300x_device_user_ensure_homeassistant`; restore calls `c300x_device_routing_restore`. Routing reaches `c300x_patch_remount_root` -> `system`, file copies/patches/fsync; user setup persists credentials. Label-script/status phases alone use jobs. |

Positive-delay `run_detached_command` calls for agent restart and update-triggered
restart already return after fork, without waiting for the child's sleep/exit.
They are not counted as synchronous child-exit waits. Their existing scheduling
acceptance semantics must not silently become execution-success semantics.

### Safe Transaction Design Before Moving These

The first scoped candidate is the legacy MQTT command tail: retain the
file/config phase as one transaction, then use ordered exit-only command-job
phases for the three stop commands or startup script. Preserve ignored command
exit statuses, final status observation and write-accounting order. A cohesive
MQTT route extraction must also cover native-enable and migration, not just
one caller of `legacy_mqtt_stop_processes`.

Even this changes interleaving: native MQTT reconnect can run while legacy stop
is pending, and reads can observe an intermediate state that synchronous
dispatch previously hid. Before implementation, define a transition gate for
reconnect and a bounded deferral policy for affected reads; keep runtime/config
commit and event accounting on the main loop. Do not add a new public 202/409
or let a worker mutate `agent_runtime`.

For complete file/remount transactions, a candidate is an allowlisted private
helper mode executed via `command_job`, with bounded copied inputs and a fixed
result record. Keep backup/rollback/remount cleanup together in the helper,
then commit runtime state on main-loop completion. Do not run arbitrary native
transaction code after `fork()` in the multithreaded agent, and do not pass
live runtime pointers to a cancellable thread.

This needs a recovery decision first: the existing job shutdown kills the
process group, which is not safe to transplant into the middle of a paired
file update or writable-root interval. Define safe cancellation checkpoints,
durable recovery after forced termination, observation during the transition,
and which existing partial-success/error outcome to return. No such behavior
change is included in this branch.

## OpenWebNet Network Waits

`openwebnet.c` uses blocking IPv4 `connect`/`send`/`recv`, configured socket
send/receive timeouts, and `select` for draining. Host parsing is numeric
`inet_pton`, not DNS. Frame reads consume bytes individually, so the configured
timeout is not a single transaction deadline. Drain waits are 250ms per readable
check and can repeat; non-ACK readback permits four frames. Sequence hold and
readback settle delays use `nanosleep`.

| Request | Call path |
| --- | --- |
| POST `/api/v1/stair-light/actions/activate` | `handle_stair_light` -> `activate_stair_light` -> `c300x_openwebnet_send`. |
| POST `/api/v1/activations/{id}/actions/run` | `handle_activation_run` -> `c300x_openwebnet_sequence` or `send`; sequence includes configured press/release hold delay. Runtime/event completion follows. |
| POST `/api/v1/locks/{id}/actions/unlock` | `handle_unlock` -> `c300x_openwebnet_sequence`. |
| GET/POST `/api/v1/smartphone-forwarding` | `handle_smartphone_get`/`post` -> `c300x_openwebnet_send`/`write_readback`; completion may also stop/join the media ring receiver. |
| GET `/api/v1/ringer` | `handle_ringer_get` -> `c300x_ringer_read_json` in `ringer_protocol.c` -> OpenWebNet read commands. |
| POST `/api/v1/ringer` | Volume path -> `c300x_openwebnet_write_readback` with `C300X_RINGER_VOLUME_SETTLE_MS`. Mute first requests GUI work, but `/ui/ringer/next` -> `c300x_ringer_control_next` -> `apply_gui_ringer_command` -> `handle_ringer_post(..., gui_confirmed=1)` still sends/reads synchronously, then may set volume. |
| GET/POST `/api/v1/answering-machine` | `handle_answering_get`/`post` -> OpenWebNet send/readback. |
| POST `/api/v1/answering-machine/messages/actions/delete` and `/api/v1/memos/actions/delete` | Delete handler -> `send_answering_delete_command` -> OpenWebNet send; `wait_for_path_absent(..., 3000)` then polls the path with 100ms sleeps when it was present. |

### Safe Protocol Design

Use a bounded transaction state machine integrated with the existing poll loop:
nonblocking connect/send/frame receive, active-only settle/hold timers, copied
config/command inputs, bounded result frames, main-loop completion. Preserve
per-operation timeout resets and existing error strings, not a newly invented
total deadline. Keep admission bounded using existing slots; serialized
transactions must not introduce new busy/error responses. A private exec helper
is another candidate for pure protocol work, but does not resolve admission or
press/release cancellation policy by itself.

Before implementing lock sequences, decide how shutdown after press guarantees
release without duplicating physical actions. For delete confirmation, retain
the 3-second outcome using an active-only timer/existing file notifications,
not an idle polling timer. Neither design requires a thread per request.

## Media Lifecycle Waits

| Request | Main-thread path requiring media-owner coordination |
| --- | --- |
| POST `/api/v1/video/doorbell/actions/activate` with parked clients | `handle_doorbell_video_activate` -> `c300x_video_activate` -> `c300x_media_session_resume_parked_rtsp` -> `start_media_session`: lifecycle mutex, synchronous SIP setup, talkback startup, `c300x_device_media_takeover` socket waits/settle sleep and failure cleanup. The ordinary keepalive path is not the same as this parked-client path. |
| POST `/api/v1/video/doorbell/actions/stop` | `handle_doorbell_video_stop` -> `c300x_video_stop` -> `c300x_media_session_stop` -> stop lifecycle: RTSP client drain, SIP close, joins of SIP/relay/talkback/on-demand threads and `c300x_device_media_stop` socket waits. |
| POST `/api/v1/calls/doorbell/actions/hangup` | `c300x_video_doorbell_call_hangup` -> `c300x_media_ring_call_hangup` -> same session-stop lifecycle. |
| POST `/api/v1/calls/home/actions/start` or `actions/stop` | `c300x_video_home_call_start`/`stop` -> `c300x_media_home_call_start`/`stop` -> condition waits and `join_home_call_locked`/`pthread_join`. The SIP conversation itself already uses its home-call worker; joining it on main is still a wait. |
| Forwarding GET/POST completion | `sync_ring_receiver_for_forwarding` -> `c300x_video_set_ring_receiver_enabled` -> `c300x_media_ring_receiver_stop` -> ring-thread join when disabling. |

Status and answer routes also acquire media mutexes; moving long operations
while holding those mutexes to another thread would not establish responsiveness.
`/ui/media-closed` updates event state rather than directly calling session stop;
its publication can nevertheless reach the MQTT send path below.

Safe direction: extend the existing media owner's lifecycle requests and
generation/cancellation guards, with completion notification to HTTP. The owner
performs teardown/reaping; the main loop retains a bounded request until the
same response boundary as today. Do not fork a copy of `g_bridge`, create
duplicate workers, change session priority, or return early success before
cleanup solely to make a test pass. This is separate from the maintenance
command slot and must coordinate with independent media work.

## Indirect Network Waits And Existing Background Work

HTTP writes/events can reach `record_agent_write` -> diagnostics event, or
`dispatch_event`/`dispatch_event_internal` directly -> `c300x_mqtt_publish_event`
-> `mqtt_publish` -> `mqtt_send_packet` -> `send_all`. The MQTT socket is
nonblocking, but `send_all` handles backpressure with a synchronous 500ms
`poll(POLLOUT)` and may repeat it. This includes maintenance write accounting,
activation/forwarding/ringer events, memo/message change notifications and
`/ui/media-closed`. It is not fixed by moving only the child command.

Candidate: bounded pending-packet ownership in the existing MQTT poll state,
preserving packet order, existing best-effort publication behavior and failure
handling. Define partial-write/disconnect and saturation behavior first; do not
reuse a callback worker against the main-owned MQTT socket. There is currently
no suitable output queue whose size can simply be increased.

MQTT reconnect (`c300x_mqtt_open_if_needed`) and command draining
(`handle_mqtt_commands` -> `send_mqtt_command_to_device`) also perform DNS/socket
waits on the loop, though they are not direct HTTP request handlers. Enabling
MQTT can trigger the next reconnect iteration. Startup/periodic forwarding
refresh is another non-request OpenWebNet caller. These prevent a whole-loop
nonblocking claim even after request handlers alone are changed.

HTTP event delivery and display-to-HA forwarding already use bounded callback
workers; their DNS/HTTP/TLS waits do not need new per-request threads. This work
does not change those queues, worker shutdown, payload bounds or deadlines.

## Local IO Not Blanket-Offloaded

Codec/firewall/device-user status reads, update prepare/file/status, config
normalization/persistence, memo writes/listing, discovery, snapshots and file
transfer still perform local reads/writes/hash/fsync or device ioctl/mmap work.
Those calls can stall on storage/device IO, but are not all subprocess/network
waits. Preserve their existing bounds and recovery semantics in separately
scoped work instead of applying a blanket filesystem wrapper.

## Focused Evidence

- `test_native_service_command_jobs.py`: real command jobs with temporary fake
  SSH/probe/reboot/removal scripts; concurrent health/UI, failures/auth,
  confirmations, delayed-launch order, output discard, deferred-input deadline,
  pool saturation/UI reservation, disconnect/shutdown and idle FD/write/timer
  checks. Full-agent host and ASan/UBSan builds; codec file calls are link stubs.
- `test_native_service_reboot.py`: shared continuation success, immediate and
  asynchronous scheduling failure, ignored SSH exit failure, exact context
  destruction and cancellation without advancing to reboot.
- `test_native_command_job_wait.py`: no invented deadline/output cap, missing
  executable, one active process, high descriptor closure and cancellation.
- Existing focused QML/device-user, transport/parser, auth, output-boundary and
  codec transaction tests remain independent regression gates.

No device, HA or external service mutation is needed for these tests. This
inventory intentionally reports open work rather than marking 2.7 complete.

The continuation validation run selected 217 tests across transport, command
jobs, device-user routes/jobs, QML/GUI jobs, service/reboot jobs, maintenance
auth, codec writes and resource budgets; all passed. Host and ARMHF builds and
the device-sysroot ABI check passed. The ARMHF stack check remained below 24576
bytes (maximum 24200 in `send_sip_setup`). This was not a full-suite run.
