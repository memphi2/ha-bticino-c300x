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

`test_native_media_protocol_modules.py` links the reader without bridge state
and runs socket framing regressions normally and with ASan/UBSan. A symbol
contract limits its exported entry point and dependencies. Existing native
lifecycle tests cover authentication deadlines, stop/cancel races, writer/fd
ownership and thread joins with the extracted reader linked normally.
