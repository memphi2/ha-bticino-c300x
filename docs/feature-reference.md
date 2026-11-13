# Feature Reference

The agent status attribute `agent_restart_count` counts observed changes of the
agent process instance since this integration entry was loaded. It does not
count device reboots, and agents without instance metadata cannot contribute to
it. This replaces the misleading `device_reboot_count` attribute; a lower uptime
alone is not treated as restart evidence.

Detailed agent diagnostics remain available live, but volatile debug attributes
(loop counters, descriptor counts and observation timestamps) are excluded from
Recorder history. Health states, CPU measurements, write counters and watchdog
triggers retain their normal history behavior. Diagnostic entities remain
disabled by default.

The diagnostics attribute `media_watchdog_last_percent` records the CPU value
of the last actual watchdog trigger, not every healthy observation. Use the
Device CPU sensor for current CPU measurements.

This page is the compact reference for users and maintainers. It describes what
the integration exposes, where to configure it, and which parts write to the
C300X only after an explicit user action.

## Operating Model

The integration is local-first:

- Home Assistant talks to the native C300X agent through the local `/api/v1`
  HTTP API.
- The native agent pushes events back to Home Assistant webhooks.
- Camera, Ring Call, Home Call and talkback use Home Assistant's WebRTC
  provider/go2rtc path.
- Core device state is event-driven; Home Assistant should not need polling for
  normal doorbell, call, ringer, forwarding, memo or message changes.
- Optional maintenance actions can write device-side config, but they are
  explicit setup, options or Repair actions.

## Setup and Options

| Area | Purpose | Writes to device |
| --- | --- | --- |
| Connection | Agent host, port, API token, maintenance token, optional callback base URL. | Token setup during explicit install. Changing callback HTTP/HTTPS mode updates agent config and schedules an agent-only restart. |
| Media features | Doorstation media, Home Assistant media user, live audio gain, Ring Capture gain. | Media-user setup writes only when setup/Repair is run. Audio gain is runtime-only and is sent only when non-default or different. |
| Device activations | Optional extra C300X activation buttons. | Only after saving, and only when the desired activation config differs. |
| Display dashboard | Optional Display patch, Alarmo/weather/dashboard entities and action allowlist. | Yes, only when the Display patch is applied/restored. |
| Maintenance controls | SSH, noAuth, mDNS discovery, firewall patches, GUI reload, reboot, agent update/remove. | Yes, only when the corresponding entity, button or Repair is used. |

## Main User Features

| Feature | User surface | Notes |
| --- | --- | --- |
| Doorbell ring event | Event entity, automations, blueprints, card state. | Receives real C300X ring events from the native agent. |
| On-demand camera | Camera entity, C300X Doorbell Call Card, `activate_doorbell_video` / `stop_doorbell_video`. | Uses local RTSP through Home Assistant's WebRTC provider/go2rtc and does not require Home Assistant Ring Call forwarding. |
| Ring Call preview | C300X Doorbell Call Card. | Multiple browser previews are supported; only the active answered browser should show Answer/Hang Up. |
| Ring Call answer/hangup | C300X card, mobile blueprints, `answer_doorbell_call`, `hangup_doorbell_call`. | Requires Forwarding set to Home Assistant and media readiness without blocking failures. |
| Talkback | Browser microphone through the card, or optionally the native HA camera player on HA 2026.11+. | Native HA control is off by default. Enable **Two-way audio in the HA camera player** in the integration options and Two-way audio in HA Labs. Requires WebRTC, HTTPS and microphone permission. Card talkback is unchanged. |
| Home Call | C300X card, Home Call websocket path, `start_home_call`, `stop_home_call`. | Audio-only call from Home Assistant to the C300X display. |
| Door unlock | Button entity, service, optional dashboard action. | Sends one configured unlock command through the native agent. |
| Stair light | Button entity, service, optional generated activation. | Manual mode uses P/N parts to generate the stair-light activation address. |
| Device activations | Button entities, `run_device_activation`. | Supports `lock`, `light`, `stair_light`, `scenario`, and `generic` activation types. |
| Forwarding | Select entity. | Values are Smartphone, Home Assistant and Blocked. Ring Call answer needs Home Assistant. |
| Ringer mute and volume | Switch and number entity. | Volume uses the C300X display scale `0..10`; `0` is muted. |
| Answering machine | Switch and video-message sensor/services. | Message delete requires the Display patch. |
| Text and voice memos | Sensors and memo services. | Text memo write and latest memo playback are service driven. Delete requires the Display patch. |
| Display pages | Optional C300X display dashboard. | Native QML pages, not Lovelace embedding; no Home Assistant token is stored on the device display side. |
| Ring Capture and local analysis | Services and blueprints. | Writes local MP4/WAV/JPEG/JSON below allowed Home Assistant paths; local Wyoming transcription is optional. |
| Media readiness and Repairs | Diagnostic sensor and Repair flows. | Media prerequisites can be repaired; the selected Ring Call forwarding target is reported but never changed by a Repair. |

### Card Buttons

The card editor lets you show or hide **Open door** and **Staircase light**
independently. Both are shown by default. In YAML, set `show_door_unlock: false`
or `show_stair_light: false` to hide the corresponding button. This only changes
that card; the Home Assistant entities and services remain available.

## Alarmo Display

The optional native Alarmo page stays a subpage in the original blue C300X
design. The configured return-after-standby setting still applies. It shows
reported alarm state, readiness, blocking contacts and entry/exit countdowns.
Tap a mode to execute directly when no PIN is required; otherwise the keypad
appears. Entry delay opens the disarm keypad when required. A pending command
blocks repeated taps; unavailable data is not displayed as a ready alarm.

Under **Display dashboard**, **Alarm page entity** selects the optional quick
action or status entity. Leave it empty to hide this area. To retain a stair-light
shortcut, select the integration's stair-light button explicitly. No stair-light
action is inserted automatically. Buttons, switches, scenes and scripts can be
operated directly; other supported selections remain read-only on this page.
The selected entity's name is used, including an existing display-name override.

The revised page is part of 2.1.0 and later. Update the bundled agent and
apply the Display patch to install it. No new background polling or device-file
history is added. Reconnect attempts run only after a failed event connection
while the page is active. Device rendering and interruption by a physical Ring
Call are not yet confirmed on hardware.

## Display Home Page Buttons

**Use dynamic home page buttons** under **Display dashboard** decides how the
Alarm and Home Assistant buttons reach the device's home page.

| Setting | Home page |
| --- | --- |
| On | Each button is placed on its own and is shown only while it has something to open: Alarm when Alarmo is configured, Home Assistant when a dashboard is available. The firmware arranges them with the stock buttons and wraps to a second row once more than four are visible. |
| Off | Both buttons sit together in one fixed pair, always visible, next to each other. |

The mode is part of the page the Display patch generates, so changing it
re-applies the patch and restarts the device GUI once. Saving the options
without touching the setting changes nothing on the device.

New entries start with the setting on. An entry created before the setting
existed keeps the fixed pair it has been running, recorded once on upgrade, and
the form shows that state instead of an unrelated default.

## Display Device Controls

Select lights, covers, climate entities, fans, media players and sensors under
**Display dashboard**. Entities with controls share the two-column overview
with sensors.
A chevron marks every tile that has a submenu: tap anywhere on such a tile to
open its supported controls, or tap a sensor tile for its read-only details.
Lights and fans keep an on/off switch on the tile itself. Covers and climate
entities are operated from their submenu, because neither has a single on/off
action. Back returns to the same overview page and scroll position; a state
refresh that arrives while the list is moving is applied once it settles.

Each tile's size is set per entity in the entity-display dialog. **Width** is
half or full. **Height** is half, the compact 64 px tile, or full, a 94 px tile
like a sensor's. A full-height tile carries the entity's own buttons, so the
common action needs no submenu:

| Entity | Buttons on a full-height tile |
| --- | --- |
| Cover | up, stop, down (those it supports) |
| Climate | target temperature minus/plus, by the entity's step |
| Light | on/off switch, brightness minus/plus in 10 % steps |
| Fan | on/off switch, speed minus/plus by about 10 %, at least one of the fan's speeds |
| Number | minus/plus, by the entity's step |
| Select | previous/next option, wrapping at either end |
| Media player | on/off switch, previous, play/pause, next (those it supports) |

The tile background still opens the submenu, and every other control stays
there. **Automatic** keeps the size of the type: sensors full height, all other
entities half height, both half width. A dashboard configured before these
settings existed therefore looks the same until a size is chosen.

- Lights show brightness, eight color swatches and warm/neutral/cool white
  presets where supported. White presets stay within the light's Kelvin range;
  the Kelvin slider remains available for fine adjustment. Selecting a color
  sends one command, including both hue and saturation. Lights supporting both
  white temperature and color have separate tabs; brightness stays available
  in either tab, with the power button in the fixed summary.
- Covers show their reported position visually, plus opening/closing state.
  Supported up/stop/down buttons stay visible above the scrolling controls.
  Position and tilt are adjusted separately; missing position is not shown as
  closed.
- Climate entities separate measured temperature and reported heating/cooling
  activity from the selected HVAC mode. Target temperature, lower/upper target
  range, presets, fan mode and vertical/horizontal swing appear where supported.
  Target and HVAC mode are on the main tab; presets, fan and swing settings
  move to a separate settings tab when supported.
- Fans expose speed, oscillation, presets and direction according to their
  capabilities. Preset names come from the entity itself.
- Media players show what is playing, or their state when nothing is. On a
  tile this is the state line, so another secondary-line choice replaces it.
  The submenu has previous, play/pause and next, a volume slider, mute, source and
  sound mode, each only where the player reports the feature. The on/off switch
  and play/pause appear only when the player reports the step its current state
  needs, and send that explicit service: turn on or off, play or pause. A
  media player cannot be chosen as the alarm page's quick entity.
- Sensor and binary-sensor tiles use larger readings and read-only details.
  Numeric sensors retain their unit and reported display precision. Details may
  show the entity's numeric battery level, humidity and illuminance attributes;
  unrelated attributes and history are not requested or forwarded.
- Number entities use HA units, bounds and step sizes; select entities show their
  actual options. Sliders send one command on release, not during movement.

State changes for selected entities use the existing event bridge, including
when no Alarmo entity is configured. There is no regular device-state polling.
Bursts are combined into a notification. Selected-entity changes that do not
alter the displayed values, availability or controls do not notify the device.
Alarmo and weather keep their existing event handling. Unchanged GUI items are
reused, preserving the overview position and active input.

Device requests to Home Assistant are serialised on the device. The agent
forwards them one at a time and refuses a second one while the first is open,
so the pages queue instead of colliding: waking from standby no longer shows a
transport error when the home page refreshes its buttons at the same moment a
page is opened. Pages asking for the same state at the same time are answered
from one request; commands always keep their own.

Command feedback distinguishes sending, accepted commands and matching state
reported by HA. HA state confirmation is not independent physical verification
for optimistic entities. An accepted command that HA never reflects is reported
as unconfirmed after 15 seconds, and feedback for an entity disappears a minute
after the last thing happened to it, so a tile returns to showing its plain
reading. Errors remain at the affected control; an uncertain transport result is
not automatically retried. During a connection outage the
last snapshot stays visible, explicitly marked as stale, with actions disabled.
Unavailable controls are disabled and commands are validated again in HA against
the current selection and entity capabilities. Timeout and reconnect handling
only runs while the page is active. Display changes require the matching bundled
agent files and reapplying the Display patch after an update. Device rendering
and physical Ring Call interruption are not yet confirmed on hardware. No
additional polling, refresh timers or device-file writes are introduced by these
detail views.

## Display Settings

Use **Configure > Display dashboard**, then the entity-display dialog. Choose
entities and the optional Alarmo quick entity with the normal HA selectors;
control types come from their actual capabilities, not a manually chosen widget.

Each overview entity has **Page**, **Position**, **Width**, **Height**, name and
secondary-line settings.
Use the same page name to group entities; leave it empty for the existing unnamed
page. Positions run from 0 to 10000, lower first within a page. Existing selections
keep their original order until you change a position. Named pages follow their
first occurrence in the selected-entity list, after the HA status/weather page.
Page names are limited to 60 characters. Missing or unavailable entities retain
their configuration and show unavailable rather than changing the saved layout.

The first page is the status page: it carries the HA, alarm and time badges
and, unless placed elsewhere, the weather card. Its internal name is `C300X`,
and the display shows no title for it. Entities without a page name go to a
separate unnamed page after it. Give entities the page name `C300X` to put
their tiles on the status page as well.

With a weather entity selected, the dialog also offers **Weather - Page** and
**Weather - Position**. Left empty and at 0, the card stays at the top of the
status page. A position sorts it among the tiles of its page exactly like an
entity's position, so 15 places it between tiles at 10 and 20. A page name
moves the card to that page without changing the order of the pages; a page
that no entity uses is created after the entities' pages.
The card always spans the full width.

The optional Alarmo quick entity also gets its name and secondary-line settings,
even if it is not selected for an overview page. Selecting it does not add it to
the overview. Leave the quick entity empty to hide it; no stair-light default is
inserted. Connection/maintenance settings remain separate. Calendar and notification
logic stays in HA automations. This is a normal configuration dialog, not a visual
editor, and opening the dialog does not operate a device.

## Display Notifications

Automations can use `bticino_c300x.show_display_notification` to show a compact
notice on the native Home Assistant page. Tap it for details. It does not open
automatically, cover Alarmo PIN entry, interrupt Ring Calls or wake the display.

```yaml
action: bticino_c300x.show_display_notification
data:
  notification_id: front_window
  title: Front window
  message: The front window is still open.
  icon: warning
  priority: important
  expires_in: 3600
```

Use the same ID to replace a message and `bticino_c300x.dismiss_display_notification`
with that ID to remove it. IDs allow lowercase letters, digits, `_` and `-` (64
characters maximum). Titles allow 80 characters, text 500, expiry 1 second to
7 days. Symbols are `info`, `warning` and `calendar`; priorities are `normal`,
`important` and `urgent`. Specify `entry_id` with multiple C300X integrations.

Up to eight messages (16 KiB of encoded data) are retained in HA memory, highest
priority first. When full,
the oldest message at the lowest priority is replaced; a lower-priority incoming
message cannot evict a higher-priority one. Restarting HA or reloading the
integration clears the list. Automations should resend still-relevant conditions.
No message history or notification files are written to the C300X or Recorder.

Optional `actions` accepts at most two `{action_id: ..., label: ...}` entries from
the existing display action allowlist. An action never runs merely because a
notification arrives. **Mark read** only dismisses the message; it does not resolve
the physical condition or run an action. Updated messages reject stale commands.

The bundled **C300X Calendar display reminder** blueprint selects an existing HA
calendar, target C300X, lead time, reminder text and expiry. It uses a calendar
event trigger rather than polling the device or adding a calendar provider.
For a reliable test, create the event more than 15 minutes in advance, as noted
in the [Home Assistant calendar documentation](https://www.home-assistant.io/integrations/calendar/#automation).

## Entity Reference

Entities are capability-gated. If the installed agent does not advertise a
feature, the matching entity is not created.

| Platform | Entity | Purpose |
| --- | --- | --- |
| `camera` | Doorbell camera | On-demand/Ring Call/Home Call media entry point. |
| `event` | Doorbell ring event | Ring-only event entity. |
| `event` | Device event | Canonical native-agent events such as doorbell, call, ringer, forwarding, stair light, activation, memo and message changes. |
| `sensor` | Media readiness | Aggregated media setup state and actionable failures. |
| `sensor` | Device agent status | Agent connection and health summary. |
| `sensor` | Device agent diagnostics | Self-test and watcher diagnostics. |
| `sensor` | Doorbell state | Current doorbell/media state derived from native events. |
| `sensor` | Device CPU/load/memory/temperature | Optional low-frequency native-agent metrics. |
| `sensor` | Video messages, text memos, voice memos | Local device message/memo counters and latest metadata. |
| `binary_sensor` | Home call active | Whether Home Call is currently active. |
| `select` | Forwarding | Smartphone, Home Assistant or Blocked forwarding mode. |
| `switch` | Ringer mute | Device ringer mute state. |
| `number` | Ringer volume | C300X `0..10` ringtone volume scale. |
| `switch` | Answering machine | Device answering-machine enabled state. |
| `switch` | Home Assistant media user | Creates/repairs the local C300X media user when used. |
| `switch` | SSH, noAuth, noAuth maintenance, mDNS discovery | Explicit maintenance controls. |
| `switch` | Display patch, API firewall patch, IPv6 firewall patch | Explicit device-side patch controls. |
| `switch` | Native MQTT bridge, legacy MQTT bridge | Local MQTT migration/compatibility controls. |
| `button` | Door unlock, stair light, device activations | One-shot device actions. |
| `button` | Stop doorbell video | Stops an active agent-owned on-demand media session. |
| `button` | Reboot, restart agent, reload display, remove device agent | Explicit maintenance actions. |
| `button` | Delete latest video/text/voice memo | Delete actions that require matching capability and patch state. |

## Service Reference

Services called by a HA user respect that user's control permissions. Device
commands require access to the matching enabled entity; configured actions keep
the caller's identity. Maintenance, explicit stair-light address overrides,
capture/analysis, notification management and stored-message services are
admin-only. Trusted context-free automations remain supported. See
[service permissions](../SECURITY.md#home-assistant-service-permissions).

| Service | Purpose |
| --- | --- |
| `bticino_c300x.run_action` | Runs one allowlisted display/dashboard action by action id. |
| `bticino_c300x.run_device_activation` | Runs one configured C300X activation by activation id. |
| `bticino_c300x.alarm_command` | Sends an alarm command to the configured alarm control panel entity. |
| `bticino_c300x.stair_light` | Activates the configured or supplied stair-light address. |
| `bticino_c300x.unlock_door` | Unlocks a configured door lock. |
| `bticino_c300x.activate_doorbell_video` | Starts or renews on-demand doorstation media. |
| `bticino_c300x.stop_doorbell_video` | Stops an active agent-owned on-demand media session. |
| `bticino_c300x.answer_doorbell_call` | Answers the active Ring Call. |
| `bticino_c300x.hangup_doorbell_call` | Hangs up the active Ring Call. |
| `bticino_c300x.capture_doorbell_call` | Records a 1–15 second MP4 from a Ring Call (`ring`, default) or idle live view (`on_demand`), with optional audio and local capture artifacts. |
| `bticino_c300x.run_ring_wyoming_analysis` | Transcribes an existing Ring Capture WAV through a local Wyoming Whisper service. |
| `bticino_c300x.evaluate_ring_analysis` | Evaluates a local transcription JSON and optionally unlocks only on strict phrase match. |
| `bticino_c300x.start_home_call` | Starts an audio-only Home Call to the C300X display. |
| `bticino_c300x.stop_home_call` | Stops an active Home Call. |
| `bticino_c300x.reboot` | Schedules a device reboot through the maintenance API. |
| `bticino_c300x.reload_gui` | Reloads the C300X graphical interface. |
| `bticino_c300x.play_latest_video_message` | Plays the latest stored video message on a media player. |
| `bticino_c300x.play_latest_voice_memo` | Plays the latest voice memo on a media player. |
| `bticino_c300x.write_text_memo` | Creates one local text memo on the C300X. |
| `bticino_c300x.delete_latest_video_message` | Deletes the latest video message when supported. |
| `bticino_c300x.delete_latest_text_memo` | Deletes the latest text memo when supported. |
| `bticino_c300x.delete_latest_voice_memo` | Deletes the latest voice memo when supported. |

### Capture Modes

`capture_doorbell_call` defaults to `capture_mode: ring`. Existing Ring Capture
automations and blueprints keep their behavior: audio or an announcement answers
the active Ring Call before recording. To record without ringing the doorbell,
explicitly select `capture_mode: on_demand`. This starts an idle doorstation live
view and records video with optional audio; it does not answer a Ring Call.

Example action for a script or automation; replace `YOUR_C300X_ENTRY_ID` with the
integration entry id:

```yaml
- action: bticino_c300x.capture_doorbell_call
  data:
    entry_id: YOUR_C300X_ENTRY_ID
    capture_mode: on_demand
    duration_seconds: 5
    include_audio: true
  response_variable: capture
```

Set `include_audio: false` for video only. Both modes accept durations from
`1` to `15` seconds. MP4 files default to `/media/c300x/`; WAV audio, JPEG frames
and JSON metadata use the existing capture workspace under `/config/c300x/`
unless configured otherwise. The metadata field `capture_mode` records the
requested mode; native media ownership is not continuously verified. The optional
`response_variable` provides the exact per-recording paths, such as
`{{ capture.output_path }}` and `{{ capture.metadata_path }}`; use these in
follow-up actions instead of the mutable `latest` pointers.

On-demand capture checks for idle media before opening its recording client and
rejects a reported busy or unclear state. The native API does not reserve the
media owner across this check and RTSP setup. A physical call that begins during
setup can change the stream, so the recording may fail or include Ring video.
On-demand capture does not answer or hang up a Ring Call. Completion, failure or
cancellation closes its own recording client. `announcement_path` is supported
only in `ring` mode and is rejected before starting an on-demand capture.

Use an integration build that includes `capture_mode`. Native agent **2.1.0**
already provides the required media API; this feature needs no agent update.

## Device Activations

Device activations are configured from setup, options, or reconfigure. They are
not raw JSON input for normal users.

Modes:

- **Automatic** keeps the generated stair-light activation out of the payload and
  uses activation items as configured by the user or reported by the agent.
- **Manual** reserves the `stair_light` id and generates one stair-light item
  from P/N address parts. This leaves up to 15 additional user-managed items.

Limits:

- Maximum total activation items sent to the native agent: `16`.
- Activation IDs: letters, numbers, `_` and `-`, up to 32 characters.
- Activation address: OpenWebNet `where` value, up to 31 characters.
- Activation names: up to 63 characters.

## Media and Audio

Live browser media uses Home Assistant's WebRTC provider/go2rtc. The native
agent exposes RTSP sources for:

- ring preview video,
- answered Ring Call audio/video with talkback backchannel,
- on-demand doorstation audio/video,
- Home Call audio.

Audio gain options:

- **Doorstation live audio gain** affects on-demand and Ring Call downstream
  audio. Default is `0 dB`.
- **Ring capture audio gain** affects Ring Capture WAV/MP4 processing. Default
  is `6 dB`.
- The allowed range is `-20 dB` to `+20 dB`.
- At `0 dB`, live audio stays on the neutral path and the integration avoids
  unnecessary gain updates.

## Expert Notes

- The native-agent API contract is documented in
  [Native Agent API](../native_agent/API.md).
- Runtime packaging and release-agent reuse rules are documented in
  [Native agent](native-agent.md).
- Release hardware checks are documented in
  [Release validation](release-validation.md).
- Security exceptions for local-only SSH bootstrap and MQTT transport are
  documented in [Security](../SECURITY.md).
