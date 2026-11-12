# Media Troubleshooting

Start here when the card, camera, Ring Call, Home Call or talkback does not
behave as expected.

First check the `Media readiness` diagnostic entity. Run a shown Repair for
`blocked` or `unavailable`; review a `warning` without assuming media is broken.

## On-demand Stream Shows No Picture

Check:

1. Doorbell camera/video is enabled in the integration options.
2. `Media readiness` is `ready` or has only a Ring Call forwarding warning.
3. No Ring Call capture or other viewer is already using the media path.
4. The browser can reach the same local C300X/HA network path.
5. The card has the C300X camera entity selected.

If the stream was left active by an old browser session, press **Stop** in the
card or call `bticino_c300x.stop_doorbell_video`, then retry.

If this happens directly after updating the native agent or changing display
pages, reload the integration once and re-check `Media readiness`.

## Device Reboots After PCMU On-demand Video

Native agent **2.0.0** includes the correction for undersized PCMU silence packets
associated with [issue #55](https://github.com/memphi2/ha-bticino-c300x/issues/55). When the
microphone is inactive, the agent sends a complete 20 ms frame instead of one
byte. Speex is unchanged; this fix does not patch firmware or add teardown delays.

Three on-device HA-card tests passed without a reboot or firmware-process
restart, including normal 60-second session renewal and at least 180 seconds
of observation after each stop. The issue is closed following this validation;
the reporter's exact cold-boot, short-gap and multi-unit setup has not yet been
retested with the corrected agent.

The fix is included in release 2.0.0. Follow the
[update instructions](advanced-maintenance.md#updates) and verify that the
**native agent**, not just the integration, is version 2.0.0 or newer.
Updating only Home Assistant files does not apply the correction.

Until the corrected agent is installed, use **Speex (stock)** in the **Audio
codec** select as the workaround. Changing the device codec is an explicit
maintenance operation that reboots the C300X. If the reboot returns with the
corrected agent, stop repeating the test, return to Speex and reopen issue #55
with the versions, reproduction steps and sanitized diagnostics.

## Card Shows Stream Instead of Answer

The card can show **Answer** only when Home Assistant receives a real Ring Call.

Check:

1. The **Forwarding** select is set to **Home Assistant**.
2. The Home Assistant media-user setup is ready.
3. The doorbell was rung after changing forwarding mode.
4. `Media readiness` has no `homeassistant_user` or `device_routing` failure.
   The `forwarding_homeassistant` warning specifically explains why Ring Call
   is not answerable from Home Assistant.

In **Smartphone** mode, use the phone route. In **Blocked** mode, Home Assistant
can still receive a ring event but cannot answer the call.

## Preview Starts but Answer Fails

Check:

1. Keep only one active answer attempt.
2. Close stale browser windows with old cards.
3. Confirm that no Ring Call capture automation is running at the same time.
4. Re-check `Media readiness`.
5. Reload the integration if the card was open during an agent update.

## Talkback or Microphone Does Not Work

The normal HA camera player's microphone is optional and **off by default**.
In the integration options, enable **Two-way audio in the HA camera player**
on the features page. This requires Home Assistant 2026.11 or newer,
**Settings > System > Labs > Two-way audio**, a WebRTC stream, HTTPS and browser
microphone permission. See the [Home Assistant requirements](https://contributors.home-assistant.io/core/entities/camera/#two-way-audio).
The integration declares support only when this option is enabled and the agent
explicitly reports talkback and an audio stream.
It uses the existing WebRTC backchannel without additional idle device polling
or an agent update. Card talkback is unaffected by this option. On older
supported HA versions, use the card's microphone.

The native microphone supports on-demand video and already answered Ring Calls.
Continue to answer and hang up incoming calls through the card; opening the
camera or enabling its microphone does not automatically answer a pending call.

Talkback needs browser microphone permission. Use:

- HTTPS,
- Home Assistant Cloud,
- or another secure Home Assistant frontend URL.

Plain HTTP is not a reliable microphone path. In mobile notifications, open the
dashboard and press **Answer** in the card; do not expect a background
notification action to grant microphone access.

The secure browser frontend is independent of device callbacks. Leave callback
transport unchanged unless the C300X needs a different reachable Home Assistant
endpoint; see [Callback URL](advanced-maintenance.md#callback-url).

## Audio Is Too Quiet or Too Loud

Use the integration options before changing automations:

- **Doorstation live audio gain** affects live on-demand and Ring Call audio.
- **Ring capture audio gain** affects Ring Capture output files.
- Both values accept `-20 dB` to `+20 dB`.
- Keep live gain at `0 dB` when the default audio level is acceptable; the
  integration then avoids unnecessary runtime gain updates.

Home Call uses its own media path. Do not tune Home Call volume by changing
Ring Capture gain.

## Home Call Rings but Looks Connected Too Early

Home Call is audio-only and has its own state path.

Check:

1. Use the Home Call card or the `start_home_call` / `stop_home_call` services.
2. Hang up from Home Assistant once if the display was rung but nobody answered.
3. Watch the Home Call active entity and the camera media-state attributes.
4. If the next on-demand stream fails after a Home Call, stop media once and
   re-check Readiness.

## Ring or On-demand Capture Fails

Capture is intended for short automation/analysis clips. The default
`capture_mode: ring` uses an active Ring Call; `capture_mode: on_demand` starts
an idle live view without a doorbell press. See the
[capture example](feature-reference.md#capture-modes).

The message **"The C300X device-agent command failed or is not supported by the
installed agent"** is a general agent-command failure. In `ring` mode,
`include_audio: true` (the default) attempts to answer the Ring Call. Calling it
without a current ring can therefore produce this message even with a compatible
agent. Select `capture_mode: on_demand` for an idle recording. An
`announcement_path` requires `ring` mode and is rejected for on-demand capture
before media starts.

If a call begins while an on-demand recording connects, the native RTSP route can
change after the idle check. The recording may then fail or include Ring video.
This is a limitation of native media routing: the idle check does not lock the media
owner through connection setup. The metadata field `capture_mode` records the
requested mode; it does not continuously verify the native owner. On-demand capture
does not answer or hang up the Ring Call and closes its own recording client on
completion, failure or cancellation.

Check:

1. Select the mode that matches the intended capture. On-demand capture requires
   an idle media path; close your live viewer first. A reported busy, unknown or
   externally owned state is rejected before the recording client opens.
2. Do not run multiple capture automations on the same device at once. Separate
   devices use isolated workspaces; do not assign the same explicit MP4 path.
3. Keep output paths below `/media/c300x/`, `/config/c300x/` or
   `/config/www/c300x/`.
4. Check `/media/c300x/` for the MP4 and `/config/c300x/` for `latest.raw.wav`,
   `latest.processed.wav`, `latest.capture.json`, `frame_01.jpg`,
   `frame_02.jpg` and `frame_03.jpg`.
   These are latest pointers. For automation use the exact paths returned by the
   capture service. Per-recording workspaces expire after one hour on the next
   capture; at most 64 are retained per capture directory.

Ring Capture blueprints retain the default `ring` mode. Use the Ring Capture +
Wyoming blueprint only when audio is enabled. The blueprint always records audio
because transcription needs `latest.raw.wav`.

## Common Log Clues

| Log or symptom | Meaning |
| --- | --- |
| `ring_call_not_active` | There was no answerable Ring Call at that moment. |
| `external_session_active` | Another route/client owns the media session. |
| `rtsp_consumer_active` | A capture or stream tried to start while the path was busy. |
| `go2rtc ... error=EOF` on stop | Usually the provider observed a native RTSP source closing. Treat it as relevant when it repeats during start or leaves the card/session busy. |
| `callback_url` readiness failure | The C300X cannot reach the HA callback URL. |
| Browser microphone unavailable | Use HTTPS/HA Cloud and allow microphone access. |

## What to Include in an Issue

Include:

- Home Assistant version.
- Integration version.
- C300X firmware family.
- Native agent version from diagnostics.
- `Media readiness` state and attributes.
- Whether Forwarding is Smartphone, Home Assistant or Blocked.
- A diagnostics download from the integration.

Do not include tokens, private URLs, packet captures, private media clips or
device-specific media user identifiers.
