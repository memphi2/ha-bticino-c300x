# Media Troubleshooting

Start here when the card, camera, Ring Call, Home Call or talkback does not
behave as expected.

First check the `Media readiness` diagnostic entity. If it is not `ready`, run
the shown Repair before changing card YAML or automations.

## On-demand Stream Shows No Picture

Check:

1. Doorbell camera/video is enabled in the integration options.
2. `Media readiness` is `ready`.
3. No Ring Call capture or other viewer is already using the media path.
4. The browser can reach the same local C300X/HA network path.
5. The card has the C300X camera entity selected.

If the stream was left active by an old browser session, press **Stop** in the
card or call `bticino_c300x.stop_doorbell_video`, then retry.

If this happens directly after updating the native agent or changing display
pages, reload the integration once and re-check `Media readiness`.

## Card Shows Stream Instead of Answer

The card can show **Answer** only when Home Assistant receives a real Ring Call.

Check:

1. The **Forwarding** select is set to **Home Assistant**.
2. The Home Assistant media-user setup is ready.
3. The doorbell was rung after changing forwarding mode.
4. `Media readiness` has no `forwarding_homeassistant`, `homeassistant_user` or
   `device_routing` failure.

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

Talkback needs browser microphone permission. Use:

- HTTPS,
- Home Assistant Cloud,
- or another secure Home Assistant frontend URL.

Plain HTTP is not a reliable microphone path. In mobile notifications, open the
dashboard and press **Answer** in the card; do not expect a background
notification action to grant microphone access.

## Home Call Rings but Looks Connected Too Early

Home Call is audio-only and has its own state path.

Check:

1. Use the Home Call card or the `start_home_call` / `stop_home_call` services.
2. Hang up from Home Assistant once if the display was rung but nobody answered.
3. Watch the Home Call active entity and the camera media-state attributes.
4. If the next on-demand stream fails after a Home Call, stop media once and
   re-check Readiness.

## Ring Call Capture Fails

Capture is exclusive. It is meant for short automation/analysis clips, not for
normal live viewing.

Check:

1. Close the live card before capture.
2. Do not run multiple capture automations at once.
3. Keep output paths below `/media/c300x/`, `/config/c300x/` or
   `/config/www/c300x/`.
4. Check `/media/c300x/` for the MP4 and `/config/c300x/` for `latest.raw.wav`,
   `latest.processed.wav`, `latest.capture.json`, `frame_01.jpg`,
   `frame_02.jpg` and `frame_03.jpg`.

Use the Ring Capture + Wyoming blueprint only when audio is enabled. The
blueprint always records audio because transcription needs `latest.raw.wav`.

## Common Log Clues

| Log or symptom | Meaning |
| --- | --- |
| `ring_call_not_active` | There was no answerable Ring Call at that moment. |
| `external_session_active` | Another route/client owns the media session. |
| `rtsp_consumer_active` | A capture or stream tried to start while the path was busy. |
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
