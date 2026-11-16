# Native HTTP Maintenance Boundary

## Ownership

- `http.c`: API admission, global busy-write guard, poll integration and the
  existing diagnostics/event accounting.
- `http_auth.c`: unchanged bearer/admin/bootstrap/confirmation policy and
  shared header lookup. Route modules do not bypass API admission.
- `http_maintenance.c`: exact QML/GUI route matching and a single process,
  retained client socket and optional completion context. No queue or new thread.
- `http_device_user.c`: device-user route validation, response formatting and
  ordered apply/restore/status continuations. No dependency on agent runtime
  internals. Completed writes call the existing accounting hook on the main loop.
- `http_service_commands.c`: SSH probe/start/stop and ordered SSH-before-reboot
  or removal. The codec route reuses its reboot continuation, not its response.
- `http_audio_codec.c`: codec status/action validation and response ownership.
  Its native file transaction remains synchronous; only the reboot tail is a job.
- `http_clients.c` / `http_client_input.c`: bounded slot admission/deferred
  dispatch versus request receive/framing/deadline handling.
- `command_job.c`: spawn, bounded nonblocking pipe reads, monotonic deadline,
  process-group cancellation and reaping. External capture buffers are borrowed
  until completion/close, never freed by the job.

## Preserved Contracts

Routes, methods, confirmations and status/error bodies are unchanged. Unmatched
methods/paths retain the 501 fallback. API rejection remains 401 with the bearer
challenge; maintenance rejection remains 403. Bootstrap access still needs both
noAuth flags and enabled maintenance. Disabled QML/GUI features retain 404.
Authorized overlapping maintenance writes/script reads return 409
`maintenance_busy`; the global write guard still runs before route validation.

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

Each device-user script has its original 10-second deadline, including the
separate final status phase. QML status/GUI deadlines remain 10 seconds and QML
writes remain 30 seconds. The single slot stays owned across phases and through
child reap. Client disconnect does not abort a partly completed transaction.
Shutdown closes the owner without invoking a completion or advancing a phase.

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

## Remaining Scope

**2.7 is not complete.** This extraction moves the listed command waits off the
HTTP loop, not every blocking device operation. See the
[blocking-path inventory and proposed ownership designs](native-http-blocking-inventory.md)
for exact remaining route/call paths, including OpenWebNet, MQTT event sends,
media lifecycle joins, and in-process file/remount transactions. Their recovery,
ordering and cancellation semantics must be settled before moving them to a
worker. The remaining `http.c` is still large; it has not been split into
arbitrary shared-runtime fragments.
Release metadata, build lock and full-suite/device validation are parent work.
