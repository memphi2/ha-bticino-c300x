# Privacy Notice

## Local Data Flow

The integration is designed for local Home Assistant use. Normal operation sends
device events from the native C300X agent to Home Assistant webhooks and sends
Home Assistant service requests back to the local agent.

The project does not intentionally send device data to a cloud service.

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

## What Is Not Included

The repository intentionally excludes vendor firmware images, extracted
firmware, APKs, generated runtime payloads, third-party controller code, local
device backups, and local secrets.
