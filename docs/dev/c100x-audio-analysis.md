# C100X 1.5.8 Audio Dossier

Scope: C100X 1.5.8, investigated separately from test candidate
`63ee8d575199a0675d6b7efb63dcc871d3794fd7`. All inspection is offline.
The original extracted firmware is a read-only input, not distributed here.
No device, acoustic, microphone, amplifier, or sustained-call result follows
from the tests below. The reviewed safety guards and firmware tests are now
integrated into the C100X branch; no package or issue comment is published here.

Status: **local speaker/TTS unsupported; safety containment implemented**.
The production change blocks incompatible C300X playback/recovery paths;
the existing Speex media path is verified against the original codec library.
Arbitrary local WAV/TTS playback still has the blockers below. The safety
fixes do not implement a local-speaker backend. The selected test-package
scope explicitly excludes local speaker/TTS. Audio investigation continues
separately and must not activate an unverified backend in this package.

## Exact Inputs

Relative paths below are inside `rootfs-c100x-1.5.8`.

| File | SHA-256 |
| --- | --- |
| `home/bticino/bin/bt_av_media` | `5464f8636b9dfc4d0603034c1e7f117b02c86733c77e94bf7b7f4fc0b48a1bb2` |
| `home/bticino/bin/bt_answering_machine` | `cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12` |
| `home/bticino/lib/liblghal.so.0.0` | `f2f4ff4826f01ea84e60a3d98a4f779724f5fd315320d64d6bf1261b44a3947b` |
| `usr/local/bin/Audio_State.sh` | `94f4f9d4f441b907575fc0c30dcf1ebd1259ad96975d0bba3a3e801b70ed85ff` |
| `usr/local/bin/hbi_load_firmware` | `16919ca5796eaba777797ac8bb59240b716f5dac38b8b608af55e1038d05ac4a` |
| `usr/lib/libspeex.so.1.5.1` | `5ff0a400fa72e0bd5038f65e85c8f4a7536e620001df846daa4de5027ca7de3a` |
| `home/bticino/lib/BtObjects/libbtobjects.so` | `5ba83a87368888473a0ec0cd8eab4ea77fe9c4fb4f9deaa37e17c99fdc776dde` |

## Pipelines and Codecs

`etc/linphone.conf`, `[sound]`, uses RTP payload 110, `speex/8000/1`,
loopback local port 5000 and remote port 4000. PCMU/8000 is present but
disabled; Speex/8000 is enabled. Other advertised codec entries are not
evidence of working paths. `stack_open.xml` agrees with `enable_speex=1`.
The existing agent's paired stack/linphone codec checks are appropriate;
changing only one side would not constitute a codec implementation.

Firmware PCMU cannot work on C100X 1.5.8, verified offline:

- `stack_open.xml` has a C100X-only `<sampling_rate>16000</sampling_rate>`;
  `bt_av_media` runs the device-side PCM at 16 kHz.
- The PCMU send pipeline has no resampler (`alsasrc` caps
  `rate=sampling_rate` -> `mulawenc` -> `rtppcmupay`), and GStreamer's
  `rtppcmupay` accepts only `rate=8000`. Under qemu the device's own
  gst-launch fails to negotiate at 16 kHz, so PCMU at 16 kHz cannot exist.
- Setting `sampling_rate` to 8000 does not work either: the ZL38067 is the
  I2S clock master, all DSP profiles run at 16 kHz (`SysSampPerMs=0x0010`)
  and the zl380xx `hw_params` is a no-op, so audio would run at the wrong
  speed.
- A possible workaround would change four files, including a global
  `/etc/asound.conf` plug resampler. It is unproven and not pursued.

Speex/8000 stays the C100X codec; HA and the browser still get PCMU through
the agent's transcode. The C100X guard rejects firmware-PCMU apply in the
core, HTTP API and CLI; capabilities and the HA selector do not offer that
change. Read-only status
remains available. Explicit restore/removal can recover Speex only from a
managed backup pair that passes stock-Speex field validation; missing, partial
or incompatible backups do not authorize writes. Unpatched removal with no
codec backups remains a no-op. These checks validate codec fields, not a full
firmware identity or acoustic result. The agent's PCMU transcode is
distinct from rewriting the stack/linphone configuration.

The same XML's `bt_av_media` section uses a 16000-Hz device sample rate,
640-byte blocks, and 20000/60000 microsecond latency/buffer settings. Device
PCM and negotiated RTP are distinct; this 16 kHz device rate is what rules out
firmware PCMU above.
Stock `ring1.wav` is PCM S16LE, 16000 Hz, two channels.

Media executable string offsets identify separate local WAV and RTP paths:

| File Offset | Evidence |
| --- | --- |
| `0x27824` | WAV recording; ALSA source, WAV encoder, deinterleave |
| `0x27a3c` | WAV playback family |
| `0x27a7c` / `0x27a90` | WAV parser / audio-converter elements |
| `0x27be4` / `0x27bf0` | Local `wav-play` / ALSA sink |
| `0x27cbc` / `0x27fac` | PCMU RTP depayloader / encoder |
| `0x2820c` / `0x2821c` | Speex RTP depayloader / decoder |
| `0x283b0` | Speex RTP send pipeline diagnostics |
| `0x2883c` / `0x28894` / `0x288c4` | Audio stop and both pipeline state changes |

These strings establish available branches, not successful negotiation or
hardware execution. Listen/talkback already has the stock Speex bridge in
the frozen agent. Ring answer/end, SRTP, microphone routing, echo behavior,
packet pacing and teardown still need hardware acceptance.

The ARM/QEMU codec probe calls the production `speex_encode_pcm_frame()` and
`speex_decode_audio_frame()` with this image's pinned `libspeex.so.1.5.1`.
Twenty synthetic frames encode and decode, 160 samples per frame, with output
boundary sentinels intact and nonzero decoded output. This verifies the ABI
and narrowband processing, not RTP negotiation, timing or acoustic fidelity.

## Board and Speaker Controls

`etc/issue` identifies Shark. In the original HAL, `hal_board()` compares
the Shark name at `0x27cc4` and selects board **16** at `0x20668`.
Board 18 is Miura, not C100X: the shared state-dispatch branch alone must
not be used to infer the correct volume table.

The ALSA driver list includes built-in `snd-soc-zl380xx_codec` and
`snd-soc-imx-shark`. The bundled `var/lib/alsa/asound.state` instead carries
older `VOICE`/`ZL0` controls. Factory test scripts referencing an OMAP Baia
board are similarly not evidence for the C100X runtime mixer.

The HAL's `hal_get_audio_state()` at `0x1bd58` selects `Audio_State` for
Shark. `hal_audio_enable_extended()` at `0x1ca9c`, specifically the shared
Shark/Miura dispatch at `0x1d3b0`, supplies the following actual contract:

| Request | Verified Original Behavior |
| --- | --- |
| Local ringtone, enum 9 | Write `Audio_State=7`; call `Audio_State.sh EN_AUDIO_RINGING_LOC` |
| Repeat local ringtone while state 7 | No mixer or command call |
| Off, enum 0, from state 7 | Mute SOUT and ROUT, write state 0, call dispatcher with `EN_AUDIO_OFF` |
| Legacy local-play requests, enums 1 and 3 | Call dispatcher with `FAKE`; HAL still returns success |
| Enum 5 / 7 | State 2 / 3; `EN_AUDIO_PASSTHR` / `EN_AUDIO_PASSTHR_INT` |
| Enum 6 / 11 | State 6 / 1; `EN_AUDIO_RINGING` / `EN_AUDIO_BEEP` |
| Enum 12 / 14 | State 4 / 5; `EN_AUDIO_IP` / `EN_AUDIO_IP_EU` |
| Enum 15 from off | State 8; `EN_AUDIO_STBY` |
| Local ringtone, enum 9, from active IP state 4 or 5 | Overwrites state with 7, loads local-ring profile |
| Off, enum 0, from active IP state 4 or 5 | Mutes both directions, clears state to 0 |
| Standby, enum 15, from state 7 | Sets state 8, loads `EN_AUDIO_STBY` |

The local-ring branch is at `0x1d544`; off is at `0x1d414`. The original
HAL returning zero does **not** prove that its dispatcher configured the DSP.

Shark volume conversion is selected through `get_vol_shark` at `0x3cad0`;
the play-table accessor is `get_vol_play_shark()` at `0x218cc`. At 25 percent,
the actual play-volume call writes DAC2 P ATT=2, DAC2 M ATT=0, AEC ROUT GAIN
Volume=48, then unmutes SOUT and ROUT. The C300X TPA2028D1/ZL0 controls and
linear gain formula are not substitutes. Mute helpers are at `0x21a2c`,
`0x21ae8`, and `0x21ba8`.

`tests/test_c100x_audio_firmware.py` executes this exact library under ARM
QEMU with board identity, mixer writes, command execution and logging
intercepted. No ALSA device is opened and no dispatcher is executed. The
helper is our own observation harness, not copied vendor implementation.
The active-IP overwrite, active-IP mute and local-ring-to-standby results
were also reproduced with an independent review probe. HAL request 9
is not a busy/ownership check, request 0 is not an owner-scoped release,
and the play-volume call does not preserve microphone mute. None is suitable
as an unguarded announcement primitive.

The GUI does not provide evidence for an independent arbitrary-WAV owner:
`Components/RingtoneSelectionItem.qml:79` enables `AudioState.VdeRingtone`
before asking the ringtone manager to play. In `libbtobjects.so`,
`AVDevice::playRingtone()` at `0x24ab24` formats the ringtone-type command
`*7*58#<type>#0#0**##`; `stopRingtone()` at `0x24ad58` sends `*7*55**##`.
The relevant string literals are at `0x3262bc`, `0x3262c8`, and `0x3262d4`.
These commands do not identify an uploaded filename or an agent-owned
playback session. They are not a safe generic TTS start/stop contract.
`SoundPlayer::start()` at `0x1dd47c` instead starts its configured `QProcess`;
it does not establish a separate transactional DSP ownership API.

## DSP Configuration and Stop Hazards

The C300X announcement prerequisites do not exist in this image:
`/bin/zl38005_ioctl-v2` and `microsemi/MEMO_AM_PLAY.cr`. Disabling those
checks or renaming a different profile would falsely advertise support.

The actual dispatcher is `usr/local/bin/Audio_State.sh`. Its revision
selection chooses ZLS38060 below revision 4 and ZLS38067 otherwise. Both
directories contain `EN_AUDIO_RINGING_LOC.cr2.bin`, plus distinct call,
ringing, beep and standby profiles. These are not a memo-play profile.

The dispatcher has three important limitations:

1. Its `/var/tmp/audlock` check followed by `touch` at lines 31-38 is not an
   atomic lock, and there is no signal trap to remove a lock left by a killed
   child. The unknown-argument branch exits at line 82, before lock removal
   at line 85, so the HAL's unsupported `FAKE` request can strand the lock.
2. DSP status probes use registers `0x22` and `0x38`. A cold/unhealthy DSP
   invokes `microsemi_setup.sh force-reload`; that script resets GPIO and
   retries firmware programming without a bounded retry count (dispatcher
   lines 59-71; setup script lines 38-65 and 94-96).
3. The dispatcher's normal final exit is **1**. Conversely, its loader
   helper returns zero without propagating the loader's failure. Neither
   success nor failure can be inferred solely from that exit code (dispatcher
   lines 22-27 and 87).

The Microsemi setup script deliberately powers down on ordinary startup
for the documented carrier workaround. A cold DSP is therefore a real
prerequisite issue, not merely an unusual error case. A bounded adapter
must not silently introduce DSP firmware reloads, GPIO resets, infinite
retries or deletion of someone else's semaphore.

## Vendor-Coordinated Playback Investigation

This bounded follow-up traces original memo, ringtone and GUI playback
entrypoints, not only exported symbol names. Addresses in this section are
ARM virtual addresses. In these two executables, subtract `0x10000` for the
corresponding text/rodata file offset; the referenced shared-library addresses
equal their text/rodata file offsets. Nearest exported labels in stripped
disassembly are not function identities.

### Request, Reply and Completion

`stack_open.xml` configures media command/monitor ports 30007/31007, playback
file `/var/tmp/records/audio.wav`, and fixed ringtone/message locations.
In `bt_av_media`, socket setup calls `g_inet_address_new_loopback` at
`0x36bec`. The receive callback at `0x36794` passes the shared media object
and parsed message to the dispatcher at `0x32cec`; it does not pass a
client-owned playback handle. Handler failure produces OPEN KO at
`0x36808`, success OPEN OK at `0x368e8`. The normal-command success path
also forwards the frame to the monitor socket (`0x32dd0`).

These replies mean command acceptance, not completed playback or an acquired
lease. Socket-close cleanup destroys the client source/socket, not an owned
playback session. The inspected handlers operate on the singleton pipeline
object. The stop routine sends typed completion frames using shared saved
fields: `*7*59#%d#%d#%d*##` and `*7*36#%d#%d*##` (format strings at
`0x37c5c` and `0x38928`). They do not supply owner-scoped cancellation.

### Memo and Configured WAV

The plugin's `AnsweringMachine::playVocalMemo()` at `0xd2dcc` sends memo
action 5; stop at `0xd2d98` sends action 0. The device wrapper at `0x240880`
formats command `87#<action>` into its device frame. The separate file-message
wrapper at `0x23e360` emits `*7*35#<directory>#<id>**##`; its stop at
`0x23ea98` emits `*7*36*##`. None takes an arbitrary uploaded WAV path or
returns a lease to the plugin caller.

There is real higher-level arbitration, which must not be overlooked:
`bt_answering_machine`'s common memo/greeting handler at `0x2a2a4` checks
state 0/12 and a pending timer (`0x2a328` onwards). Its action-5 branch at
`0x2a45c` rejects another timer and existing request-list types 6/11.
An accepted request sets the PlayMemo flag, sends volume dimension 31,
then `*7*35#4#1*##` (`0x2a830`). It appends a type-7 bookkeeping record
containing the returned command ID (`0x2a844` onwards). These are meaningful
busy checks and request tracking, but do not establish atomic arbitration
against every call or a client-owned stop token.

The decisive downstream incompatibility is concrete:

- Media command 35's directory-4 branch at `0x2e974` selects the configured
  WAV, stops existing audio, and builds its WAV pipeline (`0x2e990`). Its
  success path calls **HAL request 3** at `0x3284c`, then sets shared active
  state, volume type 1, and playback.
- Media command 51 at `0x2f4c8` similarly uses the configured local WAV;
  its success branch calls **HAL request 3** at `0x31ccc`.
- The exact original Shark HAL, executed under QEMU with command execution
  intercepted, maps request 3 from idle to `Audio_State.sh FAKE` and returns
  zero. The focused firmware regression now covers requests 1 and 3. No
  dispatcher or DSP operation is executed by this test.

Thus this memo route does not remove the unsupported-profile/semaphore
hazard. An ACK and bookkeeping entry cannot make it a valid C100X DSP path.
The memo stop action chooses global media stop 36 or 55 (`0x2a4bc` onwards),
not a per-caller stop. Record action 1 also deletes record-directory contents
(`0x2a570`); it is not an acceptable way to prepare agent TTS.

### Ringtone and Global Stop

Media command 58 starts at `0x2fb24`. If the shared active flag is already
set, it stops existing audio (`0x2fbc8`) rather than refusing takeover.
The local-source branch calls HAL request 9 (`0x32494`), selects volume
type 2, and reaches the shared volume setter (`0x2fd5c`). It uses configured
ringtone files, not an arbitrary-file queue. This confirms the local-ring
state-overwrite hazard. The type-1 play-volume probe above must not be
mistaken for a separate measurement of this type-2 volume branch.

Command 55 at `0x2f9d8` disables audio routes and calls the common stop
routine (`0x1d7c4`). That routine sets **both** shared audio pipelines to
GStreamer NULL (`0x1d824` onwards), frees them and chooses HAL 15 or HAL 0
according to shared state. There is no caller/token comparison. Command 36
at `0x30194` also invokes common stop, then HAL 0 (`0x301c4`). Neither is
safe cancellation for a separate announcement owner that may have lost
priority to a call.

### GUI Sound and Beep

`SoundPlayer` uses a shared QProcess: start at `0x1dd47c`, play/replacement
at `0x1dd7f8`, stop at `0x1dc4e8`. Its audio-state-change callback at
`0x1dc5d4` stops playback. This is an in-process coordination hook, not an
established external queue/lease API; enabling the gated GUI is not a fix.

The original HAL's beep entrypoint at `0x1ea88` refuses states above 1,
then requests profile 11 and changes controls. Beep-off at `0x1eaf0` checks
for state 1 and requests off. These checks do not establish atomic ownership,
and the same DSP dispatcher can perform unbounded initialization. A short
tone is not evidence of a safe arbitrary-WAV or TTS mechanism.

Independent firmware review additionally reports that BEEP is closest to an
output-only profile but still shares DAC2/AECRX and changes global DSP state;
RINGING_LOC shares call resources and has nonzero microphone/send settings.
Those profile-window results are reviewer evidence, not a runtime PCM test
by this worktree. No independent PCM topology has been established from the
available kernel/DT/runtime artifacts. Factory OMAP scripts do not close
that gap.

**Result:** no safe original playback queue was established among these
traced entrypoints. This is not a proof that every firmware IPC endpoint is
absent. It is a concrete rejection of memo/WAV, ringtone/global stop and
GUI/beep as currently evidenced agent primitives. No alternative backend,
vendor patch, persistent file replacement or physical activation is added.
The follow-up firmware suite passed all 19 cases, including request 3;
Python lint and diff-whitespace checks passed. No full gate was run.

## Priority and Recovery Requirements

Door ringing, answering, local intercom and talkback take priority over
announcements. The existing announcement loop observes bus frames, kills
the entire playback process group and holds off after ringing. Its C300X
cleanup writes `Zia_Aud_St`, ZL0 gain/mute and TPA volume; that cleanup must
not run on C100X, including agent restart and leftover-upload recovery.
OPEN-frame preemption alone is not evidence that all SIP-driven state
transitions are observed before a local mixer write. This remains an explicit
gap, even with the existing host preemption tests passing.

C100X requires its own lifecycle, not just different start commands:
bounded preparation, explicit hardware prerequisites, vendor audio-state
revalidation, owned recovery material, call-aware stop, and cleanup that
does not overwrite a new vendor call's controls. The vendor semaphore
and DSP initialization hazards above remain constraints on that design.
Notify speech must use the same announcement owner as TTS/media-player
playback. A display notification must not bypass the closed GUI gate.

## Confirmed Recovery Bug and Containment

Severity: P2, conditional recovery hazard, **not automatic playback on a clean
first installation**. `c300x_announce_take_over()` schedules mixer cleanup
when an upload survives a previous process. This bypassed HTTP capability
checks. A C100X host lab with the legacy DSP tool absent reported
`supported=false`, yet a leftover upload caused the C300X cleanup script to
write `ZL0 Mute Rout` and `TPA2028D1 Volume`. Real C100X controls differ, so
actual hardware writes/failures are not inferred from the mock mixer.

A second case showed that merely supplying the C300X tools/profile made the
same detected C100X advertise `supported=true`. That is not stock firmware's
default, but it allowed incompatible playback to be exposed accidentally.

The model guard now rejects C100X in capability reporting and the direct
play entrypoint, and cancels the incompatible cleanup before spawning any
worker. C100X startup also skips legacy worker discovery/termination: an
unsupported backend cannot establish safe ownership of those process groups
and their descendants. Old uploads are discarded, never replayed. C300X
worker recovery and GUI gating are unchanged.
`tests/test_native_c100x_announce_guard.py` reproduces both baseline failures
through the real host agent HTTP/startup lifecycle, using synthetic tools.

Independent review found a further P2 containment gap in the first guard:
takeover called `c300x_announce_end_leftover()` before its model check.
Isolated synthetic playback and cleanup process groups both exited with
SIGKILL (`-9`) while C100X reported `supported=false`, with no mixer writes.
This proves an unwanted legacy-worker kill, **not a vendor-process kill**.
The scanner recognizes UID, process-group leadership, argv marker and upload
path; it does not verify descendant behavior. The model check now precedes
that scanner. Both synthetic groups must survive startup and shutdown; only
the test harness terminates its own groups afterwards.
The two remnant tests failed before this correction and passed afterwards.
The focused follow-up passed all four C100X guard cases and both selected
C300X leftover-worker recovery cases (six tests); the module budget passed.

## Offline Reproduction

Use an independent temporary test/build directory, not another worktree's
build output. The firmware fixture reads `rootfs-c100x-1.5.8` from the existing
private firmware workspace. Firmware/QEMU tests explicitly skip when those
optional local inputs are absent; a skip is not compatibility proof.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -o addopts='' -p no:cacheprovider \
  --basetemp=/var/tmp/c100x-audio-focused-review \
  tests/test_c100x_audio_firmware.py tests/test_native_c100x_announce_guard.py
```

Run `tests/test_native_announce.py` separately for the existing C300X speaker
lifecycle. The probes do not open ALSA, launch the vendor dispatcher, load
DSP profiles, or communicate with a device. Proprietary binaries and config
tables stay outside the repository.

Recorded results on this sidecar: the two containment regressions failed
against the frozen baseline, then passed with the guard. The final focused
run passed 20 C100X tests; six existing C300X playback/stop/restart/missing-tool
and missing-event tests also passed against the final production change.
The extracted-module resource budget and Python lint checks passed. Both
modified production modules also cross-compiled with ARM warnings-as-errors.
No full gate was run and no device result is implied.

After integration, 46 focused checks passed: four C100X lifecycle guards,
19 original-firmware/QEMU cases, two C300X leftover-worker recovery cases,
and 21 provenance/resource-budget checks. No firmware case was skipped.
The combined full gate must verify the selected package without local
speaker/TTS before distribution; these focused results do not replace it.

## Unresolved Implementation Blockers

- A bounded cold-DSP startup path must be established for both supported DSP
  revisions. Refusing cold DSP is safe but would not implement normal startup
  on affected carrier boards. Calling the vendor reset/retry loop is not a
  bounded solution.
- Playback needs an ownership protocol that survives stop/crash and yields
  to vendor calls. `Audio_State=7` alone is not proof of agent ownership,
  and a check followed by a mixer write cannot exclude a concurrent call.
  No stale gain/profile restoration may overwrite a new vendor session.
- No arbitrary-WAV vendor API with owner-scoped cancellation has been
  established. Do not replace stock ringtone files, enable the GUI, remove
  foreign semaphores, or fake legacy prerequisites to obtain playback.
- Stock 16-kHz stereo WAV playback does not establish the physical result
  of HA's 8-kHz mono announcements, safe volume limits, or microphone
  isolation. Those require separate bounded-path and hardware evidence.

## Hardware Acceptance Bounds

No physical test is authorized by this dossier. Installing the combined
test package must not enable local announcements or the GUI, start a stream,
answer a call, play a startup sound, or run DSP recovery automatically.
After installation, a separately authorized read-only check should show
`GET /api/v1/announcements` returning `supported=false`; stop if it instead
advertises support.
Do not create missing C300X tools/profiles to bypass this condition.

Only after the implementation blockers are resolved and reviewed, and a
separate physical test is authorized, record firmware/HAL identities, board
revision, real ALSA control names/ranges, PCM format constraints, idle
state and DSP status. Do not program or reset the DSP just to make a
prerequisite check pass. Start with a quiet, short local WAV at low volume,
with recovery access and a person at the unit. Check normal completion,
explicit stop, failure during preparation, agent restart, and cleanup
before progressing to TTS.

Then test ring arrival during preparation/playback/cleanup, call answer,
talkback, caller hangup and rejected/failed call setup. Verify normal vendor
ringing and both speech directions afterwards, no retained semaphore or
player, restored idle state, no unexpected microphone feed, no persistent
gain/config changes and no restart loop. Cold-start behavior and both DSP
hardware revisions require separate evidence. Acoustic quality and volume
limits cannot be certified by firmware inspection or QEMU.
