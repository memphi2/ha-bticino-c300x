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

## Connection Paths for the Live Picture

During setup, or under **Configure > Video and audio**, **Connection paths for
the live picture** selects which ICE addresses the HA WebRTC provider may send
to the browser. Use it when video cannot connect or freezes on a multi-VLAN or
dual-stack network. Start with the default: **IPv4 and local IPv6 (ULA) -
recommended** (`prefer_ipv4_ula`). You select a policy; no address or token needs
to be entered in this field.

| UI choice | Stored value | Non-relay address groups removed | When useful |
| --- | --- | --- | --- |
| All addresses | `all` | None | When your network needs an address excluded by another policy, or to compare without filtering. |
| Without link-local addresses (fe80::, 169.254.x.x) | `drop_link_local` | IPv4 link-local; IPv6 link-local | Keep other IPv6 paths, but exclude addresses that normally cannot cross subnets. |
| IPv4 and local IPv6 (ULA) - recommended | `prefer_ipv4_ula` | IPv4 link-local; IPv6 link-local; Other IPv6 | Default for IPv4/ULA networks; excludes changing or unroutable non-ULA IPv6 paths. This filters candidates, not their priority. |
| IPv4 only | `ipv4_only` | IPv4 link-local; IPv6 link-local; Other IPv6; IPv6 ULA | Diagnose a network whose usable direct media path is IPv4. The exceptions below still apply. |

IPv4 link-local means `169.254.0.0/16`; IPv6 link-local means `fe80::/10`.
IPv6 ULA means `fc00::/7`. **Other IPv6** is the code's category for every
remaining IPv6 address, not just globally routable ones. IPv4-mapped IPv6
addresses are classified by their embedded IPv4 address. Other IPv4 addresses
are kept by all four policies.

The filter preserves **TURN relay candidates**, **mDNS `.local` candidates**,
unknown addresses and unparseable candidate lines under every policy. It does
not resolve mDNS names to enforce a family restriction. Consequently, **IPv4
only is not a guarantee of an IPv4-only connection** or a firewall policy.

Filtering applies to provider-to-browser candidates, including candidates in
the answer SDP and later trickled candidates. Browser-to-provider candidates
are not filtered. It does not change the C300X IP address, RTSP transport,
callback HTTP/HTTPS setting, firewall or codec, and saving this setting does not
install a device patch. Save the selected policy, close the old stream and open
it again to compare the result. If the change removes your only working path,
restore the previous choice; do not change device firewall/codec settings as an
automatic follow-up.

Implementation reference:
[`webrtc_ice_filter.py`](../custom_components/bticino_c300x/camera_media/webrtc_ice_filter.py),
[`const.py`](../custom_components/bticino_c300x/const.py), and
[`test_webrtc_ice_filter.py`](../tests/test_webrtc_ice_filter.py).

## Picture Is Blurry, Cut Off or Jerky

**Configure > Camera quality** distinguishes the saved settings from the ones
the device runs with. The original **688x480** factory cut-out and **704x576**
full-height choice remain available. Optional **960x576** preserves the
configured **704x576** crop's 576 lines and scales it before the existing
encoder to match the **800x480 LCD's 5:3** proportions. This is not additional
transcoding or native 960-pixel camera detail.

The option requires an exact verified C300X firmware **1.7.19 or 2.0.2** media
executable, checked against the matching full-file original/patched hash pair.
Live video is device-tested on 1.7.19; 2.0.2 is checked offline only.
Its absence on other firmware or an unrecognized binary is intentional;
do not force it through manually edited settings. Firmware 3.0.x/Qt5 and its
low stream are unchanged. Applying the patch requires a verified original
backup. Returning to 688x480 or 704x576 restores the original binary and the
selected legacy configuration. Both directions use a **normal device reboot**;
restarting only HA, the agent or the GUI is not sufficient. If restoration
reports invalid or missing backup data, retain the recovery files and resolve
the error before retrying. See [Camera quality](feature-reference.md#camera-quality).

If agent removal reports a failed read-only remount but confirms that the
original startup entries were restored, the agent and backups are retained.
The agent may already be stopped; retained files do not mean it is still running.
Perform a full device reboot, then retry removal. A startup rollback error
instead requires restoring the reported recovery files before rebooting;
do not delete those files or force removal past the error.

Removal first requires verified agent termination. If that fails, it does not
start restoring or deleting files. A later partial-deletion error is different
from a read-only remount failure: retain the reported recovery directory and
remaining backups, repair the agent installation, then restore its startup
entries before rebooting. The recovery directory does not contain copies of
deleted agent files; an incomplete installation is not automatically re-enabled.

For snapshot shape, use **Configure > Visitor Snapshot**. Its default is
**800x480**, read from the native display framebuffer; a 960x576 stream does not
make snapshots 960x576. Existing explicit settings such as 688x480 are preserved.
Choose 800x480, or 400x240 for a smaller 5:3 image, for future captures. Already
saved images are not resized. The card fits images without cropping; a custom
image with different proportions can have bars. A cached old live-stream ratio
is replaced when a new live stream reports its dimensions.

A higher bit rate can reduce compression artifacts, and up to **24 fps** can
make high video smoother. 25 is not offered for high video: older firmware then
turns its frame-rate control off and sends only about 8 fps. After saving, wait
for the normal device reboot before comparing a new stream. If a weak network
shows stalls or grey blocks, lower the bit rate again. The live result does
not establish the resolution of built-in answering-machine recordings;
**960x576 recording there remains unverified**.

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

The fix is part of the packaged agent. Follow the
[update instructions](advanced-maintenance.md#updates) so the device runs it;
updating only Home Assistant files does not apply the correction.

If a PCMU stream still reboots the C300X, stop repeating the test, switch the
**Audio codec** select back to **Speex** and reopen issue #55 with the
versions, reproduction steps and sanitized diagnostics. Changing the device
codec is an explicit maintenance operation that reboots the C300X.

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

If diagnostics report `unsupported_active_route`, the active routing file is
not one of the recognized manufacturer symlinks. Media-user setup leaves it
untouched. Preserve any third-party configuration and report the redacted error;
do not replace the route with a stock file or repeatedly run setup to force it.

## Preview Starts but Answer Fails

Check:

1. Keep only one active answer attempt.
2. Close stale browser windows with old cards.
3. Confirm that no Ring Call capture automation is running at the same time.
4. Re-check `Media readiness`.
5. Reload the integration if the card was open during an agent update.

## Talkback or Microphone Does Not Work

The normal HA camera player's microphone is optional and **off by default**.
In the integration options, enable **Talk through the Home Assistant camera view**
under **Video and audio**. This requires Home Assistant 2026.11 or newer,
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

- **Live audio level (dB)** affects live on-demand and Ring Call audio.
- **Volume of ring recordings (dB)** affects Ring Capture output files.
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
   `latest.capture.json`, `frame_01.jpg`,
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
