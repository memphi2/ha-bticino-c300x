# Privacy Notice

## Local Data Flow

The integration is designed for local Home Assistant use. Normal operation sends
device events from the native C300X agent to Home Assistant webhooks and sends
Home Assistant service requests back to the local agent.

The project does not intentionally send device data to a cloud service. The
project maintainers do not operate a service that collects or receives device
data. In normal use, camera, audio, event, and diagnostic data is handled only
by the user's local device and Home Assistant installation unless the user
explicitly shares it.

## Data Stored by Home Assistant

Home Assistant may store:

- Config entry values such as host, port, feature choices, and tokens.
- Entity state history if the recorder is enabled.
- Diagnostics generated through Home Assistant.
- Optional dashboard action configuration supplied by the user.

Diagnostics redact secrets and avoid exposing callback URLs or token values.

## Data Stored on the Device

The native agent may store:

- Its local JSON config.
- Event subscription metadata and token fingerprints.
- One-time backups of original QML and firewall files when those maintenance
  features are explicitly used.

Message and memo delete actions modify the corresponding local device data by
design.

## Video and Audio

Doorbell camera handling is local to the device, the native agent, and Home
Assistant. Users should still treat video/audio streams and Home Assistant
camera snapshots as sensitive local data.

Stored video and voice-message playback uses a RAM-only cache in Home Assistant
for up to 30 seconds, with at most four cached results and 64 MiB total. It is
not written to the device or disk. Changes to the message inventory invalidate
reuse of previous results. Agent downloads are limited to 32 MiB; converted
videos are limited to 64 MiB and 1920x1080, with a 30-second conversion budget.
One media preparation runs at a time, with at most four distinct pending jobs.

## What Is Not Included

The repository intentionally excludes vendor firmware images, extracted
firmware, APKs, generated runtime payloads, third-party controller code, local
device backups, and local secrets.
