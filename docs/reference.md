# Reference

This page lists what each model offers, every option, entity, action and
event. How to use them: [Classe 300X](classe-300x/2-use.md),
[Classe 100X](classe-100x/2-use.md).

## Models and Features

**Yes**: offered. **In test**: offered on the Classe 100X but not yet
confirmed on a device ([issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51)).
**No**: not offered; Home Assistant creates no entity for it.

| Feature | Classe 300X | Classe 100X 1.5.8 |
| --- | --- | --- |
| Door unlock, stair light, activations | Yes | In test |
| Live video, Ring Call, Home Call, talking | Yes | In test |
| Forwarding select | Yes | In test |
| Picture controls | Yes; tested on `1.7.19` | In test |
| Camera quality | Yes; `3.0.6` only the low stream | In test; low stream only |
| Camera resolution select, 960x576 | `1.7.x` and `2.0.2`; 960x576 on `1.7.19` and `2.0.2` only | No |
| Visitor images, ring recordings | Yes | In test |
| Audio codec select | Yes; `3.0.6` already runs PCMU | No; the browser still gets PCMU |
| Door level | In the station's audio chip; in software where the chip cannot be used | In test; in software |
| Fine adjustment | Yes | In test |
| Ringer volume | Yes | In test |
| Ringer mute | Yes | In test; after the display activation |
| Answering machine, video messages, voice memos | Yes | No |
| Text memos | Yes | No |
| Delete latest message or memo | With the Display patch | No |
| Speaker, `tts.speak`, spoken notices | Yes; tested on `1.7.19` | No |
| Display pages | Display patch | In test; activation by reboot, keys only |
| Display notices (Notify `display`) | With the display pages | In test; after the activation, without a tone |
| Touch tone switch | With the Display patch | In test; after the activation |
| Message LED (Notify `led`) | Where the station has one | No |
| Home page buttons, Reload device display | Yes | No |
| Agent install, update and removal | Yes | In test |

## Options

**Configure** on the integration opens a menu. Each area saves on submit.

| Area | Fields (default) | Writes to the station |
| --- | --- | --- |
| Connection to the C300X | Address; Port (`8091`); Access key; Maintenance key; Address of Home Assistant (optional). | Only when HTTP/HTTPS of the address changes: the agent restarts once no call runs. |
| Video and audio | Door station video and audio (on); Set up video and audio access (on); Door level (Stock); Fine adjustment (`0` dB, -10 to +10); Connection paths for the live picture (recommended); Talk through the Home Assistant camera view (off). | The media access during setup or its Repair. On a Classe 300X a door level above Stock writes the station's audio hook (`/home/root/demo/Audio_State.sh`); Stock or agent removal puts the original back. |
| Visitor Snapshot (video on) | Width 64-800 (`800`); height 64-480 (`480`); delay 1-300 s (`3`); keep 1-365 days (`14`); date and time in the image (on). | No. |
| Camera quality (video on) | Picture size; bit rate; frame rate; Use recommended snapshot size (800×480). | Yes; the station restarts. |
| Activations: locks, lights, stair light | Stair light address (Automatic, or Manual with P and N); activations with ID, name, type and address. | Only when the list changed. |
| Speech (Classe 300X with display pages) | Text-to-speech engine; Language. | No. |
| Display > Display and Display patch | Home Assistant pages on the display; Allowed actions; Keep the page open on screen standby; Page navigation; Home page buttons (Stock view). | Yes: the Display patch is applied or restored. Changing the home page buttons applies it again and restarts the display once. |
| Display > Display pages, Display tiles | Pages, their entities, weather and tile sizes. | No; the display asks Home Assistant. |
| Display > Alarm (Alarmo) | Alarmo alarm panel; Quick action. | No. |

Removing the integration, the package or the device agent:
[Remove the integration](classe-300x/5-update-and-removal.md#remove-the-integration).

On a Classe 100X the display area is called **Home Assistant pages on the
display**, has no home page buttons, and turning it off restores the original
display with one reboot. Before the display activation the menu shows
**Alarmo** in place of **Display**.

## Connection Paths for the Live Picture

Which addresses Home Assistant's WebRTC provider may offer the browser for
the live picture. The default is **IPv4 and local IPv6 (ULA) -
recommended** (`prefer_ipv4_ula`). Change it only when the picture does not
connect, then close the stream and open it again.

| Choice | Value | Address groups removed | When useful |
| --- | --- | --- | --- |
| All addresses | `all` | None | To compare without filtering. |
| Without link-local addresses (fe80::, 169.254.x.x) | `drop_link_local` | IPv4 link-local; IPv6 link-local | Keep IPv6, drop addresses that cannot cross subnets. |
| IPv4 and local IPv6 (ULA) - recommended | `prefer_ipv4_ula` | IPv4 link-local; IPv6 link-local; Other IPv6 | Default. It filters addresses, not their priority. |
| IPv4 only | `ipv4_only` | IPv4 link-local; IPv6 link-local; Other IPv6; IPv6 ULA | Networks where only IPv4 works. |

- IPv4 link-local is `169.254.0.0/16`, IPv6 link-local `fe80::/10`, IPv6 ULA
  `fc00::/7`. **Other IPv6** is every other IPv6 address, not just globally
  routable ones. IPv4-mapped IPv6 addresses count as IPv4.
- Every choice keeps TURN relay candidates, mDNS `.local` candidates, unknown
  addresses and unparseable candidate lines. IPv4 only is not a guarantee of
  an IPv4-only connection.
- Only provider-to-browser candidates are filtered, in the answer SDP and as
  trickled candidates. Browser-to-provider candidates are not filtered.
- Saving it does not install a device patch and changes nothing on the
  station.

## Allowed Actions

**Allowed actions (for experts)** is a JSON object, one entry per action ID
(letters, digits, `_ . : -`) with `domain`, `service` and optional `target`,
`data`, `name` and `dashboard`:

```json
{
  "entry_light": {
    "domain": "light",
    "service": "toggle",
    "data": {"entity_id": "light.entry"}
  }
}
```

Each action becomes a tile on the display, by default on an extra page.
`dashboard` can set `page`, `name`, `type` (`button`, `switch`, `image`),
`order`, `state_entity_id`, `state_label`, `source` (picture address of an
image tile), `width` and `height`. Leave home and display notices can only
offer actions from this list.

## Entities

| Entity | Type | Notes | Classe 100X |
| --- | --- | --- | --- |
| Doorbell camera | camera | Live picture and calls; shows the latest visitor image when idle. | In test |
| Speaker | media player | The station's loudspeaker. | No |
| Doorbell ring event | event | Fires `ring` on a doorbell press. | In test |
| Device event | event | All other station events. | In test |
| Media readiness | sensor | Ready, Warning, Blocked or Unavailable. | In test |
| Device agent status, Device agent diagnostics | sensor | Agent health; diagnostics disabled by default. | In test |
| Doorbell state | sensor | Idle, Ringing or Camera view active. | In test |
| Device CPU, Device temperature, Device load, Device memory | sensor | Load and memory disabled by default. | In test |
| Video messages, Text memos, Voice memos | sensor | Counts and latest item. | No |
| Home call active | binary sensor | On during a Home Call. | In test |
| Forwarding | select | Smartphone, Home Assistant, Blocked. | In test |
| Camera resolution | select | High or Low. Not on `3.0.6`. | No |
| Audio codec | select | Speex or PCMU; a change restarts the station. | No |
| Ringer volume | number | `0` to `10`. | In test |
| Ringer mute | switch | | After the display activation |
| Touch tone | switch | Needs the Display patch. | After the display activation |
| Answering machine | switch | | No |
| Save images | switch | Visitor images; attribute `last_failure`. | In test |
| Home Assistant media user | switch | Station access for video and calls. | In test |
| SSH, Agent noAuth, Agent noAuth maintenance, Agent mDNS discovery | switch | Maintenance. | In test |
| Display patch | switch | Display pages on or off. | No |
| API firewall patch, IPv6 firewall patch | switch | No IPv6 switch on `3.0.6`. | In test |
| Native MQTT bridge, Legacy MQTT bridge | switch | Local MQTT. | In test |
| Door unlock, Stair light, one per activation | button | | In test |
| Stop doorbell video | button | Ends a stream. | In test |
| Reboot, Restart device agent, Remove device agent | button | Maintenance. | In test |
| Reload device display | button | Restarts the station's display. | No |
| Activate display pages, Restore original display | button | Display pages on or off with one reboot. | Classe 100X only |
| Delete latest video message, text memo, voice memo | button | Need the Display patch. | No |

## Actions

All actions are `bticino_c300x.<name>`. With more than one station add
`entry_id`.

| Action | Does | Main fields |
| --- | --- | --- |
| `activate_doorbell_video`, `stop_doorbell_video` | Starts or stops live video. | `audio` |
| `answer_doorbell_call`, `hangup_doorbell_call` | Answers or ends a Ring Call. | |
| `start_home_call`, `stop_home_call` | Home Call to the station display. | `duration_seconds` |
| `camera_picture` | Reads or sets brightness, contrast, saturation during live video. | `control`, `value` (0-100, steps of 10) |
| `unlock_door` | Opens a door lock. | `lock_id` |
| `stair_light` | Switches the stair light. | `address` |
| `run_device_activation` | Runs an activation. | `activation_id` |
| `alarm_command` | Sends a command to the Alarmo panel. | `command`, `code`, `force` |
| `run_action` | Runs one allowed action. | `action_id` |
| `show_display_notification` | Quiet notice on the display. | `notification_id`, `title`, `message`, `icon` (`info`, `warning`, `calendar`), `priority` (`normal`, `important`, `urgent`), `expires_in` (1-604800 s), `actions` (up to two allowed actions) |
| `dismiss_display_notification` | Removes that notice. | `notification_id` |
| `capture_doorbell_call` | Records a clip ([below](#recording-clips)). | |
| `run_ring_wyoming_analysis` | Transcribes a recording with a local Wyoming service. | `wyoming_host`, `wyoming_port`, `language`, paths |
| `evaluate_ring_analysis` | Checks a transcription for an exact phrase; unlocks only on a match when asked. | `expected_phrase`, `unlock_on_match`, `lock_id` |
| `play_latest_video_message`, `play_latest_voice_memo` | Plays the latest item. Classe 300X only. | `media_player_entity_id` |
| `write_text_memo` | Writes a text memo. Classe 300X only; not during a call. | `text`, `read` |
| `delete_latest_video_message`, `delete_latest_text_memo`, `delete_latest_voice_memo` | Deletes the latest item. Classe 300X with the Display patch. | |
| `reboot` | Restarts the station. | |
| `reload_gui` | Restarts the station's display. Classe 300X only. | |

Also: the Notify action (`notify.bticino_c300x`) and `tts.speak` on the
**Speaker**.

**Permissions:** a user who is not an admin needs control of the matching
entity (the camera for video and calls, the button for door and activations,
the alarm panel for `alarm_command`). `run_action` is open to every user.
Everything else is for admins only.

## Notify Fields

The Notify action exists while **Home Assistant pages on the display** is on.
The first station uses `notify.bticino_c300x`; a station named **Front door**
gets `notify.bticino_c300x_front_door`. Do not set `target`.

| Field in `data` | Values |
| --- | --- |
| `display`, `tts`, `led` | `true` or `false`; at least one `true`. |
| `severity` | `info` (default), `warning`, `error`. |
| `wake_duration`, `sound_duration` | 0-300 s, default 30. Only with `display`. |
| `expires_in` | 1 s to 7 days, default one hour. |
| `notification_id` | Optional; the same ID replaces a notice. |
| `tts_engine`, `language` | Only with `tts`. Defaults come from **Configure > Speech**. |

- `title` up to 80 characters, `message` up to 500.
- With `display` and `tts` there is no tone.
- With only `tts` nothing is stored, so `severity`, `expires_in` and
  `notification_id` are refused.
- `led` needs a station with a message LED.
- Popup, wake and tone only appear on the station's home page or Home
  Assistant page, never during a call or on the Alarm page.
- Without any switch the call works as `display` and also lights the LED.
  The old `mode` field (`display`, `speech`, `both`, `led`) still works but
  cannot be combined with the switches.
- Classe 100X: only `display`, without `sound_duration`.

## Recording Clips

`bticino_c300x.capture_doorbell_call` records 1-15 seconds.

| `capture_mode` | Starts from | Call |
| --- | --- | --- |
| `ring` (default) | A ringing Ring Call. | With `include_audio` or `announcement_path` the call is answered first. |
| `on_demand` | No ring; the camera must be free. | Never answers or hangs up. |

```yaml
- action: bticino_c300x.capture_doorbell_call
  data:
    capture_mode: on_demand
    duration_seconds: 5
    include_audio: true
  response_variable: capture
```

- MP4 files go to `/media/c300x/`; WAV audio, three JPEG frames and metadata
  to `/config/c300x/captures/<capture_id>/`.
- Output paths must stay below `/media/c300x/`, `/config/c300x/` or
  `/config/www/c300x/`.
- The response holds `capture_id`, `metadata_path`, `output_path` and, with
  audio, `raw_wav_path`. Use these paths in later steps.
- One recording per station at a time. MP4 files are never deleted
  automatically.

## Visitor Image Failures

The **Save images** switch shows the cause of the last failed image as
**Last failure** (attribute `last_failure`):

| Code | Shown as |
| --- | --- |
| `snapshot_unavailable` | Display picture could not be read |
| `snapshot_throttled` | Requested too soon after the previous image |
| `invalid_snapshot_size` | Station rejected the image size |
| `invalid_image` | Station delivered an invalid image |
| `agent_unreachable` | Device agent not reachable |
| `agent_error` | Device agent reported an error |
| `save_failed` | Home Assistant could not save the image |

## Speaker Results

The **Speaker** attribute `last_result`:

| Value | Meaning |
| --- | --- |
| `played`, `stopped` | Finished, or stopped with **Stop**. |
| `preempted` | Ended by a door call. |
| `device_busy` | Not started: the station was using its speaker. |
| `not_played` | The agent did not take the sound. |
| `sound_path_failed`, `play_failed` | The station could not switch on the speaker or play. |
| `failed` | Broke off for another reason. |
| `unknown` | The agent could not be asked. |

## Events

Home Assistant fires `bticino_c300x_agent_event_received` for every station
event, with `entry_id`, `event_key`, `event_at` and the event data. The
**Device event** entity shows the last one.

```yaml
triggers:
  - trigger: event
    event_type: bticino_c300x_agent_event_received
    event_data:
      event_key: doorbell_pressed
```

| `event_key` | When |
| --- | --- |
| `doorbell_pressed` | Someone rang. |
| `doorbell_view_requested`, `doorbell_media_closed` | The camera view started or ended. |
| `call_started`, `call_ended` | A call on the station started or ended. |
| `home_call_started`, `home_call_answered`, `home_call_ended` | Home Call steps. |
| `door_unlock_started`, `door_unlock_ended` | Door unlock. |
| `stair_light_activated`, `stair_light_released` | Stair light. |
| `activation_executed` | An activation ran. |
| `ringer_muted`, `ringer_unmuted`, `ringer_volume_changed` | Ringer changed. |
| `smartphone_forwarding_changed` | Forwarding changed (`mode`). |
| `display_touch_tone_changed` | Touch tone changed. |
| `answering_machine_messages_changed`, `memos_changed` | Messages or memos changed. |
| `agent_restarted` | The agent restarted. |

`bticino_c300x_action_received` fires when Home Assistant itself ran
`run_action`, `unlock_door` or a display tile command.

Start values and reconnects only update the entities; they fire no event.
