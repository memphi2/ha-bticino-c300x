# Native Agent API Contract

This document describes the HTTP contract exposed by the C300X native agent.
Home Assistant treats this API as a compatibility boundary: response field names,
endpoint paths, authentication rules, side effects, and confirmation tokens
should not change without a deliberate integration migration.

The native binary deliberately serves plain local HTTP only. Deploy it on the
trusted Home Assistant/device segment, or terminate HTTPS in a local reverse
proxy if a site needs TLS.

## Versioning

- HTTP base path: `/api/v1`
- Current packaged agent version: `1.7.0`
- Self-test contract version: `api_version: "1.1"`
- Normal payloads are JSON unless an endpoint explicitly returns binary media.

Agents older than the endpoint they are asked to call respond with
`501 Not Implemented` and `{"ok": false, "error": "not_implemented"}`. Home
Assistant must treat that as unsupported capability, not as a repair signal.

## Listeners

The agent has two HTTP listeners:

- API listener: configured by `listen.host`, `listen.apiPort`, and
  `listen.allowLan`.
- UI listener: loopback display bridge listener, configured by `listen.uiPort`
  and `ui_listen_host`. It is intended for QML pages running on the device.

Public UI listener endpoints are documented separately under
[Loopback UI API](#loopback-ui-api).

## Authentication

There are two independent authorization layers.

### API Token

Normal `/api/v1` endpoints require the configured device-agent API token unless
`api.noAuth=true`.

Clients send the token in the HTTP `Authorization` header using the bearer
scheme. Do not log or expose the header value.

`GET /api/v1/health` is always unauthenticated. `GET /` and `GET /setup` are
served only while `api.noAuth=true`.

### Maintenance Token

Maintenance endpoints require the maintenance token through the
`X-Bticino-C300X-Maintenance-Token` header unless the temporary bootstrap window
`maintenance.allowNoAuth=true` is open.

Maintenance endpoints remain disabled unless `maintenance.enabled=true` and the
individual maintenance module is enabled in config, for example firewall, QML
patching, GUI reload, SSH, or MQTT migration.

### Bootstrap Defaults

`native_agent/config.example.json` intentionally starts with:

- `api.noAuth=true`
- `maintenance.enabled=true`
- `maintenance.allowNoAuth=true`
- empty API and maintenance tokens

This allows first setup through `/setup` or Home Assistant. Once tokens are
configured, setup completion closes `api.noAuth` and noAuth maintenance access.
The setup page never returns token values; it only reports configured flags and
non-secret fingerprints.

## Common Response Rules

Successful JSON responses normally include:

```json
{"ok": true}
```

Error responses normally include:

```json
{"ok": false, "error": "error_code"}
```

Common status codes:

| Status | Meaning |
| --- | --- |
| `200 OK` | Request succeeded. |
| `201 Created` | Runtime subscription was created. |
| `202 Accepted` | Runtime event wake-up was accepted. |
| `400 Bad Request` | Invalid body, missing field, invalid id, or missing confirmation token. |
| `401 Unauthorized` | Normal API token is missing or invalid. |
| `403 Forbidden` | Maintenance token is missing/invalid, endpoint requires loopback, or module is disabled. |
| `404 Not Found` | Setup disabled, media item missing, or feature disabled. |
| `409 Conflict` | Media action conflicts with the current device/media state. |
| `413 Payload Too Large` | HTTP body exceeded the static parser buffer. |
| `500 Internal Server Error` | Agent-side operation failed. |
| `501 Not Implemented` | Endpoint is not implemented by this agent version. |
| `502 Bad Gateway` | Home Assistant callback/display bridge is unavailable. |

Request bodies are parsed from JSON. Unknown fields should be ignored unless the
handler explicitly validates the whole object.

No endpoint should ever echo API tokens, maintenance tokens, webhook tokens,
shared secrets, SIP secrets, raw config file contents, or private callback URLs.
Status endpoints use boolean flags and fingerprints instead.

## Startup CLI Diagnostics

The native binary supports a read-only startup diagnosis mode:

```bash
c300x-agent-native --config /path/to/config.json --diagnose-startup
```

This command validates and parses the effective config, prints a JSON startup
plan to stdout, and exits without opening API/UI listeners, starting RTSP/media,
or writing files. It is intended for cases where the API is unavailable because
the agent exits during startup.

Fatal startup failures use stable stderr reasons before returning exit code `2`,
for example `config_error`, `api_token_missing`, `api_bind_failed`,
`ui_bind_failed`, `runtime_alloc_failed`, or `video_runtime_start_failed`.

## Endpoint Index

| Method | Path | Auth | Side effects |
| --- | --- | --- | --- |
| `GET` | `/` | setup/noAuth | Serves setup page only while bootstrap is open. |
| `GET` | `/setup` | setup/noAuth | Same as `/`. |
| `GET` | `/api/v1/health` | none | None. |
| `GET` | `/api/v1/capabilities` | API | None. |
| `GET` | `/api/v1/self-test` | API | None. |
| `GET` | `/api/v1/state` | API | None. |
| `GET` | `/api/v1/diagnostics` | API | None. |
| `GET` | `/api/v1/system/metrics` | API | None. |
| `GET` | `/api/v1/device-user` | API | None. |
| `GET` | `/api/v1/display-bridge` | API | None. |
| `POST` | `/api/v1/display-bridge` | API | Updates runtime display bridge callback config. |
| `POST` | `/api/v1/display-bridge/events` | API | Wakes local display listeners for one topic. |
| `GET` | `/api/v1/events/recent` | API | None. |
| `GET` | `/api/v1/events/subscriptions` | API | None. |
| `POST` | `/api/v1/events/subscriptions` | API | Adds or replaces a runtime event subscription. |
| `DELETE` | `/api/v1/events/subscriptions/{id}` | API | Removes a runtime event subscription. |
| `POST` | `/api/v1/stair-light/actions/activate` | API | Sends one OpenWebNet stair-light command. |
| `POST` | `/api/v1/locks/{id}/actions/unlock` | API | Sends one configured lock command. |
| `GET` | `/api/v1/activations` | API | None. |
| `POST` | `/api/v1/activations/{id}/actions/run` | API | Runs one configured activation. |
| `GET` | `/api/v1/smartphone-forwarding` | API | Reads forwarding state. |
| `POST` | `/api/v1/smartphone-forwarding` | API | Changes forwarding mode. |
| `GET` | `/api/v1/ringer` | API | Reads ringer mute and volume state. |
| `POST` | `/api/v1/ringer` | API | Changes ringer mute state or volume. |
| `GET` | `/api/v1/answering-machine` | API | Reads answering-machine state. |
| `POST` | `/api/v1/answering-machine` | API | Changes answering-machine enabled state. |
| `GET` | `/api/v1/answering-machine/messages` | API | Lists video messages. |
| `GET` | `/api/v1/answering-machine/messages/{id}/video` | API | Returns video message media. |
| `POST` | `/api/v1/answering-machine/messages/actions/delete` | API | Deletes selected video messages. |
| `GET` | `/api/v1/memos` | API | Lists text and voice memos. |
| `POST` | `/api/v1/memos/text/actions/create` | API | Creates one text memo. |
| `GET` | `/api/v1/memos/voice/{id}/audio` | API | Returns voice memo audio. |
| `POST` | `/api/v1/memos/actions/delete` | API | Deletes selected memos. |
| `GET` | `/api/v1/video/doorbell` | API | None. |
| `GET` | `/api/v1/video/doorbell/status` | API | None. |
| `POST` | `/api/v1/video/doorbell/audio` | API | Updates runtime-only doorstation downstream audio gain. |
| `POST` | `/api/v1/video/doorbell/actions/activate` | API | Starts or renews on-demand doorbell media. |
| `POST` | `/api/v1/video/doorbell/actions/stop` | API | Stops agent-owned on-demand doorbell media. |
| `GET` | `/api/v1/calls/doorbell` | API | None. |
| `GET` | `/api/v1/calls/doorbell/status` | API | None. |
| `POST` | `/api/v1/calls/doorbell/actions/answer` | API | Answers active ring-call media locally. |
| `POST` | `/api/v1/calls/doorbell/actions/hangup` | API | Hangs up active ring-call media. |
| `POST` | `/api/v1/calls/doorbell/actions/capture` | API | Marks native capture action accepted. |
| `GET` | `/api/v1/calls/home` | API | None. |
| `GET` | `/api/v1/calls/home/status` | API | None. |
| `POST` | `/api/v1/calls/home/actions/start` | API | Starts a local Home Call. |
| `POST` | `/api/v1/calls/home/actions/stop` | API | Stops a local Home Call. |
| `GET` | `/api/v1/maintenance/auth` | maintenance/read | None. |
| `POST` | `/api/v1/maintenance/auth` | maintenance/write or bootstrap | Writes auth/bootstrap config. |
| `GET` | `/api/v1/maintenance/ssh` | maintenance | Reads SSH service state. |
| `POST` | `/api/v1/maintenance/ssh` | maintenance | Starts or stops SSH. |
| `POST` | `/api/v1/maintenance/ssh/actions/start` | maintenance | Starts SSH after confirmation. |
| `POST` | `/api/v1/maintenance/ssh/actions/stop` | maintenance | Stops SSH after confirmation. |
| `POST` | `/api/v1/maintenance/reboot` | maintenance | Schedules reboot after confirmation. |
| `POST` | `/api/v1/maintenance/agent/actions/remove` | maintenance | Schedules agent removal after confirmation. |
| `POST` | `/api/v1/maintenance/agent/actions/restart` | maintenance | Restarts the native agent after confirmation. |
| `GET` | `/api/v1/maintenance/update/status` | maintenance | Reads staged update state. |
| `POST` | `/api/v1/maintenance/update/prepare` | maintenance | Creates staged update directory. |
| `POST` | `/api/v1/maintenance/update/file` | maintenance | Writes one staged update chunk. |
| `POST` | `/api/v1/maintenance/update/apply` | maintenance | Verifies and installs staged update. |
| `POST` | `/api/v1/maintenance/config/actions/normalize` | maintenance | Rewrites config with current schema. |
| `POST` | `/api/v1/maintenance/device-user/actions/ensure-homeassistant` | maintenance | Creates or repairs HA media user/routing. |
| `POST` | `/api/v1/maintenance/device-user/actions/restore-homeassistant-setup` | maintenance | Restores HA media-user setup from backups. |
| `GET` | `/api/v1/maintenance/mqtt` | maintenance | Reads native MQTT bridge state. |
| `POST` | `/api/v1/maintenance/mqtt` | maintenance | Enables/disables native MQTT bridge. |
| `POST` | `/api/v1/maintenance/mqtt/actions/migrate-legacy` | maintenance | Imports legacy MQTT config into native bridge. |
| `GET` | `/api/v1/maintenance/legacy-mqtt` | maintenance | Reads legacy MQTT script state. |
| `POST` | `/api/v1/maintenance/legacy-mqtt` | maintenance | Enables/disables legacy MQTT script. |
| `POST` | `/api/v1/maintenance/gui/actions/reload` | maintenance | Reloads the C300X GUI. |
| `GET` | `/api/v1/maintenance/firewall` | maintenance | Reads IPv4 firewall patch state. |
| `POST` | `/api/v1/maintenance/firewall/actions/apply` | maintenance | Applies IPv4 firewall patch. |
| `POST` | `/api/v1/maintenance/firewall/actions/restore` | maintenance | Restores IPv4 firewall file. |
| `GET` | `/api/v1/maintenance/ipv6-firewall` | maintenance | Reads IPv6 firewall patch state. |
| `POST` | `/api/v1/maintenance/ipv6-firewall/actions/apply` | maintenance | Applies IPv6 firewall patch. |
| `POST` | `/api/v1/maintenance/ipv6-firewall/actions/restore` | maintenance | Restores IPv6 firewall file. |
| `GET` | `/api/v1/maintenance/qml-patch` | maintenance | Reads QML patch state. |
| `POST` | `/api/v1/maintenance/qml-patch/actions/apply-core` | maintenance | Applies core media QML hook. |
| `POST` | `/api/v1/maintenance/qml-patch/actions/restore-core` | maintenance | Restores core media QML hook. |
| `POST` | `/api/v1/maintenance/qml-patch/actions/apply` | maintenance | Applies full display QML patch. |
| `POST` | `/api/v1/maintenance/qml-patch/actions/restore` | maintenance | Restores full display QML patch. |

## Health, Capabilities, State

### `GET /api/v1/health`

Authentication: none.

Side effects: none.

Response:

```json
{"ok": true, "agent": "native-c", "version": "1.7.0"}
```

### `GET /api/v1/capabilities`

Authentication: normal API token.

Side effects: none.

Returns agent metadata, device metadata, and feature flags. Home Assistant uses
this endpoint during setup to decide which entities, repair flows, media paths,
and maintenance controls are supported.

Important top-level fields:

- `api_version`
- `agent.version`
- `agent.implementation`
- `device.id`
- `device.model`
- `device.firmware`
- `capabilities`

### `GET /api/v1/state`

Authentication: normal API token.

Side effects: none.

Returns a cached aggregate state. Older Home Assistant code may use this as a
fallback for smartphone forwarding, ringer, ringer volume, and
answering-machine status when a dedicated endpoint is not available.

### `GET /api/v1/diagnostics`

Authentication: normal API token.

Side effects: none.

Returns runtime diagnostics without secrets. The payload includes non-secret
write counters such as:

- `agent_write_count`
- `last_write_class`
- `last_write_reason`
- `qml_patch_last_action`

Media diagnostic fields describe ownership and bridge state without exposing
tokens, callback URLs, or raw packet data.

### `GET /api/v1/system/metrics`

Authentication: normal API token.

Side effects: none.

Returns low-frequency system metrics. The agent also pushes metrics events when
thresholds or heartbeat intervals are reached, so Home Assistant does not need
periodic polling for normal operation.

## Self-Test

### `GET /api/v1/self-test`

Authentication: normal API token.

Side effects: none. The endpoint must not write files, modify display files or
firewall rules, restart services, start RTSP media, or open talkback RTP.

Contract version: `api_version: "1.1"`.

Response shape:

```json
{
  "api_version": "1.1",
  "agent_version": "1.7.0",
  "firmware_family": "1.7.x",
  "ok": true,
  "checks": {
    "capabilities": {"ok": true, "reason": "ok"},
    "firewall": {"ok": true, "reason": "media_ports_open"},
    "rtsp": {"ok": true, "reason": "rtsp_ready"},
    "talkback_rtp": {"ok": true, "reason": "talkback_rtp_ready"},
    "homeassistant_user": {"ok": true, "reason": "homeassistant_user_ok"},
    "device_routing": {"ok": true, "reason": "device_routing_ok"},
    "startup": {"ok": true, "reason": "startup_link_ok"}
  }
}
```

Each check must include `ok` and `reason`. Additional fields are diagnostic and
must not contain tokens, SIP secrets, webhook URLs, or raw file contents.

Check scope:

- `capabilities`: verifies the running agent can report contract metadata.
- `firewall`: reads configured IPv4/IPv6 firewall scripts and checks for the
  managed media-port blocks. It does not run iptables or ip6tables.
- `rtsp`: reads in-process video bridge state. It does not activate media and
  does not open a client connection.
- `talkback_rtp`: verifies configured talkback RTP infrastructure and firewall
  readiness. It does not send RTP packets.
- `homeassistant_user`: reads Flexisip user and route files and reports whether
  a usable media identity is available.
- `device_routing`: reads local media routing setup and display setup status. It
  does not apply or restore setup changes.
- `startup`: checks whether the agent init script and rc link are present.

## Events API

The agent can push device events to Home Assistant webhooks. Events are runtime
subscriptions and are not a substitute for static config.

### `GET /api/v1/events/recent`

Authentication: normal API token.

Side effects: none.

Returns a bounded list of recent normalized device events.

### `GET /api/v1/events/subscriptions`

Authentication: normal API token.

Side effects: none.

Returns current runtime subscriptions. Token values are not returned; the agent
uses non-secret token fingerprints.

### `POST /api/v1/events/subscriptions`

Authentication: normal API token.

Side effects: adds or replaces a runtime subscription.

Request fields:

```json
{
  "callback_url": "https://ha.example.invalid/api/webhook/...",
  "token": "not-returned-by-status-endpoints",
  "events": ["doorbell", "memos", "system_metrics"]
}
```

Validation:

- `callback_url` is required.
- `events` must contain at least one event.
- Unsupported callback URLs are rejected with `unsupported_callback_url`.

### `DELETE /api/v1/events/subscriptions/{id}`

Authentication: normal API token.

Side effects: removes one runtime subscription.

The subscription id is the opaque id returned by the subscription list/create
response.

## Display Bridge API

The display bridge lets device QML pages call Home Assistant through the local
agent. It is optional and normally loopback-only on the device.

### `GET /api/v1/display-bridge`

Authentication: normal API token.

Side effects: none.

Returns enabled state, callback configured state, shared-secret configured state,
and non-secret fingerprints.

### `POST /api/v1/display-bridge`

Authentication: normal API token.

Side effects: updates in-memory display bridge callback settings.

Request fields:

```json
{
  "enabled": true,
  "webhook_url": "https://ha.example.invalid/api/webhook/...",
  "shared_secret": "not-returned-by-status-endpoints"
}
```

When `enabled=true`, both `webhook_url` and `shared_secret` are required.
Unsupported callback URLs are rejected.

### `POST /api/v1/display-bridge/events`

Authentication: normal API token.

Side effects: wakes local long-poll QML listeners for one topic.

Request fields:

```json
{"topic": "display_bridge.state"}
```

Response status: `202 Accepted` on success.

## Device Actions

### `POST /api/v1/stair-light/actions/activate`

Authentication: normal API token.

Side effects: sends a stair-light OpenWebNet command.

Request fields:

```json
{"address": "10"}
```

### `POST /api/v1/locks/{id}/actions/unlock`

Authentication: normal API token.

Side effects: sends the configured lock command for `{id}`.

`default` is the standard lock id. The path id is percent-decoded and bounded by
`C300X_MAX_LOCK_ID_LEN`.

### `GET /api/v1/activations`

Authentication: normal API token.

Side effects: none.

Returns configured activation items. Activation items use `addressMode:
"manual"` when the configured `address` contains the OpenWebNet `where` value.
`addressMode: "auto"` is reserved for read-only device discovery; auto items
without a discovered address or explicit command are returned as non-executable.

### `POST /api/v1/activations/{id}/actions/run`

Authentication: normal API token.

Side effects: runs one configured activation.

The id is percent-decoded and bounded by `C300X_MAX_ACTIVATION_ID_LEN`.

## Device Feature State

### `GET /api/v1/smartphone-forwarding`

Authentication: normal API token.

Side effects: reads smartphone-forwarding state.

### `POST /api/v1/smartphone-forwarding`

Authentication: normal API token.

Side effects: changes smartphone-forwarding mode.

Request fields:

```json
{"mode": "enabled"}
```

Allowed modes are normalized by Home Assistant before the request.

### `GET /api/v1/ringer`

Authentication: normal API token.

Side effects: reads ringer mute state with `*#8**33##` and ringer volume with
`*#8**41##`.

The response includes `muted` when the mute read can be decoded and `volume`
when the volume read can be decoded. `volume` is the C300X UI ringtone volume
on the `0..10` scale. The firmware treats `0` as muted. OpenWebNet `41` stores
the same UI value in tens, so the agent maps raw code `20` to API/UI volume
`2`, raw code `10` to API/UI volume `1`, and raw code `0` to API/UI volume
`0`.

### `POST /api/v1/ringer`

Authentication: normal API token.

Side effects: changes ringer mute state or ringer volume.

Request fields:

```json
{"muted": true}
```

```json
{"volume": 5}
```

`muted` sends `*#8**#33*0##` or `*#8**#33*1##`. `volume` accepts the C300X UI
range `0..10` and translates it to the OpenWebNet `41` tens code before sending
`*#8**#41*<code>##`. A volume write is only reported as successful after a
fresh `*#8**41##` readback returns the requested value. If the write ACKs but
the readback still reports a different volume, the endpoint returns
`409 Conflict` with `error: "ringer_volume_not_applied"` and the confirmed
readback value.

### `GET /api/v1/answering-machine`

Authentication: normal API token.

Side effects: reads answering-machine state.

### `POST /api/v1/answering-machine`

Authentication: normal API token.

Side effects: changes answering-machine enabled state.

Request fields:

```json
{"enabled": true}
```

## Messages and Memos

### `GET /api/v1/answering-machine/messages`

Authentication: normal API token.

Side effects: none.

Returns local video-message metadata. The endpoint must not return private raw
files unless media is explicitly requested through the media endpoint.

### `GET /api/v1/answering-machine/messages/{id}/video`

Authentication: normal API token.

Side effects: returns the selected video-message media stream.

The id is path-bounded by `C300X_MAX_VOICEMAIL_ID_LEN`.

### `POST /api/v1/answering-machine/messages/actions/delete`

Authentication: normal API token.

Side effects: deletes selected local video messages.

Request fields:

```json
{"ids": ["message-id"]}
```

### `GET /api/v1/memos`

Authentication: normal API token.

Side effects: none.

Returns local text and voice memo metadata.

### `POST /api/v1/memos/text/actions/create`

Authentication: normal API token.

Side effects: creates one local text memo.

Request fields:

```json
{"text": "memo text", "read": false}
```

### `GET /api/v1/memos/voice/{id}/audio`

Authentication: normal API token.

Side effects: returns selected voice memo audio.

The id is percent-decoded and bounded by `C300X_MAX_VOICEMAIL_ID_LEN`.

### `POST /api/v1/memos/actions/delete`

Authentication: normal API token.

Side effects: deletes selected local memos.

Request fields:

```json
{"ids": ["memo-id"]}
```

## Media and Calls

### `GET /api/v1/video/doorbell`

Authentication: normal API token.

Side effects: none.

Alias for current doorbell video status.

### `GET /api/v1/video/doorbell/status`

Authentication: normal API token.

Side effects: none.

Returns doorbell video availability, stream paths, media ownership, and bridge
state. The endpoint must reflect agent/device state, not Home Assistant UI
state. `bridge.doorstation_audio_gain_db` reports the runtime-only downstream
gain that is applied to doorstation audio before RTSP output.

### `POST /api/v1/video/doorbell/audio`

Authentication: normal API token.

Side effects: updates only the native agent's in-memory doorstation downstream
audio gain. It does not write C300X device files or change Home Call audio.

Request fields:

```json
{"doorstation_audio_gain_tenths": 60}
```

Accepted gain range is `-200` to `200` tenths of a dB, in 0.5 dB steps.

### `POST /api/v1/video/doorbell/actions/activate`

Authentication: normal API token.

Side effects: starts or renews agent-owned on-demand doorbell media.

Request fields:

```json
{"audio": true}
```

The endpoint may return `409 Conflict` when another media owner is active.

### `POST /api/v1/video/doorbell/actions/stop`

Authentication: normal API token.

Side effects: stops agent-owned on-demand doorbell media.

### `GET /api/v1/calls/doorbell`

Authentication: normal API token.

Side effects: none.

Alias for doorbell ring-call status.

### `GET /api/v1/calls/doorbell/status`

Authentication: normal API token.

Side effects: none.

Returns active ring-call status, media ownership, and capture readiness.

### `POST /api/v1/calls/doorbell/actions/answer`

Authentication: normal API token.

Side effects: answers the active doorbell ring call locally through the native
media path.

### `POST /api/v1/calls/doorbell/actions/hangup`

Authentication: normal API token.

Side effects: hangs up the active doorbell ring call.

### `POST /api/v1/calls/doorbell/actions/capture`

Authentication: normal API token.

Side effects: records that a native ring-call capture action was accepted. Home
Assistant performs the actual file capture through its configured media path.

### `GET /api/v1/calls/home`

Authentication: normal API token.

Side effects: none.

Alias for Home Call status.

### `GET /api/v1/calls/home/status`

Authentication: normal API token.

Side effects: none.

Returns local Home Call status.

### `POST /api/v1/calls/home/actions/start`

Authentication: normal API token.

Side effects: starts a local Home Call.

Request fields:

```json
{"duration_seconds": 60}
```

`duration_seconds` is optional. If omitted, the agent uses its default call
duration behavior.

### `POST /api/v1/calls/home/actions/stop`

Authentication: normal API token.

Side effects: stops the local Home Call.

## Device User and Routing

### `GET /api/v1/device-user`

Authentication: normal API token.

Side effects: none.

Returns non-sensitive Flexisip device-user and routing status. Important fields:

- `supported`
- `domain_present`
- `homeassistant_user_present`
- `accounts_homeassistant_present`
- `route_int_homeassistant_present`
- `route_ext_homeassistant_present`
- `route_conf_homeassistant_present`
- `route_conf_is_symlink`
- `writable_files_present`
- `media_identity_available`
- `routes_consistent`
- `routing_state`
- `routing_error`

The endpoint must derive the local SIP/domain state from device files. It must
not hardcode device-specific SIP domains or account ids.

### `POST /api/v1/maintenance/device-user/actions/ensure-homeassistant`

Authentication: maintenance.

Side effects: applies media routing setup and creates or repairs the dedicated
Home Assistant media user.

Request fields:

```json
{
  "confirm": "ensure_homeassistant_user",
  "account_label": "Home Assistant"
}
```

`account_label` is optional.

### `POST /api/v1/maintenance/device-user/actions/restore-homeassistant-setup`

Authentication: maintenance.

Side effects: restores the Home Assistant media-user/routing setup from device
backups.

Request fields:

```json
{"confirm": "restore_ha_user_setup"}
```

## Maintenance Auth and Bootstrap Config

### `GET /api/v1/maintenance/auth`

Authentication: maintenance read authorization. During bootstrap this can be
available while noAuth maintenance is open.

Side effects: none.

Returns auth/bootstrap configuration without token values. Important fields:

- `noAuth` / `no_auth`
- `api_token_configured`
- `api_token_fingerprint`
- `maintenance_token_configured`
- `maintenance_token_fingerprint`
- `maintenance_enabled`
- `maintenance_no_auth_allowed`
- feature enabled flags, for example `video_enabled`, `events_enabled`,
  `display_bridge_enabled`, `firewall_enabled`, and `ipv6_firewall_enabled`

### `POST /api/v1/maintenance/auth`

Authentication: maintenance write authorization, or open bootstrap window.

Side effects: writes local agent config.

Common request fields:

```json
{
  "setupComplete": true,
  "noAuth": false,
  "apiToken": "not-returned-by-status-endpoints",
  "maintenanceToken": "not-returned-by-status-endpoints",
  "maintenanceEnabled": true,
  "maintenanceNoAuthAllowed": false,
  "listenHost": "127.0.0.1",
  "apiPort": 8091,
  "uiPort": 8090,
  "allowLan": false,
  "videoEnabled": true,
  "displayBridgeEnabled": true,
  "eventsEnabled": true,
  "memosEnabled": true,
  "videoMessagesEnabled": true,
  "systemMetricsEnabled": true,
  "mdnsEnabled": true,
  "firewallEnabled": true,
  "ipv6FirewallEnabled": true,
  "stairLightDefaultAddress": "10"
}
```

Validation examples:

- `invalid_api_port`
- `invalid_ui_port`
- `invalid_stair_light_address`
- `invalid_activation_address`
- `lan_binding_requires_allow_lan`
- `api_token_required`
- `maintenance_token_required`

## Maintenance Actions

All endpoints in this section require maintenance authorization. Mutating
endpoints require exact confirmation tokens so accidental browser/script calls
do not perform device writes.

### SSH

`GET /api/v1/maintenance/ssh`

Returns SSH service status.

`POST /api/v1/maintenance/ssh`

Starts or stops SSH through a boolean request:

```json
{"enabled": true}
```

`POST /api/v1/maintenance/ssh/actions/start`

```json
{"confirm": "start_ssh"}
```

`POST /api/v1/maintenance/ssh/actions/stop`

```json
{"confirm": "stop_ssh"}
```

### Reboot, Agent, GUI

`POST /api/v1/maintenance/reboot`

```json
{"confirm": "reboot"}
```

Schedules a device reboot.

`POST /api/v1/maintenance/agent/actions/remove`

```json
{"confirm": "remove_agent"}
```

Schedules native-agent removal while keeping the configured safety behavior.

`POST /api/v1/maintenance/agent/actions/restart`

```json
{"confirm": "restart_agent"}
```

Restarts the native agent.

`POST /api/v1/maintenance/gui/actions/reload`

```json
{"confirm": "reload_gui"}
```

Reloads the C300X graphical interface.

### Agent Self-Update

The self-update API stages files first, validates hashes, then applies them.
The agent accepts only known release-bundle paths.

`GET /api/v1/maintenance/update/status`

Reads staged update state.

`POST /api/v1/maintenance/update/prepare`

```json
{
  "bundle_hash": "sha256:...",
  "agent_version": "1.7.0"
}
```

Creates or resets the staging area.

`POST /api/v1/maintenance/update/file`

```json
{
  "path": "device_agent/armhf/c300x-agent-native",
  "sha256": "hex-encoded-file-sha256",
  "mode": "0755",
  "offset": 0,
  "data": "base64-chunk",
  "final": false
}
```

Allowed staged paths:

- `device_agent/armhf/c300x-agent-native`
- `device_agent/scripts/qml_patch.sh`
- `device_agent/scripts/remove_agent.sh`
- `device_agent/scripts/bootstrap_firewall.sh`
- `device_agent/init/c300x-native-agent`
- `device_agent/bundle.json`
- staged QML files and QML JavaScript files copied by the release bundle

`POST /api/v1/maintenance/update/apply`

```json
{
  "bundle_hash": "sha256:...",
  "confirm": "update_agent"
}
```

Validates the staged manifest/hash, installs files, refreshes firewall state
when needed, and returns update status.

### Config Normalize

`POST /api/v1/maintenance/config/actions/normalize`

```json
{"confirm": "normalize_config"}
```

Rewrites the device config with the current schema and normalized values.

### MQTT

`GET /api/v1/maintenance/mqtt`

Reads native MQTT bridge state.

`POST /api/v1/maintenance/mqtt`

```json
{"enabled": true}
```

Enables or disables the native MQTT bridge. Optional config fields accepted by
the endpoint include `host`, `port`, `username`, `password`, `clientId`,
`client_id`, `commandHost`, `command_host`, `commandPort`, `command_port`,
`commandTopic`, `eventTopic`, `jsonEventTopic`, `statusTopic`,
`availabilityTopic`, `keepaliveSeconds`, `keepalive_seconds`,
`reconnectInitialSeconds`, `reconnect_initial_seconds`, `reconnectMaxSeconds`,
and `reconnect_max_seconds`.

The endpoint must not vendor or execute third-party MQTT scripts.

`POST /api/v1/maintenance/mqtt/actions/migrate-legacy`

```json
{"confirm": "migrate_legacy_mqtt"}
```

Imports supported values from the legacy on-device MQTT setup into the native
bridge. It does not copy legacy scripts into this repository.

`GET /api/v1/maintenance/legacy-mqtt`

Reads legacy MQTT script state.

`POST /api/v1/maintenance/legacy-mqtt`

```json
{"enabled": false}
```

Enables or disables the legacy script path on the device.

### Firewall

`GET /api/v1/maintenance/firewall`

Reads the persistent IPv4 firewall patch state.

`POST /api/v1/maintenance/firewall/actions/apply`

```json
{"confirm": "apply_firewall"}
```

`POST /api/v1/maintenance/firewall/actions/restore`

```json
{"confirm": "restore_firewall"}
```

The IPv4 firewall endpoints manage one explicit block in
`/etc/network/if-pre-up.d/iptables`. They do not accept arbitrary iptables rules
or shell commands.

### IPv6 Firewall

`GET /api/v1/maintenance/ipv6-firewall`

Reads the persistent IPv6 firewall patch state.

`POST /api/v1/maintenance/ipv6-firewall/actions/apply`

```json
{"confirm": "apply_ipv6_firewall"}
```

`POST /api/v1/maintenance/ipv6-firewall/actions/restore`

```json
{"confirm": "restore_ipv6_firewall"}
```

The IPv6 firewall block allows `ipv6-icmp` and the configured API TCP port as
destination and source port, using idempotent `ip6tables -C` checks before
inserting rules.

### QML Patch

`GET /api/v1/maintenance/qml-patch`

Reads both optional Display patch state and required core media-hook state.

`POST /api/v1/maintenance/qml-patch/actions/apply-core`

```json
{"confirm": "apply_qml_core_patch"}
```

Applies the minimal EventManager media-close hook required for reliable doorbell
video ownership tracking.

`POST /api/v1/maintenance/qml-patch/actions/restore-core`

```json
{"confirm": "restore_qml_core_patch"}
```

Restores the core media hook.

`POST /api/v1/maintenance/qml-patch/actions/apply`

```json
{
  "confirm": "apply_qml_patch",
  "dynamic_homepage": false
}
```

Applies the core hook plus the optional Display patch: MainApp navigation,
HomePage unread memo/video-message badges, MemoPage external-delete refresh,
Alarmo/Home Assistant pages, and local QML JavaScript bridge.

`POST /api/v1/maintenance/qml-patch/actions/restore`

```json
{"confirm": "restore_qml_patch"}
```

Restores the optional Display patch while keeping the core hook. Full core-hook
restore is reserved for explicit core restore or agent removal.

Patch helpers render the desired tree into a temporary staging directory,
compare target files byte-for-byte, back up original device files under
`/home/bticino/cfg/extra/c300x-device-file-backups/original`, remount the root
filesystem writable only for final copy/write work, then remount read-only.

## Loopback UI API

The UI listener is intended for local QML pages. It rejects non-GET methods and
requires display bridge support where applicable.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | UI listener health. |
| `GET` | `/ui/memos` | Memo metadata for QML pages. |
| `GET` | `/ui/answering-machine/messages` | Video-message metadata for QML pages. |
| `GET` | `/ui/events/status` | Long-poll state for QML event bridge. |
| `GET` | `/ui/events/next` | Long-poll next QML event. |
| `GET` | `/ui/media-closed` | Reports device media-close event. |
| `GET` | `/ui/state` | Display bridge state. |
| `GET` | `/ui/alarm/status` | Alarm status alias. |
| `GET` | `/homeassistant` | Render Home Assistant dashboard payload for QML. |
| `GET` | `/ui/action` | Execute configured display action. |
| `GET` | `/ui/alarm/command` | Execute configured alarm command. |

UI endpoints use the local display bridge and shared secret configured through
the API listener. They must not expose configured token values.

## Compatibility Matrix

| Agent version | Self-test API | Firmware family | Notes |
| --- | --- | --- | --- |
| 1.7.0 | 1.1 | 1.7.x | Adds configurable live doorstation audio gain for on-demand video and Ring Call audio. |
| 1.6.1 | 1.1 | 1.7.x | Fixes RTSP backchannel negotiation for provider-based browser talkback. |
| 1.6.0 | 1.1 | 1.7.x | Adds RTSP backchannel support for provider-based browser talkback. |
| 1.5.3 | 1.1 | 1.7.x | Adds multi-client doorbell viewing and confirmed C300X UI-scale ringer volume support. |
| 1.5.0 | 1.1 | 1.7.x | Adds initial ringer volume read/write support. |
| 1.4.1 | 1.1 | 1.7.x | Adds consolidated doorstation card and Ring Call support. |
| 1.3.0 | 1.1 | 1.7.x | Adds display watchdog recovery and bundled mobile Ring Call workflow support. |
| 1.2.3 | 1.1 | 1.7.x | Consolidates display UI actions and dashboard traffic handling. |
| 1.2.2 | 1.1 | 1.7.x | Bootstraps and requires the dedicated Home Assistant media user for local media identity. |
| 1.2.1 | 1.1 | 1.7.x | Keeps the Home Assistant media user on the internal route only. |
| 1.2.0 | 1.1 | 1.7.x | Adds read-only architecture self-test. |

Older agents do not expose `/api/v1/self-test`. Home Assistant must treat that
as unsupported rather than attempting automatic repair.
