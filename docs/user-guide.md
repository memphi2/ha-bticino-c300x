# User Guide

Use this page as the entry point after installing the integration.

## Recommended Path

```text
Install integration -> add device -> install/update agent -> check Media readiness
-> add the C300X card
```

Most users only need:

1. [Quickstart](quickstart.md)
2. [Feature reference](feature-reference.md)
3. [Media readiness](media-readiness.md)
4. [Media troubleshooting](media-troubleshooting.md)

## Common Tasks

| Task | Read |
| --- | --- |
| First installation | [Quickstart](quickstart.md) |
| Update the integration, agent or card | [Updates](advanced-maintenance.md#updates) |
| See all entities, services, options and device writes | [Feature reference](feature-reference.md) |
| Check why Answer, Talkback or Home Call does not work | [Media readiness](media-readiness.md) |
| Fix stream/call/capture problems | [Media troubleshooting](media-troubleshooting.md) |
| Add notification or capture automations | [Blueprints](blueprints.md) |
| Set up native display pages, tiles and Alarmo | [Display setup](quickstart.md#9-optional-native-display) |
| Save visitor images and control retention | [Visitor images](feature-reference.md#visitor-images) |
| Browse saved HA images and videos in the card | [Media history](visitor-journal.md) |
| Upgrade from 2.3.0 or 2.1.3 | [Upgrade guide](advanced-maintenance.md#updates) |
| Update, remove or repair the device agent | [Advanced maintenance](advanced-maintenance.md) |

## Daily Use

- **Save images** enables automatic visitor images independently of an open
  dashboard, on doorbell rings and HA video streams. Size, delay, retention and
  the date and time in the image are configured under **Configure > Visitor
  Snapshot**; defaults are 688x480,
  3 seconds, 14 days and date and time on. Images and their shared camera/card preview are
  stored in HA, not on the C300X. See [Visitor images](feature-reference.md#visitor-images).
- **Better camera picture:** the factory stream is modest (688x480, 800 kbit/s,
  15 fps). **Configure > Camera quality** makes it sharper, smoother and
  wider: up to the whole camera picture at 704x576, 3000 kbit/s and 24 fps. On firmware 3.0.x
  it sets the low-resolution stream, the only one the device sends, which the
  Door Entry app receives as well. The device reads these values only when it
  starts, so saving a change restarts it once (about a minute). Removing the
  agent puts the original values back. See
  [Feature reference](feature-reference.md#setup-and-options).
- **Clearer sound:** set the **Audio codec** select to **PCMU**. The browser
  plays PCMU as it is, so the agent no longer converts the sound between
  Speex and PCMU; that gives clearer audio and leaves the device more room.
  Switching restarts the C300X once. It writes the same codec settings that
  BTicino ships on firmware 3.0.6, which already runs PCMU from the factory.
- Use the **C300X Doorbell Call Card** in **Doorstation + Home Call** mode for live view, Ring Call
  handling and audio-only Home Calls to the display.
- **Browse saved images and videos** is on by default (`show_media_history: true`). Browse
  saved HA snapshots and capture videos with the arrows on the picture; videos
  have play/pause, a timeline and volume/mute, with their timestamp at the
  lower right. Click the picture for a large window with the same controls
  and full screen. On iPhone and iPad the volume slider is not shown,
  because the system leaves media volume to the hardware keys; mute works.
  Live video and incoming rings take
  priority. Browsing never starts, answers or stops a device call.
- History does not record videos or include the device's answering-machine
  recordings. Use the bundled **C300X Ring capture** blueprint to configure
  automatic clips; its default audio capture answers the Ring Call. Follow
  [Media history](visitor-journal.md#recording-videos) for setup and constraints.
- Set `show_media_history: false` to hide history on one card without changing
  live/call controls, image saving, capture automations or storage retention.
- Keep the card's Media Readiness line visible unless you intentionally want to
  hide all readiness status from that card.
- Keep **Forwarding** set to **Home Assistant** when you want Ring Calls to be
  answerable from Home Assistant.
- Use **Ringer mute** and **Ringer volume** for ringtone behavior. Volume uses
  the C300X `0..10` scale; `0` is mute.
- Ringer mute/unmute stays synchronized with the display's saved audio state.
  It requires the matching agent and [core GUI hook](advanced-maintenance.md#core-gui-hook),
  not the optional display pages.
- Start troubleshooting with **Media readiness** before editing card YAML.

## Feature Areas

| Area | What to use |
| --- | --- |
| Doorbell and Ring Call | C300X Doorbell Call Card, Forwarding select, Doorbell event, Doorbell state, Answer/Hang Up services. |
| On-demand video | Doorbell camera entity, card Stream/Stop controls, `activate_doorbell_video` and `stop_doorbell_video`; picture size, bit rate and frame rate under Camera quality. |
| Visitor images | Device-wide Save images switch; size, capture delay, retention and date and time under Visitor Snapshot; archive in HA Media and last-image previews. |
| Media history | Enabled by default in the doorstation card; previous/next browses HA snapshots and indexed capture videos inline. Independent visibility switch; no recording or device-call action from browsing. |
| Talkback | Secure browser frontend with microphone permission; HTTPS or Home Assistant Cloud is expected. |
| Home Call | Auto card, dedicated Home Call mode or `start_home_call` / `stop_home_call`. |
| Device actions | Door unlock, stair light and configured Device activation buttons/services. |
| Messages and memos | Video-message, text-memo and voice-memo sensors plus playback/write/delete services. |
| Display pages | Five built-in pages (Status, Energy, Agenda, Leave home and Situations) plus up to seven custom pages, all with configurable positions; weather, entity controls and a separate Alarmo subpage with an optional quick action. |
| Page navigation | A favourites bar along the bottom edge of the display (default for new setups): one button per page for up to four pages, otherwise three pages and More; or previous/next arrows. Set in the display settings. |
| Notifications | Standard Notify action with info, warning and error notices and bounded wake/sound on safe screens; protected screens and calls suppress effects. Each notice can be shown, spoken or both. Not a life-safety alarm. |
| Speaker | Media player for the device loudspeaker: Text-to-Speech, short sounds and announcements; a door call always takes priority. |
| Maintenance | Agent update/remove, SSH/noAuth, firewall, mDNS, GUI reload and reboot controls. |

See [Feature reference](feature-reference.md) for the full entity and service
list.

The card's bottom-right door and light buttons press the existing default door
unlock and staircase-light entities for the selected C300X. They work without
starting or stopping video. Missing or unavailable buttons are disabled; no
extra device polling is added.

Related status and codec entities are selected from the camera's device. If a
configured camera is removed, the card does not switch to another C300X. Call
controls require an unambiguous device assignment; an unavailable assignment
is reported in the card instead of sending a command to another doorstation.

## Advanced Use

Display pages, capture/transcription workflows and strict phrase decisions are
optional. Configure them only after the basic media paths are working.
