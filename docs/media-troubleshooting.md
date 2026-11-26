# Troubleshooting

Start here when the card, camera, Ring Call, Home Call or talkback does not
behave as expected. Check **Media readiness** first. The entries apply to the
Classe 300X and the Classe 100X; [Classe 100X](#classe-100x) collects what
only happens there.

## Media Readiness

The `Media readiness` diagnostic sensor combines the agent connection, the
agent's self-test, the media user and the callback into one state. Forwarding
is reported separately: it chooses where an incoming Ring Call goes but does
not gate on-demand video.

| State | Meaning | What to do |
| --- | --- | --- |
| `ready` | Required media checks passed. | Use the card. |
| `warning` | No blocking failure, but not everything is proven. | Read `warnings`; forwarding and optional IPv6 warnings can usually stay. |
| `blocked` | A required media prerequisite failed. | Open the Repair and run its fix. |
| `unavailable` | Home Assistant cannot reach the agent. | Check network, address, keys and agent. If the station's address changed, see [Station Changed Its Address](#station-changed-its-address). |

### Attributes

`failed_checks` lists the blocking checks and `warnings` the non-blocking
ones; `recommended_action` is the code Repairs and diagnostics use. Single
results: `agent_reachable`, `agent_version_ok`,
`media_user_ok` (media user and routing), `rtsp_ok`, `talkback_rtp_ok` and
`callback_url_ok`. `forwarding_homeassistant` is `true` when Ring Calls go to
Home Assistant; `false` does not block on-demand video.
`ring_call_supported`, `home_call_supported` and `doorbell_video_supported`
show what the installed agent offers.

### Failed Checks

| Check | Typical cause | Fix |
| --- | --- | --- |
| `agent_reachable` | Agent offline, wrong address or port, rejected key, device rebooting. | Check reachability and keys; restart or update the agent. |
| `capabilities` | The agent answered without usable media features. | Update or reconfigure the agent. |
| `firewall` | Required IPv4 media ports are closed on the station. | Run the firewall Repair. |
| `rtsp` | RTSP server or stream configuration not ready. | Update or reconfigure the agent, then check readiness again. |
| `talkback_rtp` | Talkback RTP port closed or not ready. | Run the firewall Repair. IPv6 is optional. |
| `homeassistant_user`, `device_routing` | Media user missing, or its route files incomplete. | Run the Home Assistant media-user setup. |
| `callback_url` | The callback address is unreachable or unsuitable. | Set a reachable `http` or `https` address; HTTPS needs a trusted certificate matching the host name. See [Callback URL](advanced-maintenance.md#callback-url). |
| `startup` | The agent's startup link is missing. | Run the agent update or Repair. |

### Warnings

| Warning | Meaning |
| --- | --- |
| `forwarding_homeassistant` | Forwarding is not set to Home Assistant, so Ring Calls cannot be answered in HA. On-demand video, its talkback and Home Call still work. |
| `forwarding_unprovisioned`, `forwarding_unknown` | The station reports forwarding as not provisioned, or it has not been read yet. |
| `<check>:optional_ipv6` | Only the optional IPv6 part of that check failed. |
| `callback_url_unknown`, `self_test_not_loaded` | The callback or the self-test has no result yet. |
| `media_capabilities_missing` | Video is on, but the agent reports no media feature. |

Keep **Forwarding** on **Smartphone** when the Door Entry app should receive
calls; choose **Home Assistant** only when Ring Calls should be answered in HA.
A Repair never changes forwarding.

### Repairs

When readiness is not `ready` and a known safe fix exists, Home Assistant
raises a Repair. It can re-check the agent, refresh its setup data, open the
IPv4 media firewall, repair the media user and routing, or guide you to a
reachable callback address. Repairs run only when you start them. After one
that changes the station, wait for it to finish and check readiness again
before testing the card.

IPv6 is optional. Enable IPv6 firewall support only when Home Assistant
reaches the station over stable IPv6.

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

## On-demand Stream Shows No Picture

Check:

1. **Door station video and audio** is on under **Configure > Video and
   audio**.
2. Media readiness is `ready`, or `warning` with only a forwarding warning.
3. No Ring Call capture or other viewer is using the media path.
4. The browser reaches Home Assistant and the station over the same local
   network path.
5. The card has the C300X camera entity selected.

If an old browser session left the stream running, press **Hang Up** in the card
or call `bticino_c300x.stop_doorbell_video`, then retry. Directly after an
agent update or a change of the display pages, reload the integration once and
check readiness again.

## Card Shows Stream Instead of Answer

The card shows **Answer** only when Home Assistant receives a real Ring Call.

Check:

1. The **Forwarding** select is **Home Assistant**.
2. The Home Assistant media user is set up.
3. The doorbell was rung after forwarding was changed.
4. Media readiness has no `homeassistant_user` or `device_routing` failure.
   The `forwarding_homeassistant` warning means Ring Calls cannot be answered
   from HA.

With **Smartphone**, use the phone. With **Blocked**, HA still receives the
ring event but cannot answer.

If diagnostics report `unsupported_active_route`, the station's active routing
file is not one of the known manufacturer links, and the media-user setup
leaves it untouched. Keep any third-party configuration and report the redacted
error; do not replace the route with a stock file or run the setup repeatedly.

## Preview Starts but Answer Fails

1. Keep only one answer attempt active.
2. Close stale browser windows with old cards.
3. Make sure no Ring Call capture automation runs at the same time.
4. Check Media readiness again.
5. Reload the integration if the card was open during an agent update.

## Talkback or Microphone Does Not Work

The browser must allow the microphone, which needs a secure Home Assistant
frontend: HTTPS, Home Assistant Cloud or another secure URL. Plain HTTP is not
a reliable microphone path. From a phone notification, open the dashboard and
press **Answer** in the card; a notification action cannot grant microphone
access. The secure frontend is independent of the station's callbacks; leave
the [Callback URL](advanced-maintenance.md#callback-url) as it is.

Talking through the native HA camera view is off by default. It needs
**Talk through the Home Assistant camera view** under **Configure > Video and
audio**, Home Assistant 2026.11 or newer, **Settings > System > Labs > Two-way
audio**, WebRTC, HTTPS and microphone permission (see the
[Home Assistant requirements](https://contributors.home-assistant.io/core/entities/camera/#two-way-audio)).
It never answers a call: answer in the card first. Details:
[Live Picture and Talkback](user-guide.md#live-picture-and-talkback).

## Audio Is Too Quiet or Too Loud

Adjust **Door level** and **Fine adjustment (dB)** under **Configure > Video
and audio** before changing automations. They apply to the live view, Ring
Calls and Ring Capture recordings alike. Too quiet: raise the door level
first. Too loud or harsh: lower the door level or set a negative fine
adjustment. Home Call has its own audio path; these options do not change it.
The diagnostics show under `audio_level` whether the station's audio chip or
the agent's software applied the door level in the last audio.
For clearer sound use the PCMU codec. See
[Codec and Audio Levels](user-guide.md#codec-and-audio-levels).

## Device Reboots After PCMU On-demand Video

This applies to the Classe 300X; the Classe 100X has no PCMU switch.

The current agent fixes the reboots reported in [issue #55](https://github.com/memphi2/ha-bticino-c300x/issues/55).
If a PCMU stream still reboots the station, stop testing, set **Audio codec**
back to **Speex** (this reboots the station once) and report it with versions
and diagnostics.

## Picture Is Blurry, Cut Off or Jerky

Picture size, bit rate and frame rate are set under **Configure > Camera
quality**; what each value does is in
[Camera Quality and Picture Size](user-guide.md#camera-quality-and-picture-size).

| Symptom | What to try |
| --- | --- |
| Blurry or blocky | Raise the bit rate; lower it again if a weak network shows stalls or grey blocks. |
| Jerky | Raise the frame rate. High video stops at 24 fps; 25 is not offered. |
| Cut off at top and bottom | 688x480 is the factory cut-out; 704x576 shows the full height. |
| 960x576 not offered | It needs the exact verified media program of firmware 1.7.19 or 2.0.2. This is intentional; do not force it through edited settings. |
| No change after saving | Changes apply after the normal device reboot; restarting HA, the agent or the display is not enough. Wait for the reboot and open a new stream; the form shows saved and running values. |
| Restoring reports a missing or invalid backup | Keep the recovery files and solve the error before retrying; see [Recovery](advanced-maintenance.md#recovery). |
| Visitor image has bars or looks squeezed | Snapshots read the 800x480 display, so other proportions (for example 720x480) distort the image and the card shows bars. Set **Configure > Visitor Snapshot** to 800x480 or 400x240 and check a **new** capture; saved images are not resized. |

## Home Call Rings but Looks Connected Too Early

Home Call is audio-only and has its own state.

1. Use the Home Call card or `start_home_call` / `stop_home_call`.
2. If the display rang but nobody answered, hang up from Home Assistant once.
3. Watch the **Home call active** entity and the camera's media-state
   attributes.
4. If the next on-demand stream fails after a Home Call, stop media once and
   check readiness again.

## Ring or On-demand Capture Fails

Modes, files and the response are described in
[Recording Clips and Capture Modes](user-guide.md#recording-clips-and-capture-modes).

- **"The C300X device-agent command failed or is not supported by the installed
  agent"** is a general command failure. In `ring` mode with
  `include_audio: true` (the default) the action answers the Ring Call, so
  without a current ring it fails even with a compatible agent. Use
  `capture_mode: on_demand` for an idle recording. `announcement_path` needs
  `ring` mode.
- On-demand capture needs idle media: close your live view first. A busy,
  unknown or externally owned state is rejected before recording. A call that
  starts while the recording connects can make it fail or record ring video.
- Run one capture per device at a time. Separate devices use separate
  workspaces; do not give them the same explicit MP4 path.
- Output paths must be below `/media/c300x/`, `/config/c300x/` or
  `/config/www/c300x/`. MP4 files go to `/media/c300x/`; WAV, JPEG frames and
  metadata to the workspace under `/config/c300x/`. The `latest.*` files only
  point to the most recent capture; automations should use the paths the action
  returns.
- The Ring Capture + Wyoming blueprint always records audio, because
  transcription needs the WAV.

## Station Changed Its Address

When the station gets a new IPv4 address, for example from DHCP, Home Assistant
follows it without your help:

1. Home Assistant renews its connection every 5 minutes. After 15 minutes
   without an authenticated request from it, the station announces itself
   again on the network (mDNS). When its IPv4 address changes, it reopens the
   announcement on the new address.
2. Home Assistant sees the announcement and asks the station at the new
   address to prove that it holds the saved access key. The request carries
   only a fresh random value; the key is never sent to the new address.
3. When the proof matches, the entry moves to the new address and reloads.
   Nothing moves while the station still proves itself at the old address.

Expect up to about 15 minutes until the station announces itself, plus the
time Home Assistant needs to pick it up; meanwhile Media readiness shows
`unavailable`. Home Assistant tries at most once every 10 minutes per entry.
When the station did not answer, Home Assistant tries again up to two more
times, 10 minutes apart. A station that fails the proof is ignored, and the log
warns that it "did not prove the saved identity".

Enter the new address yourself with **Reconfigure** (**Settings > Devices &
services > BTicino C300X**, entry menu) when:

- the entry uses a host name or an IPv6 address (only IPv4 entries move, and
  only to an IPv4 announcement);
- the entry has no station ID, or its access key is shorter than 32
  characters;
- **Agent mDNS discovery** is off, or the announcements do not reach Home
  Assistant;
- the log shows the failed proof: check that it is your station and that the
  access key is right;
- you do not want to wait.

A DHCP reservation for the station avoids address changes.

## Agent Update or Removal Reports an Error

Do not delete recovery files or force the operation past the error. Follow
[Recovery](advanced-maintenance.md#recovery).

## Classe 100X

The Classe 100X on firmware 1.5.8 is in test in
[issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51). Report
what you see there, with the details in [What to Attach](#what-to-attach) and
the [Classe 100X notes](c100x-experimental.md#how-to-report).

### Setup or Update Names the Wrong Model

| Message | Meaning |
| --- | --- |
| **This package does not support this station** | A Classe 100X met a package that is not made for it, or the station's model could not be confirmed. No device files were replaced. |
| `unsupported_active_route` | The station's active SIP route is not one of the stock route files, for example after BTicino Companion. Nothing was written; video and calls cannot be set up on that station. |

### Classe 100X Display Pages

| Symptom | What to do |
| --- | --- |
| No display settings, **Ringer mute** or **Touch tone** | Expected until the [display activation](display.md#classe-100x-activation-by-reboot) is confirmed. Press **Activate display pages**. |
| The activation waits and does not reboot | The agent reboots only with its maintenance reboot on, once the station has been idle for about two minutes and no call, stream or announcement runs. A call postpones it. |
| Repairs: **C100X display pages were rolled back** | The pages did not start in the boot after the activation, so the station went back to its original display at the next start. Nothing else changed. Press **Activate display pages** again; if it rolls back again, report it with the agent diagnostics. |
| Repairs: **C100X display check failed at the station start** | The agent could not check a pending activation when the station started, for example after a firmware update or with a missing display package. The agent runs; the activation stays off and the original pages' backups stay. Press **Restore original display**; if that fails, update the agent with its Repair first. |
| A notification with `sound_duration`, `tts` or `led` is refused | The C100X display plays no tone, and the station has no speaker backend or message LED. Send `display` without `sound_duration`. |
| No **Reload device display** button | Expected: the C100X display program cannot be restarted. |

## Reporting an Issue

### Log Clues

| Log or symptom | Meaning |
| --- | --- |
| `ring_call_not_active` | There was no answerable Ring Call at that moment. |
| `external_session_active` | Another route or client owns the media session. |
| `rtsp_consumer_active` | A capture or stream tried to start while the path was busy. |
| `go2rtc ... error=EOF` on stop | Usually the native RTSP source closing. Relevant when it repeats during start or leaves the card busy. |
| `callback_url` readiness failure | The station cannot reach the HA callback address. |
| Browser microphone unavailable | Use HTTPS or HA Cloud and allow the microphone. |

### What to Attach

Open an issue at <https://github.com/memphi2/ha-bticino-c300x/issues> with:

- Home Assistant version and integration version,
- station model (C300X or C100X), firmware and the agent version from
  diagnostics,
- Media readiness state and attributes,
- the **Forwarding** setting (Smartphone, Home Assistant or Blocked),
- a diagnostics download of the integration,
- the relevant log lines.

Do not include keys or tokens, private URLs, packet captures, private media
clips or device-specific media user identifiers.
