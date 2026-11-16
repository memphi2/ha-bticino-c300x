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
| Browse a visit's saved image or video in the card | [Visitor journal](visitor-journal.md) |
| Upgrade from 2.3.0 or 2.1.3 | [Upgrade guide](advanced-maintenance.md#updates) |
| Update, remove or repair the device agent | [Advanced maintenance](advanced-maintenance.md) |

## Daily Use

- **Save images** enables automatic visitor images independently of an open
  dashboard. Size, delay, retention and the date and time in the image are
  configured under **Configure > Visitor Snapshot**; defaults are 688x480,
  3 seconds, 14 days and date and time on. Images and their shared camera/card preview are
  stored in HA, not on the C300X. See [Visitor images](feature-reference.md#visitor-images).
- Use the **C300X Doorbell Call Card** in **Doorstation + Home Call** mode for live view, Ring Call
  handling and audio-only Home Calls to the display.
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
| On-demand video | Doorbell camera entity, card Stream/Stop controls, `activate_doorbell_video` and `stop_doorbell_video`. |
| Visitor images | Device-wide Save images switch; size, capture delay, retention and date and time under Visitor Snapshot; archive in HA Media and last-image previews. |
| Talkback | Secure browser frontend with microphone permission; HTTPS or Home Assistant Cloud is expected. |
| Home Call | Auto card, dedicated Home Call mode or `start_home_call` / `stop_home_call`. |
| Device actions | Door unlock, stair light and configured Device activation buttons/services. |
| Messages and memos | Video-message, text-memo and voice-memo sensors plus playback/write/delete services. |
| Display pages | Up to eight ordered native pages plus an optional Energy page, weather, configurable tiles and supported entity controls; a separate Alarmo subpage with an optional quick action. |
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
