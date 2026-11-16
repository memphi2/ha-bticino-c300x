# Native MQTT Output Ownership

## Scope And Ownership

`mqtt_bridge.c` remains the sole owner of the broker socket in the HTTP poll
loop. `mqtt_output.c` owns pending wire bytes, not a thread, broker client or
heap queue. Video events already reach the main loop through the existing
video event pipe before MQTT publication; callback workers do not use this
buffer.

CONNECT, SUBSCRIBE, startup availability/start-date publications, event
publications and PINGREQ all use the same ordered output. The HTTP loop requests
POLLOUT only while bytes remain. Each flush performs one `MSG_DONTWAIT` send;
EAGAIN/EWOULDBLOCK/EINTR retain bytes for a later poll iteration. There is no
output retry loop or idle timer.

## Bounds And Saturation

Pending storage is fixed at **3077 bytes**, the old largest payload workspace
(3072) plus the maximum MQTT fixed header (5). Existing CONNECT (1024),
SUBSCRIBE (256), publication (3072) builder checks and receive (4096) bounds
are unchanged. A complete frame must fit before any of it is admitted. An
unsent suffix may be compacted, but accepted frames are never interleaved,
reordered or replaced.

Event publication remains best-effort: an oversized or newly saturated frame
is dropped whole, without changing the initiating HTTP status/body or evicting
earlier output. No event is retried across reconnect. Publications reserve two
bytes for one PINGREQ. Its pending-byte marker includes all bytes ahead of it,
so later events cannot overtake it, and keepalive does not enqueue duplicate
pings while one is pending.

## Phases And Deadlines

Startup proceeds through CONNECT output, CONNACK receive, SUBSCRIBE output and
ready. The agent does not advertise connected/subscribed until SUBSCRIBE has
fully left the application buffer. The existing absence of a SUBACK wait is
preserved. Retained availability then retained local start-date publication
remain ordered ahead of later event output.
The retained start date, initial keepalive deadline and startup-failure retry
schedule use the original connection-attempt time snapshot, even when
handshake/output completion happens in a later loop iteration.

CONNACK consumes exactly four bytes and retains the existing header/return-code
checks. Its 1500ms wait is now an active monotonic deadline reset on each
partial receive, matching the former per-read wait rather than adding a total
handshake timeout. TCP connection establishment is not covered by this phase.

The former 500ms writable wait is represented by a **500ms no-output-progress
deadline**. Positive writes reset it; newly queued events, EAGAIN and EINTR do
not. Pending output contributes this deadline to the existing poll timeout.
An idle ready connection contributes only its original keepalive deadline.
Once a PINGREQ has fully left the application buffer, its next keepalive
deadline is scheduled using the existing configured interval.

## Failure And Close

Fatal send, zero-byte send, output timeout, failed CONNACK and socket close
discard pending output, close the broker socket and use the existing reconnect
backoff. A dropped event at admission does not disconnect. This intentionally
avoids continuing on a stream with an abandoned partial frame: the old
best-effort caller ignored a failed publication send, which could leave the
next packet spliced into that frame. No delivery guarantee or public HTTP
error has been added.

Close, shutdown, network-offline handling and MQTT reconfiguration clear output,
handshake deadlines and pending ping state. Old output cannot reach a replacement
connection. Receive-command storage/ordering is unchanged.

## Evidence And Remaining Work

Host and ASan/UBSan harnesses cover exact capacity, whole-frame rejection,
compaction, short writes, EINTR/EAGAIN, timeout reset, fatal sends, startup
phases, fragmented/rejected CONNACK, subscription boundaries, ordered event and
ping output, incoming commands under output backpressure, and close/disable.
Full-agent tests use a loopback broker, short writes and small real kernel
buffers: health/UI remain responsive when the broker stops reading, frames
remain parseable after it resumes, and no output polling remains after drain.
The final focused selection passed 36 tests across MQTT, HTTP transport and
module budgets. The changed MQTT sources also compiled for ARMHF using the
device sysroot configuration. No full-suite or full release gates were run.

DNS and TCP establishment in `socket_connect_timeout` still run synchronously.
`handle_mqtt_commands` -> `send_mqtt_command_to_device` also retains its separate
DNS/device-socket waits. No recovery-sensitive maintenance transaction or media
lifecycle implementation is changed here. **This closes the MQTT output wait
item, not architecture work 2.7 as a whole.**
