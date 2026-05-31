# User Guide

## What this integration does

The integration connects Home Assistant to a native C300X device agent running
locally on the BTicino Classe 300X / C300X. Home Assistant owns the entities,
services, automations and media routing. The native agent performs the local
device work and pushes events back to Home Assistant.

## Supported device scope

- BTicino Classe 300X / C300X.
- Tested against the `1.7.x` firmware family.
- Requires a rooted or SSH-enabled C300X for native-agent installation.

Stock, unrooted devices are not install targets for this integration by
themselves. Rooting/SSH enablement is outside this repository. One commonly
referenced community firmware-patching project is:

```text
https://github.com/fquinto/bticinoClasse300x
```

## Supported functions

- Door unlock action/button.
- Stair light action/button with configurable OpenWebNet address.
- Doorbell ring event and device-agent event stream.
- On-demand doorbell camera through Home Assistant WebRTC handling.
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

## Installation flow

1. Install the Home Assistant custom integration through HACS or manually.
2. Restart Home Assistant.
3. Add **BTicino C300X** from **Settings** -> **Devices & services**.
4. Enter the C300X host and API port.
5. If the native agent is missing, use the installer step on a rooted/SSH-enabled
   device.
6. Configure the generated API token, maintenance token and optional features.

The installer uses SSH credentials only for the installation step. They are not
stored in the config entry, options, diagnostics or logs.

## Token Storage

Installer-based setup generates a device-agent API bearer token and a separate
maintenance token. The C300X stores them in:

```text
/home/bticino/cfg/extra/c300x-native-agent/config.json
```

The JSON fields are `api.token` and `maintenance.adminToken`.

Home Assistant stores its own copy in the integration config entry/options and
uses it automatically. Do not paste token values into logs, issues,
screenshots, commits or documentation.

If the exact value is needed later, use the Home Assistant reconfigure/options
flow when possible. For recovery, read the device config over SSH or set new
tokens through `/setup` while noAuth bootstrap access is still enabled. `/setup`
shows token state and fingerprints only; it does not reveal existing token
values.

## Feature options

Common options:

- Doorbell camera/video.
- Stair-light address.
- Display GUI integration.
- Alarmo entity for the C300X display page.
- Weather entity for the C300X display page.
- Dynamic Home Assistant dashboard JSON.
- Keep dashboard open after a display-side action.

The GUI patch is explicit. It is not applied by normal Home Assistant startup.
The patch writes only changed QML files, keeps one original backup, and restores
the root filesystem to read-only after the final copy.

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
- `bticino_c300x.alarm_command` for the Alarmo display workflow
- `bticino_c300x.unlock_door`
- `bticino_c300x.stair_light`
- `bticino_c300x.reboot`
- `bticino_c300x.reload_gui`
- `bticino_c300x.play_latest_video_message`
- `bticino_c300x.delete_latest_video_message`
- `bticino_c300x.play_latest_voice_memo`
- `bticino_c300x.delete_latest_voice_memo`
- `bticino_c300x.delete_latest_text_memo`

The `Remove device agent` maintenance button restores supported GUI/firewall
patches first, removes agent-owned files and backups, and leaves SSH running.

## IPv6

IPv6 is not required for a basic local install. It is still worth enabling when
your Home Assistant host and the C300X both have stable ULA or global IPv6
addresses. In mixed networks, Home Assistant, browsers, and HA Cloud/WebRTC
paths may prefer IPv6; having the agent reachable on a stable IPv6 path avoids
unreliable fallbacks through link-local names or IPv4-only routing.

Do not use link-local callback URLs unless you intentionally include and manage
the interface scope. Keep the C300X agent local-only, and enable the IPv6
firewall patch only when the network and device are configured for IPv6.

## Troubleshooting

### Integration cannot connect

- Check the agent host and port.
- Check the API token.
- Open `http://<agent-host>:8091/api/v1/health`.
- Check firewall/VLAN routing.
- If IPv6 is enabled, avoid link-local Home Assistant callback URLs for media
  paths unless that is intentional.

### Entities are missing

Check:

```text
GET /api/v1/capabilities
```

Missing capabilities mean missing entities by design.

### Camera does not start

- Enable video in the integration options.
- Ensure the installed native agent has video enabled.
- Check that Home Assistant can reach the media port.
- Prefer stable IPv4 or ULA/global IPv6 addresses over link-local names.

### Messages or memos do not update

Check the event subscription status and relevant message/memo capabilities. The
agent should push changes; it should not need periodic scans.

## Removal

1. Use the `Remove device agent` maintenance button when available.
2. Confirm that GUI/firewall patches are restored and SSH remains reachable.
3. Remove the Home Assistant integration entry.
4. For manual HA installs, remove `/config/custom_components/bticino_c300x/`.
