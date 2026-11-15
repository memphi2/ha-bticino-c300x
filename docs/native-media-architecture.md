# Native Media Boundaries

This is an internal source map, not a new public API or media protocol.
`media_bridge.h` remains the caller-facing media lifecycle contract.

## RTSP Framing

`media_rtsp_reader.c` reads one request (including its body) or interleaved
frame from a caller-owned buffer and socket. Only `c300x_media_rtsp_read` is
exported; compaction, filling, consuming and draining remain private helpers.
The buffer structure in its internal header is per connection, not shared
session state. It performs no allocation and creates no background work.

The bridge's client handler still allocates/frees the buffer and retains sole
read ownership. It chooses the same authenticated/unauthenticated, playing and
TEARDOWN deadlines, handles authentication and backchannel dispatch, and closes
the connection. The extraction preserves existing framing results, including
zero-length results after discarding oversized interleaved payloads and the
distinction between an initial idle timeout and a partial-message error.

`media_rtsp_io.c` retains readiness waits and serialized bounded writes.
`media_rtsp_clients.h` retains the existing client-slot helpers; their callers
must hold the bridge mutex. This extraction does not change writer retention,
fd snapshots, client admission, parking, eviction or draining.

## SIP Dialog Messages

`media_sip_dialog.c` owns the stateless ACK, BYE, Home Call CANCEL, Ring Call
BYE and generic OK response senders. Its internal header exposes only those
operations and their existing protocol constants, not bridge internals.
Inputs are borrowed for one synchronous call. These helpers do not read
responses, close sockets, retain dialog state or acquire session locks.

The two-second bounded sender is now `c300x_media_sip_send_all` in
`media_sip_io.c`. Its deadline, nonblocking sends, retry conditions and return
values are unchanged. It still uses the existing writable-wait primitive in
`media_rtsp_io.c`; introducing a generic transport layer is outside this split.
`media_sip.c` owns the shared repeated-header copying helper used by both
generic OK replies and the bridge's Ring Call response builder. Existing
overflow/truncation behavior is intentionally preserved, not hardened here.

Ring Call responses, REGISTER and INVITE remain in the bridge because their
construction interacts with session UUID creation and/or setup decisions.
The bridge also keeps CANCEL/BYE selection and stop-response draining. Thus
moving a sender does not reorder UUID generation, lock acquisition, SIP waits
or shutdown. Header order, branches, CSeq values, fallback URIs, User-Agent,
SDP offers and codec behavior are unchanged.

## Remaining Session Boundary

`media_bridge.c` remains the sole owner of `media_bridge_t`, `g_bridge`, the
lifecycle mutex and bridge mutex. On-demand generation cancellation, Ring Call
and Home Call state, device takeover, worker creation/joining, stop flags,
SRTP state lifetime and socket closure remain together. Moving a protocol
helper does not transfer ownership of any resource passed to it.

SIP setup/registration, UUID caching, SDP/codec policy, RTP relaying, talkback
queues and SRTP/Speex runtime adapters are not redesigned here. Future splits
must establish narrower session ownership contracts first, rather than expose
the entire bridge structure or include fragments of implementation. Existing
lock order, join-before-free rules, retry intervals and media pacing must be
preserved. There are no new timers, idle wakeups or device operations.

## Offline Validation

`test_native_media_protocol_modules.py` links each module without bridge state
and runs socket framing and byte-for-byte dialog regressions normally and with
ASan/UBSan. SIP tests fix wall-clock time only at link time, exercise rejected
messages, repeated-header capacity and a blocked sender's two-second budget.
Symbol contracts limit both modules' exported operations and dependencies.
Existing native lifecycle tests cover authentication deadlines, stop/cancel
races, writer/fd ownership and thread joins with the modules linked normally.
Existing reference-fingerprint and talkback tests remain codec-policy guards.

The production Makefile discovers both sources without a source-list change.
Host/ARMHF compilation, the firmware-sysroot ABI gate and ARMHF stack check
remain required offline checks. No version, build-lock, package, device or HA
runtime change is part of this extraction.
