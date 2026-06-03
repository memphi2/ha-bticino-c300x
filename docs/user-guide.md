# User Guide

## What this integration does

The integration connects Home Assistant to a native C300X device agent running
locally on the BTicino Classe 300X / C300X. Home Assistant owns the entities,
services, automations and media routing. The native agent performs the local
device work and pushes events back to Home Assistant.

The normal user experience should be simple: install the Home Assistant custom
integration, install or update the native agent through the setup/Repair flow,
choose the features you want, and then use the C300X as a local push-based Home
Assistant device.

## Before you start

- BTicino Classe 300X / C300X.
- Tested against the `1.7.x` firmware family.
- Requires a rooted or SSH-enabled C300X for native-agent installation.
- Requires a trusted local network path from Home Assistant to the C300X.

Stock, unrooted devices are not install targets for this integration by
themselves. Rooting/SSH enablement is outside this repository. One commonly
referenced community firmware-patching project is:

```text
https://github.com/fquinto/bticinoClasse300x
```

The integration installer can install the native agent on an already
rooted/SSH-enabled device. It cannot root a stock device.

## Supported functions

- Door unlock action/button.
- Stair light action/button with configurable OpenWebNet address.
- Doorbell ring event and device-agent event stream.
- On-demand doorbell camera through Home Assistant WebRTC handling.
- Two-way audio/talkback through the Home Assistant WebRTC camera path when the
  frontend has microphone access.
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

- Open the doorbell camera from Home Assistant when you need video.
- Use the camera WebRTC/talkback control when the frontend has microphone
  access.
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
- `bticino_c300x.reboot`
- `bticino_c300x.reload_gui`
- `bticino_c300x.play_latest_video_message`
- `bticino_c300x.delete_latest_video_message`
- `bticino_c300x.play_latest_voice_memo`
- `bticino_c300x.delete_latest_voice_memo`
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

## Doorbell video automation

Use `bticino_c300x.activate_doorbell_video` in a ring automation to pre-warm the
C300X video session before a dashboard or notification opens the camera.

```yaml
alias: C300X ring video prewarm
mode: restart
trigger:
  - platform: event
    event_type: bticino_c300x_agent_event_received
    event_data:
      event_key: doorbell_pressed
action:
  - service: bticino_c300x.activate_doorbell_video
    data:
      audio: true
```

Talkback requires the camera WebRTC path, a native agent that reports talkback
support, and browser/mobile microphone permission. Browser microphone access
requires HTTPS, Home Assistant Cloud, or another secure Home Assistant frontend
URL.

## IPv6

IPv6 is not required for a basic local install. It is still worth enabling when
your Home Assistant host and the C300X both have stable ULA or global IPv6
addresses. In mixed networks, Home Assistant, browsers, and HA Cloud/WebRTC
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
addresses when they are not needed, local backups, firmware files or packet
captures with private data.
