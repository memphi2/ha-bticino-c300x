# Blueprints

The integration ships optional Home Assistant automation blueprints for common
C300X workflows. They use the public C300X services and entities; they do not
change the device configuration.

When Home Assistant loads the integration, missing bundled blueprints are copied
to:

```text
/config/blueprints/automation/bticino_c300x/
```

They then appear in Home Assistant under **Settings -> Automations & scenes ->
Blueprints**. Existing blueprint files are not overwritten.

## Included Blueprints

| Blueprint | Purpose |
| --- | --- |
| C300X Doorbell notification | Run a notification action when the doorbell rings. Select the C300X device; the blueprint finds the camera entity. |
| C300X Doorbell call notification | Notify only when Ring Call can be answered from Home Assistant. Select the C300X device; the blueprint finds the matching entities. |
| C300X Ring Call Android phone alert | Ring an Android phone with Answer, Hang Up and Open actions. |
| C300X Ring Call iOS phone alert | Ring an iPhone with critical sound plus Answer, Hang Up and Open actions. |
| C300X Ring capture | Capture a short MP4 plus local WAV/JPEG files when the doorbell rings. Select the C300X device; the blueprint finds the media-readiness sensor. |
| C300X Ring capture and Wyoming transcription | Capture and transcribe the latest raw WAV with a local Wyoming Whisper service. Select the C300X device; the blueprint finds the media-readiness sensor. |
| C300X strict phrase decision | Evaluate an existing transcription with strict capture freshness and exact phrase matching. Optional unlock stays disabled by default. |

If a blueprint is missing, restart Home Assistant once after updating the
integration. As a fallback, import the matching file from
`blueprints/automation/bticino_c300x/` in this repository with **Import
Blueprint**.

## Recommended Use

Start with **Media readiness**. Ring Call notification and capture should only
run when the media setup is `ready` or `warning`.

For Ring Call notifications, select the C300X device. The blueprints derive the
matching forwarding select, media-readiness sensor and camera from that device.
Forwarding must be set to **Home Assistant**. The doorbell-event blueprints use
the C300X event metadata to target the matching config entry, so no manual entry
ID is needed for these workflows.

Use the simple Doorbell notification blueprint only when you want an event
notification and do not want to answer the call. It also starts from the C300X
device and derives the camera entity for notification templates.

Use **C300X Ring Call Android phone alert** for Android phones. It
creates a high-priority notification with **Answer**, **Hang Up** and **Open**
actions. **Answer** clears the ringing notification, opens the configured
dashboard in the Companion App and calls `bticino_c300x.answer_doorbell_call`.
After answering, a quiet in-call notification keeps a **Hang Up** action
available.

The phone sound comes from the Android notification channel configured in the
blueprint. Open the Home Assistant Companion App notification settings and set
the sound for that channel to the ringtone you want.

Use **C300X Ring Call iOS phone alert** for iPhones. It sends an iOS critical
notification with **Answer**, **Hang Up** and **Open** actions. **Answer**
opens the Companion App in the foreground, clears the ringing notification and
calls `bticino_c300x.answer_doorbell_call`.

For the dedicated phone alert blueprints, set the notify service to the matching
Companion App service, for example:

```text
notify.mobile_app_your_phone
```

For capture and transcription, the default paths are:

- MP4 clips: `/media/c300x/`
- Latest raw WAV, processed WAV, frames and capture metadata: `/config/c300x/`
- Wyoming result and decision files: `/config/c300x/analysis/`

The capture files below `/config/c300x/` are overwritten on each run so the
directory does not grow indefinitely.

## Notification Actions

The event and generic call notification blueprints intentionally leave the
notification action to you.
That keeps mobile-app, persistent-notification and script-based setups possible.

The action can use these blueprint variables:

- `camera_entity`
- `dashboard_path`
- `entry_id`

Example action:

```yaml
service: notify.mobile_app_your_phone
data:
  title: Doorbell
  message: Someone is at the door.
  data:
    url: "{{ dashboard_path }}"
    clickAction: "{{ dashboard_path }}"
    entity_id: "{{ camera_entity }}"
```

## Strict Phrase Decision

The strict phrase blueprint is intentionally separate from capture and
transcription. Trigger it after your transcription run, for example with an
`input_button` or from another automation.

The decision service checks that:

- the result belongs to a fresh capture,
- the capture ID was not already consumed for unlock,
- the phrase matches exactly,
- unlock only runs when `unlock_on_match` is enabled.
