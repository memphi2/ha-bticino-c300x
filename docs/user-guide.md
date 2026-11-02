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
| Update, remove or repair the device agent | [Advanced maintenance](advanced-maintenance.md) |

## Daily Use

- Use the **C300X Doorbell Call Card** in **Auto** mode for live view, Ring Call
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
| Talkback | Secure browser frontend with microphone permission; HTTPS or Home Assistant Cloud is expected. |
| Home Call | Auto card, dedicated Home Call mode or `start_home_call` / `stop_home_call`. |
| Device actions | Door unlock, stair light and configured Device activation buttons/services. |
| Messages and memos | Video-message, text-memo and voice-memo sensors plus playback/write/delete services. |
| Display pages | Optional Display patch with Alarmo, weather and selected dashboard entities. |
| Maintenance | Agent update/remove, SSH/noAuth, firewall, mDNS, GUI reload and reboot controls. |

See [Feature reference](feature-reference.md) for the full entity and service
list.

## Advanced Use

Display pages, capture/transcription workflows and strict phrase decisions are
optional. Configure them only after the basic media paths are working.
