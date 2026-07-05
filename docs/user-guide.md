# User Guide

Use this page as the entry point after installing the integration.

## Recommended Path

```text
HACS install -> add integration -> install/update agent -> check Media readiness
-> run Repair if needed -> add the C300X card
```

Most users only need:

1. [Quickstart](quickstart.md)
2. [Feature reference](feature-reference.md)
3. [Media readiness](media-readiness.md)
4. [Media troubleshooting](media-troubleshooting.md)

## Common Tasks

| Task | Read |
| --- | --- |
| First install or update | [Quickstart](quickstart.md) |
| See all entities, services, options and device writes | [Feature reference](feature-reference.md) |
| Check why Answer, Talkback or Home Call does not work | [Media readiness](media-readiness.md) |
| Fix stream/call/capture problems | [Media troubleshooting](media-troubleshooting.md) |
| Add notification or capture automations | [Blueprints](blueprints.md) |
| Update, remove or repair the device agent | [Advanced maintenance](advanced-maintenance.md) |
| Validate a release on real hardware | [Release validation](release-validation.md) |

## Daily Use

- Use the Doorbell/On-demand card for live view and Ring Call handling.
- Use the Home Call card for audio-only calls to the C300X display.
- Keep the card's Media Readiness line visible unless you intentionally want to
  hide all readiness status from that card.
- Keep **Forwarding** set to **Home Assistant** when you want Ring Calls to be
  answerable from Home Assistant.
- Use **Ringer mute** and **Ringer volume** for ringtone behavior. Volume uses
  the C300X `0..10` scale; `0` is mute.
- Start troubleshooting with **Media readiness** before editing card YAML.

## Feature Areas

| Area | What to use |
| --- | --- |
| Doorbell and Ring Call | C300X Doorbell Call Card, Forwarding select, Doorbell event, Doorbell state, Answer/Hang Up services. |
| On-demand video | Doorbell camera entity, card Stream/Stop controls, `activate_doorbell_video` and `stop_doorbell_video`. |
| Talkback | Secure browser frontend with microphone permission; HTTPS or Home Assistant Cloud is expected. |
| Home Call | Home Call card mode or `start_home_call` / `stop_home_call`. |
| Device actions | Door unlock, stair light and configured Device activation buttons/services. |
| Messages and memos | Video-message, text-memo and voice-memo sensors plus playback/write/delete services. |
| Display pages | Optional Display patch with Alarmo, weather and selected dashboard entities. |
| Maintenance | Agent update/remove, SSH/noAuth, firewall, mDNS, GUI reload and reboot controls. |

See [Feature reference](feature-reference.md) for the full entity and service
list.

## Advanced Use

Display pages, capture/transcription workflows and strict phrase decisions are
optional. Configure them only after the basic media paths are working.
