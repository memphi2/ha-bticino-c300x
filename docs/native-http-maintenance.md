# Native HTTP Maintenance Boundary

## Ownership

- `http.c`: API admission, global busy-write guard, poll integration and the
  existing diagnostics/event accounting.
- `http_auth.c`: unchanged bearer/admin/bootstrap/confirmation policy and
  shared header lookup. Route modules do not bypass API admission.
- `http_maintenance.c`: exact QML/GUI route matching and a single process,
  retained client socket and optional completion context. No queue or new thread.
- `http_device_user.c`: device-user route validation, response formatting,
  synchronous apply/restore and asynchronous read-only status completion. No
  dependency on agent runtime internals. Completed writes call the existing
  accounting hook on the main loop, before starting the status job.
- `http_service_commands.c`: SSH probe/start/stop and ordered SSH-before-reboot
  or removal. The codec route reuses its reboot continuation, not its response.
- `http_audio_codec.c`: codec status/action validation and response ownership.
  Its native file transaction remains synchronous; only the reboot tail is a job.
- `http_camera_quality.c`: camera quality status/action validation, the same
  way as the codec route. `camera_quality.c` owns the synchronous file
  transaction, `camera_settings.c` the key changes in the settings text and
  `camera_quality_body.c` the offered sizes, limits and the response body.
- `http_clients.c` / `http_client_input.c`: bounded slot admission/deferred
  dispatch versus request receive/framing/deadline handling.
- `command_job.c`: spawn, bounded nonblocking pipe reads, monotonic deadline,
  process-group cancellation and reaping. External capture buffers are borrowed
  until completion/close, never freed by the job.
- `command_transaction.c`: synchronous label-write spawn, bounded-prefix output
  drain and child reap. No deadline, cancellation, worker or idle timer. Signal
  interruptions retry the read/wait, allowing commit/rollback cleanup to finish.

## Preserved Contracts

Routes, methods, confirmations and status/error bodies are unchanged. Unmatched
methods/paths retain the 501 fallback. API rejection remains 401 with the bearer
challenge; maintenance rejection remains 403. Bootstrap access still needs both
noAuth flags and enabled maintenance. Disabled QML/GUI features retain 404.
During an asynchronous job, authorized maintenance writes and competing QML or
device-user script reads return 409 `maintenance_busy`; the global write guard
still runs before route validation. SSH reads use the deferral described below.

QML actions remain `status`, `apply`, `core-apply`, `core-restore`, `restore`;
GUI reload remains `reload`. The camel-case dynamic-homepage field retains
precedence over the snake-case field, and only apply uses it. QML responses keep
the existing leading-object check, not a new strict JSON interpretation. GUI
non-object output retains its successful reload fallback. QML writes record a
change when `changed_files` is absent or positive, not when it is zero/negative.

Device-user ensure retains routing apply, user setup, successful label apply
with JSON `ok:true`, write accounting, then refreshed user/routing/label status.
Restore retains optional label restore, routing restore, accounting, then
status. Label restore checks process success only, as before. A missing label
script fails ensure but does not prevent restore. Missing, non-object or failed
status-script output still produces HTTP 200 with unavailable/unknown label
status, not a new endpoint failure. Output starting with `{` retains the legacy
available flag even if individual fields cannot be parsed. No SIP identity
fields are exposed.

The device-user read-only status script retains its 10-second deadline, including
the final status phase after a write. Label apply/restore are deliberately kept
off the cancellable job API. They block dispatch through commit/rollback,
remount cleanup and reap, then start the status job. Graceful agent shutdown is
processed only after the synchronous write returns; client disconnect does not
abort or duplicate it. Output overflow is drained, not a reason to stop a write.

The old synchronous capture was unsafe too: its ten-second timeout sent
`SIGKILL` without running the script's rollback/remount traps. The label-write
fallback therefore has **no execution deadline or forced cancellation**, not a
verbatim restoration of that capture. A hung script blocks HTTP and graceful
shutdown indefinitely. Power loss or forced process termination is outside this
guarantee; asynchronous transaction recovery remains deferred architecture work.

QML status/GUI deadlines remain 10 seconds and QML writes remain 30 seconds.
Asynchronous jobs retain their slot through reap; shutdown closes that owner
without invoking a completion or advancing a phase. Their existing process-group
kill behavior is unchanged. In particular, the label-write fix does not certify
existing QML-write job cancellation as transaction-safe.

Ordinary job output remains 4096 bytes including NUL and fails on overflow.
Device-user status captures retain 4096 bytes and label captures 8192 bytes,
including NUL, discarding excess as the old synchronous capture did. One
request-scoped context is retained, not a queued request body or copied runtime.
HTTP input/output, file-transfer and callback capacities/timeouts are unchanged.

SSH GET and setter responses retain 200 and actual probe results. A failed
probe means `enabled:false,running:false`, not 502. Failed start/stop commands
retain 502 `maintenance_command_failed`; successful action endpoints retain
their literal start/stop bodies without adding a probe. Feature-disabled
SSH/reboot/removal retain 404, confirmation failures 400, and existing auth gates
still apply. SSH-before-reboot/removal failure remains deliberately ignored.
Reboot/removal retain 202 after delayed-launch acceptance, not after execution.
Removal retains its 500ms delay; reboot uses the unchanged configured positive
delay. Codec mutation failure retains 500 with its original detail; success
retains 200 and the original status body even if reboot scheduling fails
(`rebooting:false`). Changed-file accounting still precedes its reboot attempt.

Service waits previously used `system()` or blocking `waitpid()` without a
deadline. Exit-only command jobs preserve that absence of a deadline, discard
stdout/stderr to `/dev/null` without introducing an output-overflow failure,
and use the old service launcher's descriptor close bound (at most 4096).
They occupy the same single slot and use the existing active-only 50ms reap
tick; an idle job has no timer. A hung service can therefore keep that slot
busy until shutdown, but does not itself block HTTP dispatch. This is not a
claim that all route-side filesystem or event publication is nonblocking.

An authorized enabled SSH GET waits behind an occupied slot without acquiring
a new 409 contract. It retains its complete request in the existing eight-slot
input pool, with two slots still reserved for UI requests and 8192 bytes per
input. There is no additional queue. The 500ms incomplete-request deadline still
applies to receiving input, not to an already complete deferred request.
Successful parsing restores the raw request delimiters for a later retry.
Deferred slots have no poll FD or timer; active-job completion/reap drives
progress. Unauthorized/disabled requests are not deferred. Saturation retains
the existing excess-connection close behavior, not a new HTTP status.

## Validation

Focused loopback tests exercise service responsiveness, API/UI access during
slow scripts, busy/auth ordering, exact route matching, disconnect/reuse,
closed-stdout deadlines, shutdown/process groups and no idle FD/write/timer churn.
C harnesses use real process jobs but stub all device file operations for
ensure/restore ordering, failure responses, confirmations, cancellation and
write-accounting tests. Host and ASan/UBSan variants cover exact output boundaries,
truncation, spawn failure and single-slot ownership. ARMHF ABI and stack checks
use the device sysroot; no installed-device behavior is claimed.

Label-write follow-up: `test_native_device_user_shutdown.py` executes the real
QML script against temporary GUI files with mount/GUI commands stubbed. It
checks apply/restore commit and rollback, shutdown during initial/recovery start,
read-only remount cleanup and writes exceeding the former ten-second deadline.
`test_native_command_transaction.py` checks output bounds, failures, interrupted
reads/waits, early stdout closure and child/FD cleanup. Both run host and
ASan/UBSan variants. A negative control using the pre-fix `1cc61ec` route left
modified labels and orphaned transactions, with no read-only remount call, for
both apply and restore.

The follow-up passed 124 focused checks, including all 11 full-agent status
tests, plus Ruff and compile-only ARMHF checks of the two changed production
modules. The status-test build initially lacked `curl/curl.h`; rerunning with
the existing curl headers and runtime library path passed without installing
dependencies. Earlier ABI and stack evidence above is not a new full validation
of this follow-up. No full gates, bundle rebuild or device/HA access were run.

## Remaining Scope

**2.7 is not complete.** This extraction moves the listed command waits off the
HTTP loop, not every blocking device operation. See the
[blocking-path inventory and proposed ownership designs](native-http-blocking-inventory.md)
for exact remaining route/call paths, including OpenWebNet, MQTT connection waits,
media lifecycle joins, and in-process file/remount transactions. Their recovery,
ordering and cancellation semantics must be settled before moving them to a
worker. The remaining `http.c` is still large; it has not been split into
arbitrary shared-runtime fragments.
Release metadata, build lock and full-suite/device validation are parent work.
