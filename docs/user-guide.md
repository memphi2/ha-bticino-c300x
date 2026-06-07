# User Guide

## What this integration does

This local-first, app-like Home Assistant custom integration connects Home
Assistant to a native C300X device agent running locally on the BTicino Classe
300X / C300X. Home Assistant owns the entities, services, automations and media
routing. The native agent performs the local device work and pushes events back
to Home Assistant.

The normal user experience should be simple: install the Home Assistant custom
integration, install or update the native agent through the setup/Repair flow,
choose the features you want, and then use the C300X as a local push-based Home
Assistant device.

Version 1.0.0 focuses on three app-like media workflows:

- **On-demand**: open the door camera from Home Assistant when nobody is
  ringing.
- **Ring Call**: when smartphone forwarding is enabled, answer the real
  incoming doorbell call from Home Assistant with video, device audio and
  microphone talkback.
- **Home Call**: call the C300X from Home Assistant as an audio-only in-house
  call.

## Before you start

- BTicino Classe 300X / C300X.
- Tested against the `1.7.x` firmware family. If your separate rooting or
  SSH-enablement workflow asks for a firmware target, select `1.7.19`.
- Requires a rooted or SSH-enabled C300X for native-agent installation.
- Requires a trusted local network path from Home Assistant to the C300X.

Stock, unrooted devices are not install targets for this integration by
themselves. Rooting/SSH enablement is outside this repository. One commonly
referenced community firmware-patching project is:

```text
https://github.com/fquinto/bticinoClasse300x
```

Use that kind of workflow at your own risk, without warranty, and only where it
is legal for your device and jurisdiction.

The integration installer can install the native agent on an already
rooted/SSH-enabled device. It cannot root a stock device.

## Supported functions

- Door unlock action/button.
- Stair light action/button with configurable OpenWebNet address.
- Doorbell ring event and device-agent event stream.
- On-demand doorbell camera through Home Assistant camera handling.
- App-like doorbell Ring Call answer/hang-up with video, device audio and
  talkback.
- Audio-only Home Call from Home Assistant to the C300X.
- Two-way audio/talkback through the Home Assistant camera path when the
  frontend has microphone access over HTTPS or Home Assistant Cloud.
- Ringer mute state/control.
- Smartphone forwarding state/control.
- Answering machine state and stored video-message counters/playback/delete.
- Manual text memo visibility/delete.
- Manual voice memo counters/playback/delete.
- Optional display dashboard bridge for Alarmo and Home Assistant pages.
- Optional mDNS bootstrap discovery.
- Optional maintenance controls such as SSH, reboot, GUI reload, GUI patch,
  firewall patches and remove-agent.

Entities are capability-gated. If the installed agent does not advertise a
function, Home Assistant does not create that entity.

## Setup flow

1. Install the Home Assistant custom integration through HACS or manually.
2. Restart Home Assistant.
3. Add **BTicino C300X** from **Settings** -> **Devices & services**.
4. Enter the C300X host and API port.
5. If the native agent is missing, use the installer step on a rooted/SSH-enabled
   device.
6. Configure the generated API token, maintenance token and optional features.

The installer uses SSH credentials only for the installation step. They are not
stored in the config entry, options, diagnostics or logs.

Recommended first setup:

- Enable doorbell camera/video when you want video or talkback in Home
  Assistant.
- Keep **Create Home Assistant media user** enabled unless you already manage a
  dedicated media user on the C300X yourself.
- Enable the display GUI patch only when you want Alarmo or Home Assistant pages
  on the physical C300X display.
- Select an Alarmo entity only when you actually use Alarmo.
- Select a weather entity only when you want weather on the C300X display page.
- Leave destructive maintenance options disabled until needed.
- Keep noAuth bootstrap access temporary. Turn it off after tokens are set.

## Tokens

Installer-based setup generates a device-agent API bearer token and a separate
maintenance token. The C300X stores them in:

```text
/home/bticino/cfg/extra/c300x-native-agent/config.json
```

The JSON fields are `api.token` and `maintenance.adminToken`.

Home Assistant stores its own copy in the integration config entry/options and
uses it automatically. Do not paste token values into logs, issues,
screenshots, commits or documentation.

If the exact value is needed later, read it from the device config over SSH. The
agent `/setup` page shows token state and fingerprints only; it does not reveal
existing token values. If noAuth bootstrap access is still enabled, `/setup` can
set new tokens.

## Feature options

Common options:

- Doorbell camera/video.
- Create Home Assistant media user for video, Ring Call and Home Call media.
- Stair-light address.
- Display GUI integration.
- Alarmo entity for the C300X display page.
- Weather entity for the C300X display page.
- Dynamic Home Assistant dashboard JSON.
- Keep dashboard open after a display-side action.
- Native MQTT bridge migration.
- Optional mDNS bootstrap discovery.
- Optional maintenance actions.

The GUI patch is explicit. It is not applied by normal Home Assistant startup.
The patch writes only changed QML files, keeps one original backup, and restores
the root filesystem to read-only after the final copy.

Keep these options disabled unless you need them:

- GUI patching, when you do not use the C300X display pages.
- IPv4/IPv6 firewall patching, unless the device firewall blocks the selected
  ports.
- SSH maintenance, except during recovery or manual work.
- Remove device agent, except when uninstalling the device-side runtime.
- Native MQTT bridge, unless you intentionally migrate away from an older
  device-side MQTT patch.

## Everyday use

After setup, typical interaction happens through Home Assistant entities:

- Use the doorstation card's play button for on-demand camera viewing.
- Press **Answer** in the doorstation card when the doorbell rings to take over
  the real Ring Call.
- Use the Home Call card to call the C300X from Home Assistant and hang up from
  either side.
- Use the talkback control only from a secure Home Assistant frontend
  with microphone permission.
- Use the door unlock and stair-light buttons/services for direct actions.
- Toggle ringer mute, smartphone forwarding and answering machine through their
  switches.
- View, play or delete stored video messages and voice/text memos when the agent
  reports those capabilities.
- Use the optional display pages on the C300X when the GUI patch and display
  bridge are enabled.

Maintenance entities are intentionally separate from everyday controls. Keep
SSH, reboot, firewall patching, GUI patching and remove-agent disabled unless
you are actively using them.

## Home Assistant media user

Doorbell video, Ring Call and Home Call need a local C300X media identity. The
setup and reconfigure flow can create a dedicated device-side `homeassistant`
user for that purpose.

Rules:

- If the `homeassistant` user exists, the agent uses it first.
- If it does not exist but an app-created C300X user exists, the agent can use
  that existing user as a fallback.
- If no usable user exists while video/Home Call/Ring Call features are enabled,
  Home Assistant raises a Repair so you can create the dedicated user.
- Generated user IDs must be random and device-local. Never copy real phone/app
  UUIDs, account IDs or other private identifiers into code, documentation,
  examples or issues.
- To remove the user, delete it from the C300X display/user management UI and
  then rerun the Repair or reconfigure flow.

Media-related entities expose a compact `media_user` attribute when the agent
reports which media identity is being used.

## Alarmo Display Page

The C300X alarm display page is built and tested for
[Alarmo](https://github.com/nielsfaber/alarmo). It mirrors Alarmo-style state,
readiness, bypass, delay and code behavior exposed through Home Assistant.
Other `alarm_control_panel` entities may share the same Home Assistant domain,
but they are not guaranteed to provide the same readiness and bypass semantics.

Thanks to Niels Faber, the developer of Alarmo, for building and maintaining the
Home Assistant alarm integration this display page is designed around.

## Data updates

- Normal state updates are push/event driven.
- There is no periodic polling loop for doorbell, ringer, forwarding, messages
  or memos.
- The camera starts on demand when Home Assistant opens the stream.
- Optional system metrics are disabled by default and push only on meaningful
  change or heartbeat when enabled.

## Services

The integration can register these services, depending on capabilities:

- `bticino_c300x.run_action`
- `bticino_c300x.run_device_activation`
- `bticino_c300x.alarm_command` for the Alarmo display workflow
- `bticino_c300x.unlock_door`
- `bticino_c300x.stair_light`
- `bticino_c300x.activate_doorbell_video`
- `bticino_c300x.stop_doorbell_video`
- `bticino_c300x.start_home_call`
- `bticino_c300x.stop_home_call`
- `bticino_c300x.reboot`
- `bticino_c300x.reload_gui`
- `bticino_c300x.play_latest_video_message`
- `bticino_c300x.delete_latest_video_message`
- `bticino_c300x.play_latest_voice_memo`
- `bticino_c300x.delete_latest_voice_memo`
- `bticino_c300x.write_text_memo`
- `bticino_c300x.delete_latest_text_memo`

The `Remove device agent` maintenance button restores supported GUI/firewall
patches first, removes agent-owned files and backups, and leaves SSH running.

## Device activations

The native agent can expose configured original C300X Quick Actions as Home
Assistant buttons and as `bticino_c300x.run_device_activation`. These are read
from the agent configuration and only appear when the agent advertises the
`activations` capability. Automatic discovery is deliberately conservative:
unknown OpenWebNet frames are not imported as runnable Home Assistant buttons.
Manually configured actions may still use explicit allowlisted commands.

Activation addresses support two modes:

- `manual`: the JSON item contains the OpenWebNet `address`/`where` value.
- `auto`: the address is expected to come from device-side discovery. Until the
  agent has discovered a concrete address or explicit command, the item is
  reported but not exposed as a runnable Home Assistant button.

The star/favorites button on the C300X display is not a separate action. It
adds an existing C300X object to the display homepage. If that linked object is
a safe lock or stair-light action, the integration can expose
the object itself as a Home Assistant button. The favorite marker is only
metadata.

## Doorbell video, Ring Call and Home Call

The media workflows are intentionally separate:

- **On-demand** starts the normal camera stream when nobody is ringing.
- **Ring Call** answers the real incoming doorbell call reported by the agent
  while smartphone forwarding is enabled.
- **Home Call** starts an audio-only call from Home Assistant to the C300X.

Use `bticino_c300x.activate_doorbell_video` only for on-demand camera
pre-warm/start. Use `bticino_c300x.stop_doorbell_video` or the `Stop doorbell
video` button as the doorstation hang-up action. Use
`bticino_c300x.start_home_call` and `bticino_c300x.stop_home_call` for Home Call.

When smartphone forwarding is `blocked`, the C300X still emits a doorbell ring
event but does not deliver a real SIP ring call to Home Assistant. The
doorstation card therefore does not show **Answer** in that state; use
**Stream** for on-demand viewing. A separate HA-only `in-house only` ring mode
is planned for a later release and is not part of 1.0.0 behavior.

The integration bundles the `custom:c300x-doorbell-call-card` Lovelace card and
loads it automatically. Add it from the Lovelace card picker or use YAML. The
card editor is localized in English, German, French and Italian. It only needs
the camera entity; related doorbell and Home Call state entities are discovered
through the same config entry. This keeps multiple C300X devices clean without
manual `state_entity` fields.

Add two cards when you want the full 1.0.0 UI:

- one normal doorstation card for On-demand and Ring Call,
- one Home Call card for the audio-only in-house call.

Dashboard card:

```yaml
type: vertical-stack
cards:
  - type: custom:c300x-doorbell-call-card
    entity: camera.bticino_c300x_doorbell_camera
    name: C300X Door Station
  - type: custom:c300x-doorbell-call-card
    entity: camera.bticino_c300x_doorbell_camera
    mode: home_call
    name: C300X Home Call
```

### HTTPS and microphone requirements

Talkback needs microphone access in the Home Assistant frontend. Use HTTPS,
Home Assistant Cloud, or another secure frontend URL. Plain HTTP is not a
reliable microphone path except for browser-specific localhost exceptions. In
mobile notifications, the **Answer** action should open the Home Assistant
dashboard so the user starts the media session from the card with microphone
permission.

### Mobile notification examples

The Companion App supports actionable notifications on Android and iOS. It can
also display camera content in notifications through `entity_id` or platform
attachment behavior. Keep action ids unique if several door-call automations can
run at the same time.

Replace `/dashboard-c300x/door` with the dashboard path that contains your
C300X doorstation card. The notification does not auto-answer the call; it opens
the card so the user can press **Answer** and start talkback with
microphone permission. The doorstation card can answer only a real Ring Call
reported by the agent, so keep active mobile push notifications gated behind
`switch.bticino_c300x_smartphone_forwarding` when forwarding is disabled.

```yaml
alias: C300X door call notification
mode: restart
trigger:
  - platform: event
    id: ring
    event_type: bticino_c300x_agent_event_received
    event_data:
      event_key: doorbell_pressed
  - platform: event
    id: hangup
    event_type: mobile_app_notification_action
    event_data:
      action: C300X_HANGUP_DOOR_CALL
action:
  - choose:
      - conditions:
          - condition: trigger
            id: ring
        sequence:
          - choose:
              - conditions:
                  - condition: state
                    entity_id: switch.bticino_c300x_smartphone_forwarding
                    state: "on"
                sequence:
                  - service: notify.mobile_app_phone
                    data:
                      title: Doorbell
                      message: Someone is at the door
                      data:
                        entity_id: camera.bticino_c300x_doorbell_camera
                        tag: c300x-door-call
                        group: c300x
                        actions:
                          - action: URI
                            title: Answer
                            uri: /dashboard-c300x/door
                            activationMode: foreground
                          - action: C300X_HANGUP_DOOR_CALL
                            title: Hang Up
                            destructive: true
                          - action: URI
                            title: Dashboard
                            uri: /dashboard-c300x/door
      - conditions:
          - condition: trigger
            id: hangup
        sequence:
          - service: bticino_c300x.stop_doorbell_video
```

Android high-priority/alarm-stream example:

```yaml
service: notify.mobile_app_pixel
data:
  title: Doorbell
  message: Someone is at the door
  data:
    ttl: 0
    priority: high
    channel: alarm_stream
    entity_id: camera.bticino_c300x_doorbell_camera
    actions:
      - action: URI
        title: Answer
        uri: /dashboard-c300x/door
      - action: C300X_HANGUP_DOOR_CALL
        title: Hang Up
      - action: URI
        title: Dashboard
        uri: /dashboard-c300x/door
```

Android command-webview example:

```yaml
service: notify.mobile_app_pixel
data:
  message: command_webview
  data:
    command: /dashboard-c300x/door
```

iOS critical-alert example:

```yaml
service: notify.mobile_app_iphone
data:
  title: Doorbell
  message: Someone is at the door
  data:
    entity_id: camera.bticino_c300x_doorbell_camera
    push:
      sound:
        name: default
        critical: 1
        volume: 1.0
    actions:
      - action: URI
        title: Answer
        uri: /dashboard-c300x/door
        activationMode: foreground
      - action: C300X_HANGUP_DOOR_CALL
        title: Hang Up
        destructive: true
      - action: URI
        title: Dashboard
        uri: /dashboard-c300x/door
```

Relevant Companion App documentation:

- <https://companion.home-assistant.io/docs/notifications/actionable-notifications/>
- <https://companion.home-assistant.io/docs/notifications/dynamic-content>
- <https://companion.home-assistant.io/docs/notifications/critical-notifications/>
- <https://companion.home-assistant.io/docs/notifications/notification-commands/>

## IPv6

IPv6 is not required for a basic local install. It is still worth enabling when
your Home Assistant host and the C300X both have stable ULA or global IPv6
addresses. In mixed networks, Home Assistant, browsers, and HA Cloud media
paths may prefer IPv6; having the agent reachable on a stable IPv6 path avoids
unreliable fallbacks through link-local names or IPv4-only routing.

Do not use link-local callback URLs unless you intentionally include and manage
the interface scope. Keep the C300X agent local-only, and enable the IPv6
firewall patch only when the network and device are configured for IPv6.

Do not use `homeassistant.local`, other `.local` names, or link-local addresses
for the Home Assistant callback URL used by this integration. Use a stable local
IPv4 address or a stable ULA/global IPv6 address so event subscriptions, camera
streams and talkback all use a predictable route.

If the generated callback URL is still wrong for your topology, set `Local Home
Assistant callback base URL` in setup, reconfigure or options. Enter only the
local HTTP base such as `http://192.0.2.10:8123`; Home Assistant keeps the
generated webhook path and token. HTTPS, `.local`, loopback, link-local,
credentials and paths are rejected.

## Troubleshooting

### Integration cannot connect

Check these in order:

1. The C300X is powered on, connected to Wi-Fi and reachable from Home
   Assistant.
2. `http://<agent-host>:8091/api/v1/health` opens from the Home Assistant
   network.
3. The API token in Home Assistant matches `api.token` on the device.
4. The firewall patch is enabled only if your C300X needs it for the configured
   API/media ports.
5. The Home Assistant callback URL is a stable local HTTP URL. Do not use
   `.local`, loopback, unspecified, or link-local callback addresses.

### Entities are missing

Entities are capability-gated. First check:

```text
GET /api/v1/capabilities
```

Missing capabilities mean missing entities by design. If a capability should be
there, check that the feature is enabled in options, the agent is current, and
there is no pending Home Assistant Repair for an agent update.

### Camera does not start

- Enable video in the integration options.
- Ensure the installed native agent has video enabled.
- Check that Home Assistant can reach the media port.
- Prefer stable IPv4 or ULA/global IPv6 addresses over `.local`, mDNS or
  link-local names.
- For browser talkback/microphone access, open Home Assistant through HTTPS,
  Home Assistant Cloud, or another secure frontend URL.
- After a major native-agent upgrade, if media entities, capabilities or call
  controls stay inconsistent, use `Remove device agent`, remove the integration
  entry, then reinstall the integration and native agent cleanly.

### Messages or memos do not update

Check the event subscription status and relevant message/memo capabilities. The
agent should push changes; it should not need periodic scans. If the C300X
display still shows an old unread counter after a delete, open diagnostics and
check whether the GUI patch is active and whether the memo/message event was
delivered.

## Removal

1. Use the `Remove device agent` maintenance button when available.
2. Confirm that GUI/firewall patches are restored and SSH remains reachable.
3. Remove the Home Assistant integration entry.
4. For manual HA installs, remove `/config/custom_components/bticino_c300x/`.

## Support Checklist

When asking for help, include:

- integration version,
- native agent version,
- C300X firmware version when known,
- whether video, GUI patch, MQTT bridge and IPv6 are enabled,
- whether the problem happens on Home Assistant startup, device reboot, doorbell
  ring, camera open, or manual button press,
- a Home Assistant diagnostics download for this integration.

Do not include passwords, tokens, usernames, private hostnames, private IP
addresses when they are not needed, local backups, firmware files, network
traces or other private data.
