# User Guide

Use this page as the entry point after installing the integration.

## Recommended Path

```text
HACS install -> add integration -> install/update agent -> check Media readiness
-> run Repair if needed -> add the C300X card
```

Most users only need:

1. [Quickstart](quickstart.md)
2. [Media readiness](media-readiness.md)
3. [Media troubleshooting](media-troubleshooting.md)

## Common Tasks

| Task | Read |
| --- | --- |
| First install or update | [Quickstart](quickstart.md) |
| Check why Answer, Talkback or Home Call does not work | [Media readiness](media-readiness.md) |
| Fix stream/call/capture problems | [Media troubleshooting](media-troubleshooting.md) |
| Add notification or capture automations | [Blueprints](blueprints.md) |
| Update, remove or repair the device agent | [Advanced maintenance](advanced-maintenance.md) |
| Validate a release on real hardware | [Release validation](release-validation.md) |

## Daily Use

- Use the Doorbell/On-demand card for live view and Ring Call handling.
- Use the Home Call card for audio-only calls to the C300X display.
- Keep **Forwarding** set to **Home Assistant** when you want Ring Calls to be
  answerable from Home Assistant.
- Start troubleshooting with **Media readiness** before editing card YAML.

## Advanced Use

Display pages, capture/transcription workflows and strict phrase decisions are
optional. Configure them only after the basic media paths are working.
