# BTicino Classe 300X for Home Assistant (Unofficial)

[![Validate](https://img.shields.io/badge/checks-local%20%2B%20CI-2ea44f?style=flat-square)](.github/workflows/validate.yml)
[![Quality](https://img.shields.io/badge/Quality-HA%20QS%20Platinum%20Track-0366d6?style=flat-square)](custom_components/bticino_c300x/quality_scale.yaml)
[![Release](https://img.shields.io/badge/release-v1.1.0-0366d6?style=flat-square)](.github/release-notes/v1.1.0.md)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/)
[![License Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

Local-first, app-like Home Assistant custom integration for the BTicino Classe
300X / C300X video door station.

The project pairs a Home Assistant integration with a small native C agent on
the C300X. The goal is a quiet, local, event-driven setup: no Node.js runtime on
the device, no polling controller, no cloud dependency for normal operation, and
no fake Home Assistant entities.

<p align="center">
  <img src="custom_components/bticino_c300x/brand/logo.png" alt="BTicino C300X integration logo" width="140">
</p>

## Status

- Current release line: `1.1.0`
- Home Assistant requirement: `2026.5.0` or newer
- IoT class: `local_push`
- HACS type: custom integration with `zip_release`
- Quality target: Home Assistant Quality Scale Platinum track
- License: Apache-2.0
- Support scope: community project, not an official BTicino/Legrand or Home
  Assistant Core integration

## Is this for you?

Use this integration when you want your Classe 300X to behave like a local Home
Assistant device: doorbell events, camera, talkback, door unlock, stair light,
ringer/forwarding controls, messages and optional display pages, all without a
polling controller or a Node.js runtime on the C300X.

The 1.1.0 release adds HA-side Ring Call capture diagnostics, local Whisper
transcription from the retained raw WAV, and an optional strict phrase-match door
unlock evaluation service.

The 1.0.0 line adds the three app-like media workflows that users expect from a
video door station:

- **On-demand**: open the door camera from Home Assistant when nobody is
  ringing.
- **Ring Call**: when someone rings and smartphone forwarding is enabled,
  answer the real incoming door call from Home Assistant with video, device
  audio and talkback.
- **Home Call**: call the C300X from Home Assistant as an audio-only in-house
  call.

Before you start, check these requirements:

- Your C300X must already be rooted or SSH-enabled.
- Home Assistant must be able to reach the C300X on your local network.
- You should be comfortable installing a local device agent on the C300X.
- You should keep the agent API on a trusted LAN only. Do not expose it to the
  internet.

If your device is still completely stock and you do not have SSH/root access
yet, do that first. Rooting and firmware patching are outside this repository.

## Highlights

- Native C device agent for the C300X, built without Node.js or `node_modules`.
- Local push callbacks into Home Assistant instead of periodic polling.
- Bearer-token API plus a separate maintenance token for sensitive actions.
- Capability-gated entities: Home Assistant only shows functions the installed
  agent actually supports.
- Three app-like media workflows: on-demand camera, real ring-call
  answer/hang-up and Home Call.
- Home Assistant camera handling for app-like doorstation video, started only
  when video is needed.
- Two-way audio/talkback through the Home Assistant camera session, when the
  browser or mobile app has microphone access over HTTPS or Home Assistant
  Cloud.
- Audio-only Home Call from Home Assistant to the C300X.
- Door unlock and stair-light actions.
- Ringer mute, smartphone forwarding, answering machine and message support.
- Video-message playback/delete, voice-memo playback/delete and text-memo
  visibility/delete.
- Optional C300X display pages for Alarmo and a dynamic Home Assistant board.
- Multilingual C300X display labels with German, French, Italian and English
  text.
- Optional mDNS bootstrap discovery for Home Assistant Zeroconf.
- Low-noise diagnostics for connection state, write counters and device
  metrics.
- Original C300X Quick Actions can be exposed as Home Assistant buttons when the
  installed agent has a safe address or command for them.

## Screenshots

Screenshots show a representative setup. Exact entities and display pages depend
on the installed agent capabilities and the options enabled in Home Assistant.

### Door Camera Inline Dashboard

<p align="center">
  <img src="docs/images/readme/ha-door-camera-inline-dark.png" alt="BTicino C300X inline door camera dashboard card in Home Assistant dark mode" width="720">
</p>

### Home Assistant Entities

<table>
  <tr>
    <td align="center" valign="top"><strong>Controls</strong><br><img src="docs/images/readme/controls.png" alt="BTicino C300X Home Assistant controls" width="170"></td>
    <td align="center" valign="top"><strong>Sensors / Events</strong><br><img src="docs/images/readme/sensors.png" alt="BTicino C300X Home Assistant sensors" width="170"><br><img src="docs/images/readme/events.png" alt="BTicino C300X Home Assistant device and doorbell events" width="170"></td>
    <td align="center" valign="top"><strong>Configuration</strong><br><img src="docs/images/readme/configuration.png" alt="BTicino C300X Home Assistant configuration entities" width="170"></td>
    <td align="center" valign="top"><strong>Diagnostics</strong><br><img src="docs/images/readme/diagnostic.png" alt="BTicino C300X Home Assistant diagnostic entities" width="170"></td>
  </tr>
</table>

### C300X Display Pages

<table>
  <tr>
    <td align="center"><strong>C300X dashboard</strong><br><img src="docs/images/readme/display-c300x-dashboard.jpeg" alt="BTicino C300X dashboard page" width="320"></td>
    <td align="center"><strong>Alarmo page</strong><br><img src="docs/images/readme/display-alarmo.jpeg" alt="Alarmo page on the BTicino C300X display" width="320"></td>
  </tr>
  <tr>
    <td align="center"><strong>Home Assistant weather page</strong><br><img src="docs/images/readme/display-ha-weather.jpeg" alt="Home Assistant weather page on the BTicino C300X display" width="320"></td>
    <td align="center"><strong>Custom Home Assistant page</strong><br><img src="docs/images/readme/display-custom-ha-page.jpeg" alt="Custom Home Assistant page on the BTicino C300X display" width="320"></td>
  </tr>
</table>

### Display Bridge Output

<p>
  <img src="docs/images/readme/display-bridge-output.png" alt="Dynamic Home Assistant board rendered for the BTicino C300X" width="520">
</p>

## Important Requirement: Rooted C300X

The native agent must run on the C300X device. That means the device must already
be rooted or otherwise SSH-enabled with write access for installing the agent.

This repository does not provide firmware images, firmware extraction output,
APKs, exploits, rooting instructions, or vendor files. If your device is still
stock, you first need a separate, compatible rooting/firmware-patching workflow.
One commonly referenced community project for that topic is:

```text
https://github.com/fquinto/bticinoClasse300x
```

Use that kind of workflow at your own risk, without warranty, and only where it
is legal for your device and jurisdiction. When that workflow asks for a
firmware target, select `1.7.19`; this integration and the packaged native
agent are validated against the `1.7.x` firmware family. After SSH/root access
is available, this integration can install and manage the native agent.

The integration installer can copy the bundled native agent to an already
rooted/SSH-enabled device. It cannot root a stock device for you.

## What You Get in Home Assistant

Exact entities depend on the capabilities reported by your installed agent.

| Platform | Typical entities |
| --- | --- |
| `camera` | Doorbell camera |
| `event` | Standard doorbell ring event, optional diagnostic device-event stream |
| `binary_sensor` | Home Call active state |
| `button` | Door unlock, stair light, reboot, reload GUI, remove device agent, delete latest memo/message |
| `switch` | Ringer mute, smartphone forwarding, answering machine, SSH maintenance, noAuth bootstrap, mDNS, GUI patch, firewall patches |
| `sensor` | Device agent status, doorbell state, message/memo counters, optional device metrics |

The integration also registers services for door unlock, stair light, Alarmo
commands, dashboard actions, Home Call start/stop, latest video-message
playback/delete, latest voice-memo playback/delete, latest text-memo
write/delete and explicit doorbell-video start/stop for automations.

## Installation

### 1. Install the Home Assistant integration

HACS custom repository:

1. Open **HACS**.
2. Go to **Integrations**.
3. Open **Custom repositories**.
4. Add this repository:

   ```text
   https://github.com/memphi2/ha-bticino-c300x
   ```

5. Category: **Integration**.
6. Install **BTicino C300X**.
7. Restart Home Assistant.

Manual Home Assistant install:

```bash
mkdir -p /config/custom_components
cp -a custom_components/bticino_c300x /config/custom_components/
```

Then restart Home Assistant.

The HACS release asset is `ha-bticino-c300x.zip`. It contains both the Home
Assistant integration and the matching ARMHF native-agent bundle. Normal users
should not need Node.js, npm, a cross compiler, or SSH helper tools inside Home
Assistant.

### 2. Add the integration

In Home Assistant:

```text
Settings -> Devices & services -> Add integration -> BTicino C300X
```

The setup flow first asks for the C300X address and local agent API port. In
most installations the API port is `8091`.

- If the native agent is already reachable, setup continues with token and
  feature configuration.
- If the agent is not reachable, setup offers an explicit installer step for a
  rooted/SSH-enabled C300X.

The installer uses the SSH username/password only for that install step. The
credentials are not stored in the Home Assistant config entry, options,
diagnostics, or logs.

Recommended first-run choices:

- Enable the GUI patch only if you want the C300X display pages.
- Enable the doorbell camera if you want video, ring-call handling, Home Call
  or talkback in Home Assistant.
- Leave **Create Home Assistant media user** enabled unless you already manage a
  dedicated C300X user yourself. The agent prefers that `homeassistant` media
  identity when present and falls back to an existing app-created user only when
  no Home Assistant user exists.
- Select an Alarmo entity only when you use Alarmo.
- Select a weather entity only when you want it on the C300X display page.
- Leave destructive maintenance functions disabled until you need them.
- Keep the generated API and maintenance tokens; they are required for later
  reconfiguration and maintenance.

Feature choices are reversible from the integration options. Device-changing
maintenance actions are still explicit: the integration should not patch the
GUI, change firewall scripts, reboot the device, or remove the agent just
because Home Assistant starts.

### 3. Tokens and Recovery

During installer-based setup, Home Assistant generates two random tokens:

- the device-agent API bearer token
- the maintenance token for sensitive actions such as reboot, GUI patching,
  firewall patching and remove-agent

The installer writes both tokens into the C300X agent config:

```text
/home/bticino/cfg/extra/c300x-native-agent/config.json
```

The JSON fields are:

```text
api.token
maintenance.adminToken
```

Home Assistant stores its own copy in the integration config entry/options and
uses it automatically. Do not copy these values into issues, logs, screenshots,
commits or documentation.

If you need the exact token later, read it from the device config path above
over SSH. The agent `/setup` page shows whether tokens are configured and their
fingerprints, but it does not reveal existing token values. If noAuth bootstrap
access is still enabled, `/setup` can set new tokens. After setup, turn noAuth
off.

### 4. What the installer puts on the device

The installer deploys project-owned files only:

- ARMHF native C agent binary
- generated `config.json` with generated API and maintenance tokens
- init/start script for the native agent
- QML support files for the optional C300X display pages
- QML patch helper script
- optional firewall helper state managed by the native agent

The installer does not ship vendor firmware, extracted firmware files, APKs,
Node modules, or third-party controller code.

### 5. Choose optional features

The feature step lets you enable only what you need:

- Doorbell camera/video
- Home Assistant media user for video, ring-call and Home Call media identity
- C300X display GUI integration
- Alarmo entity for the display page
- Weather entity for the display page
- Dynamic Home Assistant board JSON
- Native MQTT bridge migration
- Stair-light address
- Optional maintenance controls

The GUI patch is explicit. Normal Home Assistant startup must not patch the
device UI. When enabled, the patch process backs up original QML files once,
renders the target files, compares byte-for-byte, writes only changed files,
remounts the root filesystem writable only for the final copy, and returns it to
read-only immediately afterwards.

### 6. After setup

After setup, verify these basics:

- `sensor.bticino_c300x_device_agent_status` should show `ok`.
- The device-agent version should match the integration release or show an
  update Repair.
- `camera.bticino_c300x_doorbell_camera` should be present when video is
  enabled.
- `sensor.bticino_c300x_doorbell_state` should change only from real agent
  doorbell/media events.
- `binary_sensor.bticino_c300x_home_call_active` should follow real Home Call
  start, answer and end events.
- Maintenance entities that can change the device should stay disabled until
  actively needed.

## Home Assistant Media User

Doorbell video, ring-call media and Home Call need a local C300X media
identity. The integration can create a dedicated device-side user named
`homeassistant` during setup or reconfigure. This is preferred because it keeps
Home Assistant separate from personal phone/app users.

The user-management rules are deliberately conservative:

- If the `homeassistant` user exists, the agent uses it for media.
- If it does not exist but another valid C300X app user exists, the agent can
  use that existing user as a fallback.
- If no usable user exists and media features are enabled, Home Assistant raises
  a Repair so you can create the dedicated user.
- The generated user identity is device-local and must be random. Do not copy
  phone/app UUIDs, app account ids or other private identifiers into
  configuration, commits, logs or documentation.
- If you want to remove the user, delete it from the C300X display/user
  management UI and rerun the integration Repair or reconfigure flow.

Entities that depend on a media identity expose a compact `media_user`
attribute so you can see whether Home Assistant is using the dedicated user or
an existing fallback without exposing private UUIDs.

## Doorbell Video, Ring Calls and Talkback

There are three user-facing media workflows:

- **On-demand**: press play in the doorstation card when nobody is ringing.
  Home Assistant starts the normal C300X camera path and opens video/audio.
- **Ring Call**: when someone rings and smartphone forwarding is enabled, the
  agent reports the real incoming call/media state. Press **Answer** in Home
  Assistant to take over that call through the app-like Home Assistant workflow,
  with video, device audio and microphone talkback.
- **Home Call**: the Home Call card starts an audio-only call from Home
  Assistant to the C300X. It is intentionally separate from doorbell/ring media.

The `bticino_c300x.activate_doorbell_video` service starts or renews the
on-demand C300X doorbell video session. The
`bticino_c300x.stop_doorbell_video` service ends the active doorbell/on-demand
media session. Use the stop service or card hang-up action; pausing a generic
camera card may not immediately close the native media session.

When smartphone forwarding is `blocked`, the C300X still emits a doorbell ring
event but does not deliver a real SIP ring call to the Home Assistant media
user. In that state the card does not show **Answer**; use **Stream** for
on-demand viewing. A separate HA-only `in-house only` ring mode is planned for a
future release and is not enabled silently by 1.0.0.

The integration bundles the `custom:c300x-doorbell-call-card` Lovelace card and
loads it automatically when the integration is set up. Add it from the card
picker or YAML. The visual editor is localized in English, German, French and
Italian. The setup repair writes the matching Doorbell state and Home Call state
entities into generated cards, and the editor lets you select them explicitly
for renamed or localized entities.

Dashboard example:

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
Home Assistant Cloud, or another secure frontend URL. Plain HTTP generally
cannot grant browser/mobile microphone access except for browser-specific
localhost exceptions. For mobile notifications, the action that answers a call
should open the Home Assistant app/dashboard so the user can grant or reuse
microphone permission and start the media session from the card.

### Mobile notification examples

Home Assistant Companion App actionable notifications can show actions and fire
`mobile_app_notification_action` events. Camera previews can use
`entity_id: camera.bticino_c300x_doorbell_camera`; Android can also use
`/api/camera_proxy/...`, and iOS supports camera streams through dynamic
attachments. See the official Companion App notification documentation for
platform-specific details:

- <https://companion.home-assistant.io/docs/notifications/actionable-notifications/>
- <https://companion.home-assistant.io/docs/notifications/dynamic-content>
- <https://companion.home-assistant.io/docs/notifications/critical-notifications/>
- <https://companion.home-assistant.io/docs/notifications/notification-commands/>

Replace `/dashboard-c300x/door` with the dashboard path that contains your
C300X doorstation card. The notification does not auto-answer the call; it
opens the card so the user can press **Answer** and start talkback with
microphone permission. The doorstation card can answer only a real Ring Call
reported by the agent, so keep mobile push notifications gated behind
`switch.bticino_c300x_smartphone_forwarding` when forwarding is disabled.

Basic shared automation:

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

Android high-priority variant:

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

Android can also be sent directly to the dashboard with a notification command:

```yaml
service: notify.mobile_app_pixel
data:
  message: command_webview
  data:
    command: /dashboard-c300x/door
```

iOS critical-alert variant:

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

Critical alerts require the iOS app/device permission for critical
notifications. Keep notification action ids unique if several automations can
send door-call notifications at the same time.

### MQTT Migration

Some rooted Classe 300X devices already have an older community MQTT patch
installed. That path is useful for existing automations, but it usually runs as
separate helper processes outside this integration. On a small C300X this can
mean extra idle CPU load, duplicate event handling, more filesystem writes, and
unclear ownership when Home Assistant and the old patch both try to represent
the same device state.

This integration therefore includes an optional native MQTT bridge in the C
agent. It is meant as a controlled migration path, not as a second mandatory
transport. The bridge can use the broker settings you configure in the agent
JSON and can expose legacy-compatible topics for setups that still depend on
them. Only one MQTT path should be active at a time: either keep the legacy
bridge disabled, or migrate to the native bridge and disable/remove the old
device-side MQTT patch through the maintenance controls.

The migration is explicit. The installer and maintenance entities can detect
whether legacy MQTT support is present, back up device-side legacy files before
removal where needed, and restore them during remove-agent where possible. The
goal is to keep old automations working while moving runtime work into the
single low-idle native agent.

### Alarmo Display Page

The C300X alarm display page is built and tested for
[Alarmo](https://github.com/nielsfaber/alarmo). It uses Alarmo-style state,
readiness, bypass and code behavior exposed through Home Assistant. Other
`alarm_control_panel` entities may expose the same basic entity domain, but they
are not guaranteed to provide the same readiness and bypass semantics.

Thanks to Niels Faber, the developer of Alarmo, for building and maintaining the
Home Assistant alarm integration this display page is designed around.

### IPv6 Recommendation

IPv6 is optional, but recommended when your Home Assistant network already uses
stable IPv6 addressing. Home Assistant, browsers, and HA Cloud media paths may
prefer IPv6 when it is available; enabling the agent's IPv6 firewall support
lets those callbacks and camera sessions use the same predictable network path
instead of falling back to fragile name resolution or link-local addresses.

Use stable ULA or global IPv6 addresses for Home Assistant and the C300X. Avoid
link-local callback URLs such as addresses that require an interface suffix.
The IPv6 firewall patch should only be enabled when the device and your network
are actually configured for IPv6, and the agent must still remain on a trusted
local network.

## Callback and Video Addressing

Do not configure Home Assistant callbacks or C300X media paths through
`homeassistant.local`, other `.local` names, or link-local addresses. They can
resolve differently for Home Assistant, the C300X, browsers and HA Cloud, which
can leave event subscriptions registered to an address the device cannot call
back or make video/talkback unstable.

Use a stable local IPv4 address or a stable ULA/global IPv6 address for the Home
Assistant URL used by this integration. The diagnostics page reports the
callback host type and whether the subscription callback looks like a clean
local HTTP address.

If Home Assistant generates a poor callback address for your network, set the
`Local Home Assistant callback base URL` option during setup or reconfigure. Use
only the local HTTP base, for example `http://192.0.2.10:8123`. The integration
keeps the generated webhook path and token intact and replaces only the callback
scheme, host and port sent to the device agent. Do not put HTTPS, `.local`,
loopback, link-local, usernames, passwords or paths into this field.

Use the override only when Home Assistant generates a callback URL the C300X
cannot reach, for example `homeassistant.local` or a link-local IPv6 address.
Most single-LAN IPv4 setups do not need this option.

## Device Quick Actions

The C300X can store original Quick Actions such as locks, stair lights,
automation actions, cameras or intercom shortcuts. The integration exposes only
actions the native agent can represent safely.

Address handling has two modes:

- `manual`: the action JSON contains the OpenWebNet `address`/`where` value.
- `auto`: the agent is expected to discover the address from the device-side
  model. Automatic discovery is deliberately conservative: unknown OpenWebNet
  frames are not exposed as runnable Home Assistant buttons.

The star/favorites button on the C300X display is not a separate Home Assistant
action. It only marks an existing C300X object as a homepage quick action. The
linked object may become a Home Assistant button if it is executable and safely
identified.

## Security Model

Use this only on a trusted local network.

- Do not expose the agent API, setup page, display bridge, media ports or the
  C300X device directly to the internet.
- Use strong random API and maintenance tokens.
- Keep `noAuth` disabled after bootstrap.
- Keep noAuth maintenance disabled after bootstrap.
- Keep maintenance functions disabled unless actively needed.
- Mutating API endpoints use `POST`.
- The display UI listener is local to the device and separate from the
  Home-Assistant-facing API.
- Diagnostics redact secrets and avoid private callback URLs.
- The optional SSH installer uses pinned Paramiko legacy SSH support only for
  bootstrap/fallback installation on devices you control; normal agent operation
  uses the local token-protected API.

The native agent intentionally does not include a TLS stack. Use plain HTTP only
on a trusted local segment, or terminate HTTPS in a local reverse proxy if your
network design requires it. Home Assistant Cloud access should go through Home
Assistant's own camera handling, not by exposing the C300X agent.

See [SECURITY.md](SECURITY.md).

## Performance Model

The integration is designed for low idle cost:

- no periodic Home Assistant polling loop for normal C300X state
- persisted event subscriptions instead of webhook rotation on every start
- no background still-image camera polling
- doorstation media starts on demand
- display bridge config is updated only when it differs
- QML patching is explicit and writes only changed files
- diagnostics expose write counters so idle writes are visible

Optional system metrics are disabled by default and should be enabled only when
you actually want device diagnostics.

### Legacy MQTT Diagnostics

The legacy TcpDump2Mqtt bridge and C300X media startup handling are treated as
separate device areas. Disabling legacy MQTT only disables the
`S99TcpDump2Mqtt` autostart link and stops TcpDump2Mqtt helper processes; it
does not restore or rewrite unrelated media startup files.

The `sensor.bticino_c300x_device_agent_status` attributes include a
media-startup reference-state value:

- `legacy_mqtt_patch`: expected state for a device with the legacy
  TcpDump2Mqtt firmware patch. The active media startup file contains the
  legacy restart marker and the backup does not.
- `stock_or_unpatched`: expected state when no legacy MQTT media startup marker is
  present.
- `backup_without_active_marker`: a previous cleanup likely restored the
  media startup backup while legacy MQTT files still exist. If video or the old
  TcpDump2Mqtt watchdog behaves differently than before, restore the device from
  a known-good backup or reapply the legacy MQTT firmware patch.
- `unexpected_backup_marker`, `marker_without_backup` or `missing`: inspect the
  device before changing MQTT state; these are not normal reference states.

## Maintenance and Removal

Maintenance entities are exposed only when the agent advertises support and the
integration is configured with the required token.

Useful maintenance controls can include:

- SSH maintenance switch
- reboot button
- GUI reload button
- GUI patch switch
- IPv4/IPv6 firewall patch switches
- mDNS bootstrap switch
- noAuth bootstrap switches
- remove device agent button

Use **Remove device agent** when you want to uninstall the device-side runtime.
The agent removes its own files, restores GUI/firewall patches first when
possible, and leaves SSH available so the device remains reachable.

## Troubleshooting

### The integration cannot connect

Check these in order:

1. The C300X is online and reachable from Home Assistant.
2. `http://<agent-host>:8091/api/v1/health` opens from the Home Assistant
   network.
3. The API token in Home Assistant matches `api.token` in the device config.
4. The firewall patch is enabled only if your device needs it for the selected
   ports.
5. The callback URL is a reachable local HTTP address, not `.local`, loopback,
   unspecified, or link-local.

### Entities are missing

This is usually capability-gating, not a bug. The integration creates entities
only for features the installed agent reports through `/api/v1/capabilities`.
If a feature is missing:

- make sure it is enabled in the integration options,
- make sure the installed agent is current,
- check for an agent update Repair,
- check the diagnostics download before opening an issue.

### Camera or talkback is unstable

- Keep video enabled in the integration options.
- Avoid `homeassistant.local`, mDNS and link-local callback/media addresses.
- Prefer a stable local IPv4 address or stable ULA/global IPv6 address.
- For microphone/talkback in browsers, access Home Assistant through HTTPS,
  Home Assistant Cloud, or another secure frontend URL.
- After a major native-agent upgrade, if media entities, capabilities or call
  controls stay inconsistent, use `Remove device agent`, remove the integration
  entry, then reinstall the integration and native agent cleanly.

### Messages or memos do not update

Message and memo updates are event-driven. There should be no periodic scan.
Check the event subscription status, memo/message capabilities and diagnostics.
If you delete a message from Home Assistant, the GUI should refresh through the
device UI path, not through a device reboot.

### Before opening an issue

Please include:

- integration version,
- native agent version,
- C300X firmware version when known,
- whether the device is on IPv4, IPv6 or both,
- whether the C300X display GUI patch is enabled,
- which optional features are enabled,
- a Home Assistant diagnostics download for this integration.

Do not include passwords, tokens, local usernames, private hostnames, public IP
addresses, private backups, firmware files, network traces or other private
data.

## Project Background and Attribution

Thanks to SlyOldFox for the public C300X groundwork and original community
controller work, and to Niels Faber for Alarmo, which the optional C300X alarm
page is designed around.

Development has been assisted by OpenAI Codex. The resulting code and
documentation are maintained as normal project artifacts in this repository.

## Legal Notes

This repository is an independent community project.

- Unofficial integration: no affiliation with, endorsement by, or sponsorship
  from BTicino, Legrand, Home Assistant, Nabu Casa, HACS, OpenAI, or the
  referenced community projects.
- Trademark notice: BTicino, Classe 300X, Legrand, Home Assistant, HACS, Nabu
  Casa, OpenAI, Codex and other names are used only for compatibility,
  attribution, or descriptive reference and belong to their respective owners.
- This repository does not include vendor firmware, extracted firmware, APKs,
  third-party controller source trees, local device backups, or secrets.
- This repository does not ship codec binaries or codec implementation source
  code. Doorbell media uses the user's Home Assistant/browser media stack; users
  and distributors are responsible for codec availability and any
  jurisdiction-specific patent or licensing requirements.
- License: Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).

See [docs/legal.md](docs/legal.md) for the full legal and asset-hygiene notes.

## Documentation

| Topic | Document |
| --- | --- |
| User guide | [docs/user-guide.md](docs/user-guide.md) |
| Native agent details | [docs/native-agent.md](docs/native-agent.md) |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Device UI feasibility and safety | [docs/device-ui-feasibility.md](docs/device-ui-feasibility.md) |
| Security policy | [SECURITY.md](SECURITY.md) |
| Privacy notice | [PRIVACY.md](PRIVACY.md) |
| Legal notes | [docs/legal.md](docs/legal.md) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |

## Development Checks

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

.venv/bin/python scripts/check_repo.py
.venv/bin/ruff check .
.venv/bin/python -m pytest
make -C native_agent check
make -C native_agent armhf-abi-check armhf-stack-check
```
