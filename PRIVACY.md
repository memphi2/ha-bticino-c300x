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
- A mapping from config-entry IDs to reserved Notify action names in
  `.storage/bticino_c300x_notify_names`. It contains no notification text or
  credentials. Permanently removing an entry removes its reservation; an empty
  file can remain after removing the final entry.
- Visitor images in the configured HA media directory. The per-device **Save
  images** switch is on by default: a ring or active video session requests one
  image after 3 seconds, and images expire after 14 days. Delay and retention
  are configurable; storage is limited to 1,000 images and 128 MiB per device.
- Per-entry media-history metadata in HA's private `.storage`: ring times and
  outcomes and links to existing images and clips, kept as long as the image
  retention; an expired entry does not delete its MP4. Removing the integration
  entry removes this metadata, not media or backups. Details:
  [Visitor Images and Media History](docs/user-guide.md#visitor-images-and-media-history).

Turning **Save images** off prevents new captures and hides previews, but does
not delete existing images. Retention cleanup runs while the integration is
loaded, including while the switch is off. Images are served through
authenticated HA endpoints, not a public `www` path; who can open them is set
out in [Stored Media Access](SECURITY.md#stored-media-access). Local filesystem
copies and backups remain subject to your own access and backup policy.

Diagnostics redact secrets and avoid exposing callback URLs or token values.

When a notice lights the station's message LED (the `led` switch, legacy
`mode: display`, `both` or `led`, or a call without switches), the LED receives
only the unread state, never the notification text; see
[Notifications](docs/user-guide.md#notifications).

The live text-memo sensor can expose the latest memo text to authorized Home
Assistant clients. Its `latest_text` attribute is excluded from Recorder
history. Text already in Recorder history, copied by automations, exported in
logs or retained in backups is not removed.

Deleting a message or memo on the C300X does not delete Home Assistant history,
exports, optional local ring recordings, or backups. Manage those copies through
Home Assistant's Recorder retention settings and your backup policy. No automatic
history purge or backup deletion is performed by this integration.

## Data Stored on the Device

The native agent may store:

- Its local JSON config.
- Event subscription metadata and token fingerprints.
- One-time backups of original QML and firewall files when those maintenance
  features are explicitly used.

Message and memo delete actions modify the corresponding local device data by
design.

Visitor-image capture does not create images or temporary files on the C300X.
The agent reads the active video framebuffer into bounded memory and transmits
it to HA. HA performs JPEG conversion and storage. Capture does add bounded
device CPU, RAM and network activity.

## Video and Audio

Stored answering-machine videos, voice memos and local Ring Capture MP4 files
can be played by any authenticated Home Assistant user; see
[Stored Media Access](SECURITY.md#stored-media-access).

Doorbell camera handling is local to the device, the native agent, and Home
Assistant. Users should still treat video/audio streams and Home Assistant
camera snapshots as sensitive local data.

Stored video and voice-message playback uses a RAM-only cache in Home Assistant
for up to 30 seconds. It is not written to the device or disk.

Speech and other sounds for the device's speaker are made in Home Assistant.
The text of a spoken notification goes to the text-to-speech engine selected
in Home Assistant: a cloud engine sends it to its provider, a local engine
keeps it in your network. The converted sound is sent to the device as a
temporary file that is removed when the sound has ended. See
[Speaker Announcements and TTS](docs/user-guide.md#speaker-announcements-and-tts).

## What Is Not Included

The repository intentionally excludes vendor firmware images, extracted
firmware, APKs, generated runtime payloads, third-party controller code, local
device backups, and local secrets.
