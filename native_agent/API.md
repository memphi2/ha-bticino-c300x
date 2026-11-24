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
- Current agent version: `2.10.0b1`
- Self-test contract version: `api_version: "1.1"`
- Normal payloads are JSON unless an endpoint explicitly returns binary media.

`agent.self_update_file_set_version` advertises the updater's supported payload
file set (`1` when the field is missing). A bundle's `update_file_set_version`
declares the minimum required set. Set `2` includes `C300XRingerControl.qml`,
set `3` adds `C300XEnergy.qml`, and set `4` is the retired 2.4.1 energy-view set.
Set `5` adds the 2.5 display navigation, optional-page, Consumers and alert
components. Set `6` adds the shared checks/optional-page views and Situations.
The matching native agent and complete display bundle are required;
updating the HA integration alone does not install these GUI components.
When the installed self-updater cannot install the target file set, Home
Assistant first installs and verifies the new executable, then completes the
payload once through that updater using the same maintenance token. A matching
manifest hash alone does not make an updater with a lower file set capable of
installing new files.

Unknown `/api/v1` paths respond with `501 Not Implemented` and
`{"ok": false, "error": "not_implemented"}`. Home Assistant treats that as an
unsupported capability, not as a repair signal.

## Listeners

The agent has two HTTP listeners:

- API listener: configured by `listen.host`, `listen.apiPort`, and
  `listen.allowLan`.
- UI listener: loopback display bridge listener on `127.0.0.1`, port
  `listen.uiPort` (reported as `ui_listen_host`/`ui_port`). It is intended for
  QML pages running on the device. Every display call follows `listen.uiPort`:
  the Display patch writes the port into the patched `MainApp.qml` and
  `EventManager.qml`, and all other pages take it from there. After a port
  change, restart the agent and reapply the Display patch; until then the patch
  is reported as partially patched.

Public UI listener endpoints are documented separately under
[Loopback UI API](#loopback-ui-api).

## Authentication

There are two independent authorization layers.

### API Token

Normal `/api/v1` endpoints require the configured device-agent API token unless
`api.noAuth=true`.

Clients send the token in the HTTP `Authorization` header using the bearer
scheme. Do not log or expose the header value.

`GET /api/v1/health` and `POST /api/v1/identity/proof` are always
unauthenticated; the proof route never returns the token. `GET /` and
`GET /setup` are served only while `api.noAuth=true`.

Every API listener route except `GET /` and `GET /setup` refuses, with 403
`cross_site_request`, a request whose `Origin` header is not this host, and a
non-GET request whose `Content-Type` is `text/plain`,
`application/x-www-form-urlencoded` or `multipart/form-data`: what a web page
of another site can send without a CORS preflight. Clients send JSON and no
`Origin`, as Home Assistant does.

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
| `201 Created` | Runtime subscription or text memo was created. |
| `202 Accepted` | Display wake-up accepted, or reboot, agent removal or restart scheduled. |
| `400 Bad Request` | Invalid body, missing field, invalid id, or missing confirmation token. |
| `401 Unauthorized` | Normal API token is missing or invalid. |
| `403 Forbidden` | Maintenance token is missing/invalid or maintenance is disabled, the endpoint requires loopback, or a required UI header is missing. |
| `404 Not Found` | Setup disabled, media item missing, feature disabled, or maintenance module disabled (`maintenance_disabled`). |
| `405 Method Not Allowed` | Wrong method on a loopback UI route. |
| `409 Conflict` | The request conflicts with the current device, media or agent state, for example an agent update while `/` is already writable. |
| `413 Payload Too Large` | HTTP body exceeded the static parser buffer. |
| `429 Too Many Requests` | Snapshot requested less than two seconds after the previous one. |
| `500 Internal Server Error` | Agent-side operation failed. |
| `501 Not Implemented` | Unknown endpoint. |
| `502 Bad Gateway` | Home Assistant callback/display bridge is unavailable, or an OpenWebNet command failed or was not sent (`openwebnet_busy`, `client_gone`). |
| `503 Service Unavailable` | Resource busy or inactive (transfer slots, system metrics, snapshot source, ringer GUI, display command), or a media action was not run (`media_busy`, `client_gone`). |
| `504 Gateway Timeout` | The GUI did not acknowledge a ringer command within five seconds, or a QML write passed its deadline (`qml_patch_timeout`). |

Requests that send OpenWebNet commands and the media actions (activate, stop,
answer, hangup, home call start and stop) run one at a time each, in the order
they arrived; the others wait for their turn with the connection open. Three
requests may wait in all. One more is answered `openwebnet_busy` (502) or
`media_busy` (503): nothing was sent or changed, and the request can be
repeated. A request that had to wait and whose caller has closed the
connection meanwhile, also only its sending side, is not run and answered
`client_gone`; of the media actions this applies to the three that start
something, a stop still runs unless a new request needed its place. A
maintenance POST that replaces the agent configuration (auth, MQTT, legacy
MQTT, MQTT migration) is no such waiting request and takes none of the three
places. Once it is admitted it is held while a bus command or a media
operation of another request is running or not yet answered, which can be
several in a row, and is applied afterwards. A write whose caller has closed
the connection, also only its sending side, is never applied and answered
502 `client_gone`, held or not. A request that waited for a worker while
such a write changed the API token is answered 401 without having run.

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
| `POST` | `/api/v1/identity/proof` | none | None. |
| `GET` | `/api/v1/capabilities` | API | None. |
| `GET` | `/api/v1/self-test` | API | None. |
| `GET` | `/api/v1/state` | API | None. |
| `GET` | `/api/v1/diagnostics` | API | None. |
| `GET` | `/api/v1/system/metrics` | API | None. |
| `GET` | `/api/v1/device-user` | API | None. |
| `GET` | `/api/v1/display-bridge` | API | None. |
| `POST` | `/api/v1/display-bridge` | API | Updates runtime display bridge callback config. |
| `POST` | `/api/v1/display-bridge/events` | API | Wakes local display listeners for one topic. |
| `POST` | `/api/v1/display/alert` | API | One immediate delivery to a waiting GUI alert connection; no deferred queue. |
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
| `GET` | `/api/v1/announcements` | API | Reads whether a sound is playing and how the last one ended. |
| `POST` | `/api/v1/announcements/audio` | API | Writes one piece of the sound file to play. |
| `POST` | `/api/v1/announcements/actions/play` | API | Plays the sound file over the device speaker. |
| `POST` | `/api/v1/announcements/actions/stop` | API | Ends the sound that is playing. |
| `GET`, `POST` | `/api/v1/display/touch-tone` | API | Reads GUI-confirmed touch tone; POST `{"enabled":true}` waits up to five seconds for GUI acknowledgement. Requires the Display patch. |
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
| `GET` | `/api/v1/video/doorbell/snapshot` | API | Reads the active video framebuffer into bounded RAM and returns BMP data for HA-side conversion. Optional `width` (64-800) and `height` (64-480), both or neither, give the image size; without them it is the display size scaled to fit 800x480. Any other value answers `400 invalid_snapshot_size`; a request within two seconds of the previous one answers `429 snapshot_throttled`, and no readable video frame answers `503 snapshot_unavailable`. No file writes, video activation or call answer. |
| `POST` | `/api/v1/video/doorbell/audio` | API | Updates runtime-only doorstation downstream audio gain. |
| `POST` | `/api/v1/video/doorbell/actions/activate` | API | Starts or renews on-demand doorbell media. |
| `POST` | `/api/v1/video/doorbell/actions/stop` | API | Stops agent-owned on-demand doorbell media. |
| `GET`, `POST` | `/api/v1/video/picture` | API | GET reads brightness, contrast and saturation; POST changes one of them on the active video source. |
| `GET` | `/api/v1/calls/doorbell` | API | None. |
| `GET` | `/api/v1/calls/doorbell/status` | API | None. |
| `POST` | `/api/v1/calls/doorbell/actions/answer` | API | Answers active ring-call media locally. |
| `POST` | `/api/v1/calls/doorbell/actions/hangup` | API | Hangs up active ring-call media. |
| `POST` | `/api/v1/calls/doorbell/actions/capture` | API | Marks native capture action accepted. |
| `GET` | `/api/v1/calls/home` | API | None. |
| `GET` | `/api/v1/calls/home/status` | API | None. |
| `POST` | `/api/v1/calls/home/actions/start` | API | Starts a local Home Call. |
| `POST` | `/api/v1/calls/home/actions/stop` | API | Stops a local Home Call. |
| `GET` | `/api/v1/maintenance/auth` | API/maintenance/read or API noAuth | None. |
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
| `GET` | `/api/v1/maintenance/camera-resolution` | maintenance | Reads the camera resolution. |
| `POST` | `/api/v1/maintenance/camera-resolution` | maintenance | Saves the camera resolution for the next stream. |
| `GET` | `/api/v1/maintenance/camera-quality` | maintenance | Reads size, bit rate and frame rate of the camera stream Home Assistant receives (the low one on firmware 3.0.x). |
| `POST` | `/api/v1/maintenance/camera-quality` | maintenance | Saves them and restarts the device after confirmation. |
| `GET` | `/api/v1/maintenance/audio-codec` | maintenance | Reads the device audio codec (speex/PCMU) state. |
| `POST` | `/api/v1/maintenance/audio-codec/actions/apply` | maintenance | Switches the device to PCMU and reboots after confirmation. |
| `POST` | `/api/v1/maintenance/audio-codec/actions/restore` | maintenance | Switches the device to speex and reboots after confirmation. |

## Health, Capabilities, State

### `GET /api/v1/health`

Authentication: none.

Side effects: none.

Response:

```json
{"ok": true, "agent": "native-c", "version": "2.4.0"}
```

### `POST /api/v1/identity/proof`

Authentication: none. Side effects: none.

Home Assistant uses this before it follows the station to a new address. The
station proves that it holds the API token without sending it:

```json
{"nonce": "<64 lowercase hex characters>"}
```

```json
{"ok": true, "id": "c300x-...", "proof": "<64 lowercase hex characters>"}
```

`proof` is HMAC-SHA256 with the API token as key over
`c300x-identity-v1\n<id>\n<local IPv4>:<local port>\n<nonce>`, where the
address and port are the ones this connection arrived on. A relay that forwards
the nonce to the real station therefore gets a proof for the station's address,
not its own. Errors: `400 invalid_nonce`; `404 identity_proof_unavailable`
when `api.noAuth=true`, the token is shorter than 32 characters, or the
connection is not IPv4.

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

Returns a cached aggregate state. Home Assistant falls back to it for
smartphone forwarding when that endpoint is unsupported, and for ringer and
answering-machine status when the dedicated read fails (for example
`409 ringer_gui_busy`).

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

Returns the latest completed system-metrics snapshot, also used by
`system.metrics_changed` events. Reading this endpoint never takes a new CPU
sample or changes the sampling schedule. CPU usage is `null` until two counter
readings are available. If monitoring is disabled, the endpoint returns HTTP 503
with `error: "system_metrics_inactive"`.

HTTP and event payloads carry snapshot metadata:

- `instance_id`: random 32-character hexadecimal identifier for this agent run.
- `sample_sequence`: increasing integer, starting at 1 within each instance.
- `sample_age_ms`: monotonic age of the sample when the payload is serialized.
- `sample_interval_ms`: actual interval between counter readings; 0 initially.
- `sample_interval_seconds`: configured sampling cadence, normally 30 seconds.
- `heartbeat_seconds`: configured maximum interval between successful pushes
  when values are unchanged, normally 600 seconds.

CPU changes at the displayed precision (one decimal place) trigger a push at the
next regular sample. Other metrics retain their configured thresholds. Failed
deliveries remain pending until a subsequent regular sample is acknowledged;
only the newest snapshot is sent. Home Assistant rejects out-of-order snapshots
and expires the cache after the heartbeat plus two sample intervals. No periodic
Home Assistant polling is required.

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
  "agent_version": "2.4.0",
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
- `events` must contain at least one event and at most 32; more are refused
  with `too_many_events`, never cut.
- Unsupported callback URLs are rejected with `unsupported_callback_url`.
- HTTP and HTTPS are accepted. HTTPS requires `capabilities.https_callbacks`;
  otherwise registration returns `https_unavailable`. TLS verifies the server's
  certificate chain and hostname with the device CA bundle. Redirects are not
  followed, proxies from the environment are ignored, and no HTTP fallback occurs.
- Subscription `last_delivery` includes `http_status` (0 if unavailable) and
  `error` (empty on success). HTTPS failures use fixed identifiers such as
  `https_certificate_invalid`, `https_timeout` or `https_http_status`; they never
  include the callback URL or token. These added fields describe HTTPS delivery;
  HTTP keeps the existing `ok` result.

HTTPS is disabled by default. `https_callbacks_configurable` advertises support
for the opt-in setting without loading libcurl. `https_callbacks_configured`
reports the persisted desired mode; `https_callbacks_enabled` reports the mode at
process startup, and `https_callbacks` reports initialized transport availability.
These capability reads never initialize TLS.

An authenticated `POST /api/v1/maintenance/auth` with
`{"httpsCallbacksEnabled": true}` persists `callbacks.httpsEnabled` only when
changed. TLS initialization occurs before workers start, so a mode change needs
an agent restart. HA derives this setting exclusively from an explicit HTTPS
callback base URL override. To defer a restart during active media, send
`{"confirm":"restart_agent","only_if_idle":true}` to the existing agent restart
endpoint. It returns `409 media_session_active` instead of stopping the session.
Switching back to HTTP requires the same restart to release the TLS library state.

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
Unsupported callback URLs are rejected. HTTPS uses the same transport and
certificate checks as event subscriptions and requires `https_callbacks`.

### `POST /api/v1/display-bridge/events`

Authentication: normal API token.

Side effects: wakes local long-poll QML listeners for one topic.

Request fields:

```json
{"topic": "display_bridge.state"}
```

For `display_bridge.state` and `notifications`, an optional boolean `unread`
also synchronizes HA's memo LED claim, even without a display listener. The
agent advertises `memo_led` only when it finds the LED and a usable, trusted
volatile claim store at startup. An empty private directory on tmpfs records
ownership across agent crashes, not device reboots. Releasing the claim
respects the firmware LED trigger and any unread native memos. An accepted
event is not a hardware delivery receipt.

Response status: `202 Accepted` on success. `400 invalid_unread` when the body
carries `unread` and the topic is another one, the value is not a boolean, or
the body is not a valid JSON object; nothing is woken then. A body without
`unread` is not checked for it.

### `POST /api/v1/display/alert`

Authentication: normal API token. Requires capability `display_alerts` and the
matching Display patch. The HA standard Notify service prepares this payload;
it is not an arbitrary command or media endpoint.

Only these fields are accepted, all required:

| Field | Constraint |
| --- | --- |
| `id`, `revision` | 32 lowercase hexadecimal characters each; delivery ID and HA notice revision. |
| `notification_id` | 1 to 64 lowercase letters, digits, `_` or `-`. |
| `severity` | `info`, `warning` or `error`. |
| `title`, `message` | Text, at most 80 and 500 Unicode characters respectively; the HA service rejects empty text. |
| `wake_duration`, `sound_duration` | Integer seconds from 0 to 300; 0 disables that effect. |
| `expires_in` | Integer seconds from 1 to 604800 for the notice lifetime. |

The body is limited to 7680 bytes. Query parameters, extra fields, arbitrary
URLs, audio files and commands are rejected. HA supplies defaults: severity
`info`, wake 30 seconds, sound 30 seconds for every severity, expiry
3600 seconds. These defaults belong to the HA service, not the native schema.

Success is `200 {"ok":true,"accepted":true}` after writing to the already
waiting GUI connection. This is **transport acceptance only**, not a GUI
acknowledgement or proof of rendering, physical wake or audible output. The
GUI can discard blocked, stale or lower-priority alerts. HA performs one POST
without automatic retries; a lost response does not establish non-delivery.

A live GUI listener that reports a protected context instead returns
`200 {"ok":true,"accepted":false,"suppressed":true,"reason":"display_protected"}`.
No command is delivered and the sleeping listener stays connected. HA keeps
the notice without raising an action error. This outcome is also retained in
the receipt table, so repeating it after leaving the protected screen cannot
replay the effects.

No waiting GUI returns `503 display_alerts_gui_unavailable`; nothing is queued
for a later connection or wake. A failed delivery returns
`503 display_alerts_delivery_failed`. The in-memory deduplication table retains
64 delivery receipts for five minutes. Repeating the same ID and normalized
payload returns the recorded result without replay; a different payload with
that ID returns `409 display_alert_id_conflict`. A full receipt table returns
`503 display_alerts_dedup_full`. Other errors include
`400 invalid_display_alert`, `413 display_alert_too_large` and
`503 display_alerts_unavailable`. There are no runtime notification-file writes
or idle expiry timers.

Wake and bounded stock short-beep effects are restricted to ready, safe Home/HA
screens. Calls, ringing, Alarmo and other protected pages block them. User
interaction or a protected context stops effects, with no deferred replay.
These alerts are supplementary information, not fire-alarm or life-safety
functionality. Local strict simulations do not establish physical behavior on
every device or firmware version.

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

Side effects: reads smartphone-forwarding state and switches the agent's Ring
Call receiver on for `homeassistant`, off otherwise.

Response: `{"ok": true, "mode": "enabled" | "homeassistant" | "blocked" |
"unprovisioned", "raw": "<device reply>"}`. When the device's reply names no
mode: `{"ok": true, "mode": null, "status": "unknown", "raw": "..."}`.

### `POST /api/v1/smartphone-forwarding`

Authentication: normal API token.

Side effects: changes smartphone-forwarding mode.

Request fields:

```json
{"mode": "enabled"}
```

Accepted modes are `enabled`, `homeassistant` and `blocked`;
`{"enabled": true|false}` maps to `enabled`/`blocked`. Any other value,
including `unprovisioned`, returns `400 invalid_smartphone_forwarding_mode`.

The agent writes the requested mode and performs a fresh `*#8**37##` readback.
Only a valid write response (ACK or forwarding status) followed by the requested
readback mode returns success. `raw` contains the write response; `mode_raw`
contains the readback. The confirmed mode updates the agent's cached forwarding
state and Ring Call receiver eligibility, including when it differs from the
request.

If the readback differs, the endpoint returns `409 Conflict` with
`error: "smartphone_forwarding_not_applied"`, `requested_mode`, and the actual
`mode`. A rejected or invalid write response, an invalid readback, or a transport
failure returns `502 Bad Gateway`. An ACK alone never confirms a mode change.

### `GET /api/v1/ringer`

Authentication: normal API token.

Side effects: reads ringer mute state with `*#8**33##` and ringer volume with
`*#8**41##`.

While a GUI mute/unmute command is pending, returns `409 ringer_gui_busy`
without querying the hardware. Home Assistant uses the cached `/api/v1/state`
response during this transition. This prevents an old readback from restoring
the GUI's previous mute setting.

The response includes `muted` when the mute read can be decoded and `volume`
when the volume read can be decoded. `volume` is the C300X UI ringtone volume
on the `0..10` scale. The firmware treats `0` as muted. OpenWebNet `41` stores
the same UI value in tens, so the agent maps raw code `20` to API/UI volume
`2`, raw code `10` to API/UI volume `1`, and raw code `0` to API/UI volume
`0`.

### Announcements

The agent plays a sound file over the device speaker, for example speech that
Home Assistant made. Capability `announcements.supported` is true where the
device has the sound tools this needs (`aplay`, `amixer`, the audio chip tool
and its configuration for playing) and the agent has joined the multicast
group of the door entry events, without which a sound could not give way to a
door call.

`GET /api/v1/announcements` returns

```json
{"ok": true, "supported": true, "playing": false, "started": false,
 "busy": false, "result": "played", "duration_ms": 0, "max_bytes": 2097152}
```

`result` tells how the last sound ended: `played`, `stopped`, `preempted` (a
door call took the speaker), `device_busy` (the device was using its speaker;
nothing was switched), `sound_path_failed`, `play_failed` or `failed`. It is
empty before the first sound and while one plays, and set as soon as the
sound has ended. `started` turns true while a sound plays once the device let
the agent have its speaker and the speaker is switched on; a device that uses
it ends the sound as `device_busy` before that. `busy` stays true after the sound until the speaker is
switched off again; no new piece or sound is taken while it is true.

`POST /api/v1/announcements/audio` with `{"offset": 0, "data": "base64"}`
writes one piece of the file. Pieces come in order; offset 0 starts a new
file. The file is a WAV with 8000 Hz, 16 bit PCM, one or two channels, the
only format the device's sound card takes, and at most `max_bytes` long
(about two minutes). It lives in `/tmp`, must be a file of the agent with a
single name, and is removed when the sound ends and when the agent starts or
ends. A play that is refused keeps it.

`POST /api/v1/announcements/actions/play` with `{"volume": 1..100}` checks the
file and starts playing; the reply carries `duration_ms`. The volume follows
the device's own table for playing and ringing. The agent switches the device
to its state for local playing, loads the audio chip's configuration for it
(to RAM only), unmutes the speaker and plays. Afterwards it mutes the speaker,
switches the amplifier off and sets the gain back. While the device's software
has set a state of its own or plays itself, the speaker is its: switching off
waits until the device is idle again, at most ten minutes.

`POST /api/v1/announcements/actions/stop` ends the sound at once.

A door call has priority: a call being set up or answered (`*8*1#…`,
`*8*2#…`) ends the sound at once and frees the sound device. Locks, lights,
video commands and the end of a call do not. The speaker is then left to the
device for three seconds before it is switched off as above. A ring
(`*8*1#1#…`) leaves the speaker to the device for a minute, also in the pauses
in which the device is idle; every further frame of its call (`*8*…` other
than locks and lights, for example the answering machine, answering and the
end) starts the minute again, also for a switching off that already waits. No
frame ends it early, and an agent that is restarted within it keeps it. During it, and while the switching off
after a door frame waits, no new piece or sound is taken: the answer is
`409 announcement_device_busy`. After a stop the speaker is switched off one
second later. A switching off still due when the agent ends runs on after it.
An agent that starts and has the API port ends the player or switching off of
one that was killed or restarted (or finds its sound file left without a
player), takes over the gain to set back, and then acts as after a door
frame: a minute without new sounds, then switching off. A touch tone or
another sound of the device during an announcement can cut it short.

Errors: `409 announcement_busy` while `busy` is true, `409
announcement_device_busy` after a door frame as above, `409
announcement_unsupported`, `400 announcement_invalid_audio`, `400
announcement_invalid_volume`, `500 announcement_write_failed`, `500
announcement_start_failed`.

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

`muted` first asks the core QML hook to enable/disable `AudioState.RingtoneMute`,
just like the device button. The API response waits for the matching GUI
acknowledgment and device readback. Only the GUI sends the mute/unmute device
command; the agent never overrides its audio-state priorities with a raw write.
The GUI acknowledgment alone does not trigger a readback: the stock GUI queues
its hardware write, and an early read can feed the old mute state back into it.
A matching device status event triggers verification; multicast write-command
echoes do not. Matching status received before the GUI acknowledgment is retained
unless superseded by an opposite status. There is at most one event-triggered
readback and one final verification at the existing five-second deadline.
The final verification also handles missing events and already-applied commands.
If the value still differs, the endpoint returns `409 ringer_not_applied`;
an undecodable readback returns `502 ringer_readback_failed`. A GUI acknowledgment
or event alone is not a confirmed device value. There are no retry writes,
periodic reads or extra idle wakeups. Clients must allow enough HTTP time for
the command deadline, device readback and response delivery.
The core QML hook must be updated and loaded; the optional display bridge
pages are not required. A missing GUI returns `503 ringer_gui_unavailable`,
a concurrent command `409 ringer_gui_busy`, and a missing acknowledgment
`504 ringer_gui_timeout` after five seconds. Failed/mismatching GUI
acknowledgments never fall back to an unsynchronized device write.

`volume` accepts the C300X UI
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

Video-message and voice-memo downloads share four bounded transfer slots. The
agent streams each file through its event loop without waiting on a slow reader,
so call events and API controls remain responsive. A fifth concurrent download
returns `503` with `media_transfers_busy`. A transfer with no socket-write
progress for two seconds is closed; disconnected clients and agent shutdown also
release the socket and file.

### `POST /api/v1/answering-machine/messages/actions/delete`

Authentication: normal API token.

Side effects: deletes one local video message.

Request fields:

```json
{"id": "message_1"}
```

### `GET /api/v1/memos`

Authentication: normal API token.

Side effects: none.

Returns local text and voice memo metadata. `deleted` lists the ids (same
format as `memos[].id`) of the last 32 memos deleted through the agent, oldest
first, until a memo with that id exists again; the display drops a memo it
still shows only once its id is listed there. `/ui/memos` returns the same.

### `POST /api/v1/memos/text/actions/create`

Authentication: normal API token.

Side effects: has the station save one local text memo, the way its own
display does: the agent writes `message.txt` into `memos.recordsDir`, sends
`*8*87#4*##`, and `bt_answering_machine` numbers the memo, writes its
`msg_info.ini` and moves the file in. The agent then sends the display's list
request `*#8**100#3##`, whose answer the station also sends to the display,
and for `read: true` marks the memo read with `*#8**#101#3#<n>*1##`.
A save the station refuses (it is recording, for example) answers
`502 memo_create_refused`. Further `502` errors of this route:

| `error` | Meaning |
| --- | --- |
| `memo_records_dir_missing` | The records directory is missing and could not be created or opened to the station. Nothing was sent. |
| `memo_create_failed` | `message.txt` could not be written. Nothing was sent. |
| `memo_list_unreadable` | The station answered the list request with something the agent cannot read. |
| `memo_create_unconfirmed` | The station acknowledged the save, but its list names no new memo. |

Request fields:

```json
{"text_b64": "bWVtbyB0ZXh0", "read": false}
```

### `GET /api/v1/memos/voice/{id}/audio`

Authentication: normal API token.

Side effects: returns selected voice memo audio.

The id is percent-decoded and bounded by `C300X_MAX_VOICEMAIL_ID_LEN`.

### `POST /api/v1/memos/actions/delete`

Authentication: normal API token.

Side effects: deletes one local memo.

The station deletes only memos it has listed since it started; it refuses
any other one, which answers `502 memo_delete_refused` at once. The video
message delete answers `502 video_message_delete_refused` the same way.

Request fields:

```json
{"id": "text/memo_1"}
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
`bridge.ring_hangup_requested` is true while the native ring-call hangup path is
being driven.

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

The endpoint may return `409 Conflict` with `external_session_active` when
another media owner is active, for example a call answered on the station's
display; that guard lasts for the whole display call (at least 65 s, renewed by
each view frame) unless the call's end frame clears it earlier.

While the station is busy it answers `503` with `error`
`video_activate_failed` and `last_error` `station_busy`, and does not call
the station; an RTSP `PLAY` that would start on-demand media
gets `503` (reason `ondemand_start_refused`). The guard is set when the
station answers the on-demand call with `486 Busy`, lasts up to 65 s and is
freed at once by the next call-end bus frame.

### `POST /api/v1/video/doorbell/actions/stop`

Authentication: normal API token.

Side effects: stops agent-owned on-demand doorbell media.

### `GET`, `POST /api/v1/video/picture`

Authentication: normal API token.

Side effects: POST changes one picture control of the active video source.

A connected GUI advertising `picture=1` provides the legacy ring-only path.
An eligible C300X (firmware 1.7.19; 2.0.2 with a bound ADV7180 video decoder,
HW rev 2/3, or TVP5150, HW rev 1/4; 3.0.6 with its bound TVP5150, as the 3.0.6
package requires HW rev 4) can also report
`bridge.picture_controls_scope: "ring_and_on_demand"` with
`bridge.picture_controls_supported: true`. Model and firmware alone do not
enable it: an authenticated status or capability request during owned media
checks the capture source on the bounded media worker. The read result is
cached for that media session; no source is opened while idle.
`camera_picture.supported` reports whether either path is available.
Missing or unknown scope does not extend GUI support beyond ring calls.

`GET` returns brightness, contrast and saturation; POST accepts one `control`
with a percentage `value` (0 through 100 in steps of 10). Direct success returns
source readback; legacy success returns the GUI object's values. Neither
measures the rendered picture.
The source must be character device 81:0 bound to `mxc_v4l2_capture` with
`VIDIOC_QUERYCAP` driver `mxc_v4l2` and video capture; any other device or
driver is refused. The stock capture driver has no V4L2 control descriptors
(`VIDIOC_QUERYCTRL` fails with `EINVAL`). The agent accepts that only by its
exact signature (version `0x10b`, capabilities `0x05000005`, `device_caps` 0,
empty card and bus) and uses the stock firmware's fixed raw ranges
(brightness 30-180, contrast 59-209, saturation 64-244, eleven steps). Any
other `mxc_v4l2` device must expose integer descriptors that cover these
ranges; raw control reads alone do not make it supported.
The decoder is told by its bound I2C driver
(`/sys/bus/i2c/drivers/adv7180/<bus>-<address>` or `.../tvp5150/...`). The
stock ADV7180 driver writes brightness XOR `0x80` but reads the register back
raw, so the agent undoes that XOR on read. The TVP5150 reads back plain; its
contrast is a driver cache that stays 0 until the first write after boot.
Such a 0, like any read off the eleven steps, fails the whole read: all three
controls are unavailable, and the agent refuses direct control for the rest
of that media session (a Ring Call falls back to the GUI path). Once a
TVP5150 contrast write ioctl succeeds, its read-back always matches, because
it comes from that cache and the driver ignores I2C write errors; a failed
I2C contrast write cannot be detected. Only brightness and saturation have a
genuine read-back there. A contrast write is still answered as not applied
and rolled back when the write ioctl fails, when a re-read (in practice of
brightness or saturation) fails, or when the 750 ms deadline passes during
verification.
The TVP5150 driver queues its I2C write and returns at once, so when the
read-back differs the agent reads again up to five times, 10 ms apart,
before it reports the setting as not applied.
Changes last for the current media session; the station applies its own
values again when the next session starts. 3.0.6 and the 2.0.2 path are
checked offline only; 1.7.19 is tested on a device.
Direct operations check media ownership and session identity during execution.
A failed direct write returns an error; it is not retried through the GUI.
When the write or its read-back fails, the agent writes the previous value
back while the media session is still its own.
No extra idle poll, recording, configuration write or media restart is needed.

Errors:

| Status | `error` | Meaning |
| --- | --- | --- |
| `400` | `invalid_picture_control` | A POST without a body, or a JSON object whose `control` is not `brightness`, `contrast` or `saturation`, or whose `value` is not an integer 0 through 100 in steps of 10. |
| `400` | `invalid_json` | The body is not a JSON object. The agent's request parser answers this for every route before the route runs. |
| `405` | `method_not_allowed` | The method is neither `GET` nor `POST`. |
| `409` | `media_busy` | The media worker is busy with another job; nothing was changed. Unlike the media actions, this route answers `409`. |
| `409` | `picture_controls_unavailable` | Neither the direct nor the GUI path is available for the current media, or the GUI answered with missing or out-of-range values. |
| `409` | `picture_not_applied` | Direct path: the write failed, a re-read failed, the value read back differs, or the 750 ms verification deadline passed; the previous value is written back while the agent still owns the media. Legacy path: the GUI read back a different value than the one sent. |
| `409` | `picture_gui_busy` | The GUI is still handling an earlier ringer or picture command. |
| `500` | `ringer_gui_id_failed` | The agent could not create a command id for the GUI (reading `/dev/urandom` failed). |
| `503` | `picture_gui_unavailable` | No GUI listener for the legacy path. |
| `503` | `ringer_gui_unavailable` | The command could not be handed to the GUI listener, or the agent shut down before the GUI answered. |
| `504` | `picture_gui_timeout` | The GUI did not acknowledge within five seconds. |

### `GET /api/v1/calls/doorbell`

Authentication: normal API token.

Side effects: none.

Alias for doorbell ring-call status.

### `GET /api/v1/calls/doorbell/status`

Authentication: normal API token.

Side effects: none.

Returns active ring-call status, media ownership, capture readiness, and
`hangup_requested` while the native ring-call hangup path is being driven.
`talkback_ready` is true only while the answered ring-call audio and UDP listener
are active and the HTTP caller's peer has a live, unparked RTSP connection after
PLAY. HA waits for this before sending an announcement. This field uses the same
peer-admission check as UDP media; it does not reserve a connection or replace
per-packet checks. Older agents omit it and retain their legacy readiness behavior.

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

An active route must use the recognized internal or external route symlink.
An unrecognized link or regular active-route file reports `supported: false`,
`routes_consistent: false` and `unsupported_active_route`. Internal readiness
requires the HA destination in the active route; external forwarding deliberately
excludes it.

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

Unrecognized active routing is rejected before modifying routing binaries or SIP
files. Applying the binary patch requires a complete known firmware hash, not
only matching instruction ranges. These checks do not authorize replacing
third-party routing files with stock configuration.

When the media user cannot be set up after the routing binary was patched by
this request, the routing is restored before the error is returned. Ensure and
restore answer `"root_writable": true` when the routing write succeeded but `/`
could not be made read-only again (the replaced binary is still running); a
reboot makes it read-only. The agent remembers that root as its own, also
across an agent restart, and its next device write or agent update tries the
read-only remount again.

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

Authentication: API token or maintenance token; also readable during API noAuth
bootstrap. Reading does not authorize configuration changes.

Side effects: none.

Returns auth/bootstrap configuration without token values. Important fields:

- `noAuth` / `no_auth`
- `api_token_configured`
- `api_token_fingerprint`
- `maintenance_token_configured`
- `maintenance_token_fingerprint` (empty without maintenance authorization)
- `maintenance_enabled`
- `maintenance_no_auth_allowed`
- feature enabled flags, for example `video_enabled`, `events_enabled`,
  `display_bridge_enabled`, `firewall_enabled`, and `ipv6_firewall_enabled`

### `POST /api/v1/maintenance/auth`

Authentication: the existing maintenance token, even if maintenance actions are
disabled. A normal API token is insufficient. Token-free bootstrap requires
`api.noAuth`, `maintenance.enabled`, and `maintenance.allowNoAuth` together.

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

Execution is hybrid; **not every operation is off the HTTP loop yet** (see
[Remaining Blocking Work](../docs/dev/architecture.md#remaining-blocking-work)). QML status/patch, GUI reload, the read-only device-user
status script, SSH probe/start/stop and SSH-before-reboot/removal share one
asynchronous job slot. Connections stay open until the existing response
boundary; no new job ID, queue or early-success response is introduced.

While that slot is occupied, authorized maintenance POSTs and competing QML or
device-user status reads return `409` with `error: maintenance_busy`. An enabled,
authorized SSH GET instead waits in an existing bounded input slot, without a
new busy status or execution deadline. The 500ms receive deadline applies to
incomplete input, not a complete deferred SSH request. Unauthorized and disabled
SSH requests are not deferred. Retrying a busy request must wait for completion.

QML status and standalone GUI reload retain a 10-second script deadline; QML
writes retain 30 seconds for a failed start, rollback and restart of the previous
GUI. Their failed execution, timeout and overflowing 4096-byte output retain
the existing `502` responses, with one exception: a QML write (apply,
apply-core, restore-core, restore) past its 30 seconds gets `SIGTERM` for its
process group first, not `SIGKILL`. A QML write whose output overflows gets the
same `SIGTERM` and grace period, and is then answered `502` with
`state: script_failed`. A write that ended by itself is answered with its own
result even when the agent reaps it only on the deadline tick. The script's trap then restores the GUI
files it changed, remounts `/` read-only and restarts the previous GUI. The agent
gives it 15 seconds for that, the trap's worst case on the device (two 2-second
GUI restart waits, the remount and the file moves) with margin, and sends
`SIGKILL` only after them. The request stays open until the script has really
ended and is then answered with `504`:

```json
{"ok": false, "available": true, "error": "qml_patch_timeout", "rolled_back": true}
```

`rolled_back` is `true` only when the script exited with status 130: it
stopped on the signal with every GUI file it changed back in place and `/`
read-only again, or before it changed any. The script exits 131 when the
signal came after a QML write had committed, during the display library step
of apply, restore and restore-all, or when its rollback was incomplete: it
first remounts `/` read-only and restarts a GUI that is down or still runs the
replaced library. `false` means such a 131, a failed rollback, or a script
that had to be killed; `GET /api/v1/maintenance/qml-patch` then says
what the device has and reports a transaction the write left behind; the next
write finishes it (see QML Patch).
Graceful agent shutdown during a QML write sends that `SIGTERM` once, as the
first step of its clean-up, and waits up to the same 15 seconds before
`SIGKILL` at the end of it; that request is closed without an answer. The init
script's own stop sends `SIGKILL` to the agent after 3 seconds; the script, in
a process group of its own, has its signal by then and still finishes its
rollback. A write cut off even so is finished at the next agent start.

At start the agent runs `qml_patch.sh recover` once when QML maintenance is
enabled and the script exists: a job without a client, with the QML write
deadline and grace period. It finishes a transaction that a power loss, a
crash or a killed write left behind (see QML Patch) and returns at once when
there is none. Meanwhile other maintenance requests get `409
maintenance_busy`, like during any other job. Device-user status alone also has a 10-second
deadline and a 4096-byte bounded-prefix capture; script failure retains HTTP 200
with unavailable/unknown label status. SSH start and stop have a 60-second
deadline and SSH status a 15-second one; at the deadline the process group is
killed with `SIGKILL`; an action then fails like a failed command and a
status reads as not running, so a hanging script no longer holds maintenance. They discard output.

Device-user native routing/user mutations and label apply/restore are
**synchronous**. Label writes use an 8192-byte bounded-prefix capture, without
an execution deadline, `SIGKILL` cancellation or `pthread_cancel`. Graceful agent
shutdown waits for the script to finish commit/rollback and remount cleanup.
This deliberately replaces the old unsafe ten-second label-write kill timeout.
A hung script can block HTTP dispatch and graceful shutdown indefinitely; a
client timeout or disconnect does not abort or replay a physical write. Forced
process termination and power loss are not covered by this guarantee.

Only after the write phase finishes does device-user start its asynchronous
read-only status phase. Ensure still requires successful label-script exit and
JSON `ok:true`; restore retains its exit-status-only interpretation. Native
codec file mutation also remains synchronous; only its reboot tail uses jobs.
Shutdown cancels an active asynchronous job without invoking its completion
or advancing another phase, but cannot reach that cleanup during a synchronous
label transaction. A QML write job gets `SIGTERM` and its grace period at its
deadline and at shutdown (see above); one that is killed even so, or loses
power, leaves a transaction that the next write or agent start finishes.

See [HTTP maintenance ownership](../docs/dev/architecture.md#http-maintenance-boundary) and the
[remaining blocking work](../docs/dev/architecture.md#remaining-blocking-work).

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
  "agent_version": "2.4.0"
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

Errors:

| Status | `error` | Meaning |
| --- | --- | --- |
| `400` | `maintenance_confirmation_required` | The body does not carry `"confirm": "update_agent"`. |
| `400` | `invalid_update_metadata` | `bundle_hash` is missing or does not start with `sha256:`. |
| `400` | `update_manifest_missing` | The staged `device_agent/bundle.json` is missing, empty or only line breaks, unreadable or 8 KiB or larger. |
| `400` | `update_bundle_hash_mismatch` | `bundle_hash` differs from the hash in the staged manifest. |
| `403` | `maintenance_unauthorized` | Maintenance is disabled, or the maintenance token is missing or wrong. |
| `409` | `update_root_already_writable` | `/` was already writable before the update (by someone else, or left so by the agent and still busy); the agent refuses to install and leaves the mount as it is. |
| `409` | `qt5_recovery_required` | Firmware 3.0.x: the staged agent has no Qt 5 display recovery while overlay files, a quarantine or an unverified display start script remain. The installed agent and its recovery stay untouched. |
| `500` | `update_root_readonly_failed` | The update could not make `/` read-only again after writing to it. |
| `500` | `update_apply_failed` | Validation or installation failed. |
| `500` | `out_of_memory` | The agent could not allocate the memory for the update. |
| `500` | `invalid_agent_dir` | The staging path of the manifest cannot be built from the configured agent directory. |

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
or shell commands. The script keeps the vendor's mode and is synced to disk
with its backup; when iptables refuses the new rules at once, apply answers
`runtime_apply_failed` and puts the previous script back (IPv4 and IPv6
alike).

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

The capability `ipv6_firewall_hook` says whether the configured IPv6 firewall
start script exists on the station. Firmware 3.0.x has none
(`/etc/network/if-pre-up.d/iptables6`), so it reports `false` there and Home
Assistant does not offer the IPv6 firewall switch; apply would answer
`missing`.

### QML Patch

`GET /api/v1/maintenance/qml-patch`

Reads both optional Display patch state and required core media-hook state.
`home_buttons` names the home page button layout installed on the device:
`"stock"` (the stock layout), `"side_by_side"` (the fixed pair), or `null`
when the home page carries neither layout. On firmware 3.0.x it is also `null`
while the overlay is not active (`qt5_overlay` other than `active`): the
display then shows the vendor home page.

On firmware 3.0.x, `qt5_unsupported` names why the station's display program or
start script is not one the agent knows (`display_program_unknown`,
`display_resource_missing`, `display_file_unsupported`,
`display_wrapper_unknown`). The apply actions then change nothing and answer
`200` with `"ok":false,"error":"display_unsupported"` and the status fields; the
agent runs without the display pages. The field stays until an apply finds a
known display again. Full removal also records `display_wrapper_unknown` when
the start script is no longer the original with a block of this or an earlier
beta in it, for example after a
vendor update; it then removes the overlay files and leaves that script as it
is.

Every QML write keeps the GUI files it may change in a transaction directory
`.c300x-qml-transaction.<pid>` inside the GUI directory. The directory gets a
format marker `.c300x-v2` first, then the copies, then a file list that names
the files it found and the ones it would add, written only once all copies are
on flash and before any GUI file changes. A write cut off for good (power loss,
crash, `SIGKILL`) leaves that directory behind.

On firmware 3.0.x the GUI directory is the agent's working copy
(`display-qt5/skins/default`), and the transaction also keeps copies of the
display activation files (resource file, preload library, start script, its
original backup, quarantine mark) in `.qt5/`, saved before the file list. A
write marks `.qt5/.published` before it changes any of them; a rollback then
first quarantines the overlay for this boot, puts every activation file back
and restores the quarantine mark last, and restarts the GUI when the resource
file, the library or the start script differed. The import that fills the
working copy from the firmware before every apply is not part of the
transaction: it only adds missing files, each written whole, and drops the
copy when the firmware's files change.

Status only reads: it reports a leftover and never changes the device. The
recovery runs before every write and once at agent start (the `recover`
action, see the maintenance job deadlines above). It skips
everything while a transaction of a running write exists and otherwise
finishes each leftover whose process is gone, in an order that a later run
can repeat from any point where it was cut off:

1. Roll back. With the file list: files back in place, files the write added
   removed. With the marker and no list: nothing to do, no GUI file had
   changed. Without the marker (a write of agent 2.9.0 or older, which kept
   no list): only copies proven complete are moved back, i.e. byte-equal to
   the stock backup of that file, to the agent's own source of a generated
   file, or to the file in place. When a display file is newer than that
   directory, a later write has replaced the files since, and the proven
   copies are dropped instead of moved back (a restore that already started
   is finished). On firmware 3.0.x the activation copies of such a write
   count only while each equals the file in place and no activation file was
   added. If any copy cannot be proven, the directory
   stays, the GUI is left as it is and the leftover is reported `stuck` for
   good; remove the directory by hand once the display works.
2. Restart the GUI, only when step 1 changed a file. A marker file in the
   directory keeps that fact for a run that is cut off before the restart.
3. Remove the directory: marker files first, the copies, the format marker
   last, so that a cut-off removal still leaves a directory the next run
   finishes.
4. Remount `/` read-only. Every remount read-write leaves a mark naming the
   process in `$TMPDIR` (default `/tmp`, RAM on the device); the next run
   remounts read-only when that process is gone, and a reboot clears it.

The answers carry one more field when a leftover exists:

- `"transaction": "pending"` (status): a leftover waits for the next write or
  agent start.
- `"transaction": "recovered"` (write, recovery): this run finished a leftover.
- `"transaction": "stuck"`: a leftover could not be finished; its directory
  stays. A leftover with the format marker is tried again at the next
  recovery; one without it is not.

Without a leftover the field is absent. While a leftover with the format
marker is stuck, or a transaction of another running write exists, a write
exits with status 1 before it prints anything (stderr: `An unfinished GUI
write is still in place`); the agent answers `502` with
`{"ok": false, "available": false, "state": "script_failed"}`, and the
device-user actions answer `500` with `media_user_label_setup_failed` or
`media_user_label_restore_failed`. A stuck leftover without the marker does
not block writes: every write builds its files from the stock backups and the
agent's sources, never from the files in place.

`POST /api/v1/maintenance/qml-patch/actions/apply-core`

```json
{"confirm": "apply_qml_core_patch"}
```

Applies the core EventManager hook: the media-close notification required for
reliable doorbell video ownership tracking and the `C300XRingerControl.qml`
command channel used by `POST /api/v1/ringer`.

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
the Settings > General HA feedback and touch-tone controls, the Alarmo, Home
Assistant and energy pages (`Alarm.qml`, `HomeAssistant.qml`,
`C300XEnergy.qml`) and the local QML JavaScript bridge.

`dynamic_homepage` chooses the home page button layout: `true` installs the
Alarm and Home Assistant buttons among the station's own buttons (shown only when
needed), `false` the fixed pair side by side. Without the field the layout
on the device is kept; a device without the Display patch gets the `true`
layout.

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
The agent's own device writes (routing, audio codec, camera, firewall, touch
patch) leave `/` as they found it: on a root that is already writable they
write without remounting and keep it writable, which is success.
`root_writable` / `remount_ro_failed` only report a root the agent made
writable and could not make read-only again; an agent removal stops for a
reboot only then. Such a root stays the agent's own (a mark in `/run` keeps
it across an agent restart): the next write retries the read-only remount,
and a retry that is still busy is not a failure.

### Camera Resolution

`GET /api/v1/maintenance/camera-resolution` returns
`{"ok": true, "high_resolution": true}`. `POST` with
`{"high_resolution": false}` saves `video.av.highResolution` and returns the
same body; it applies from the next stream that starts. Capabilities advertise
it as `maintenance.camera_resolution`. On firmware 3.0.x the agent fixes the low
resolution, does not advertise the setting, and answers a request for high
resolution with `409` and `error: "high_resolution_unsupported"`.

### Camera Quality

`GET /api/v1/maintenance/camera-quality` returns size, bit rate and frame rate
of the camera stream Home Assistant receives. That is the high-resolution
stream (`"stream": "high"`), and on firmware 3.0.x (Qt 5 display), which sends
only the low-resolution stream, that one (`"stream": "low"`):

```json
{"ok": true, "supported": true, "stream": "high", "bitrate_kbps": 800, "fps": 15,
 "size": "688x480", "running_bitrate_kbps": 800, "running_fps": 15,
 "running_size": "688x480", "bitrate_min": 300, "bitrate_max": 3000,
 "fps_min": 5, "fps_max": 24, "sizes": ["688x480", "704x576", "960x576"],
 "restart_required": false, "changed": false, "remount_ro_failed": false,
 "rebooting": false}
```

`bitrate_kbps`, `fps` and `size` are the saved values, `running_*` the ones
the device started with (`0` and `""` when the agent cannot tell), and
`restart_required` is `true` while the two differ. When the file could not be
read at the agent's start, the agent takes the values the file has before its
first change as the running ones. `sizes` lists the sizes a
request may choose. `960x576` is included only for the exact verified C300X
1.7.19 and 2.0.2 media executables, either original or patched. Each build
requires its own matching stock backup; build IDs are not normalized away. Other builds retain the
legacy High sizes. The high stream takes 300–3000 kbit/s and 5–24 fps: at
25 fps the device drops its frame rate control and sends about 8 frames per
second. The low stream takes 100–2000 kbit/s (the device lowers the bit rate
at run time and raises it again only up to 2000) and 5–25 fps, in the sizes
320x240, 352x288, 400x288 (from the factory), 480x288, 640x384, 640x480,
704x576, 720x432 and 720x576. The added 480x288, 640x384 and 720x432 choices have the LCD's
5:3 ratio; 320x240 is a compact 4:3 choice. Original 3.0.6 Low caps were
checked offline, not on hardware. Sizes other than 400x288, their framing and
performance remain untested on a 3.0.x device. Low writes only configuration;
it does not patch the executable or change the LCD window. 960x576 is never
offered for the Low path. See [3.0.6 Low evidence](../docs/dev/firmware-3.0.6-camera.md).

`POST` with `{"confirm": "apply_camera_quality", "size": "960x576",
"bitrate_kbps": 3000, "fps": 24}` saves new values and returns the same body;
each value may be left out and then stays as it is. Like the audio codec
switch, the agent then restarts the device when the saved values differ from
the running ones, unless the request sends `"reboot": false` or reboot
maintenance is disabled; `rebooting` says whether it does. A bit rate or frame
rate outside the limits is answered `400` with
`error: "camera_quality_out_of_range"`, a size not in `sizes` with
`camera_quality_invalid_size`, a value that is not a whole number with
`camera_quality_invalid_bitrate` or `camera_quality_invalid_fps`, and a
request with no value with `camera_quality_value_required`. A value the file
already has may stay even when it is outside the limits.
An active or starting media session rejects changes with `409` and
`camera_quality_media_session_active`. Geometry changes additionally require
an exact known executable and a verified original backup; unknown files or
invalid backups are not overwritten.
Concurrent camera maintenance is rejected with `409` and
`camera_quality_update_busy`, without changing configuration or the executable.

The device keeps the values in the `[Answering Machine]` section of
`/home/bticino/cfg/bt_answering_machine` and reads that file only when it
starts: `BitrateRtpH`, `FpsRtpH`, `Width` and `Height` for the high stream,
`BitrateRtpL`, `FpsRtpL`, `WidthLow` and `HeightLow` for the low one. For the
high stream the device crops the camera picture when `Width` is more than
1.5 times `Height`. The offered sizes keep `Width=800`, `Height=480`, which
also describe the LCD output, and adjust the crop in `stack_open.xml`:
`688x480` uses `(16,48,688,480)`; `704x576` uses `(8,0,704,576)`.
`960x576` uses the latter crop plus two hash-pinned instruction replacements
in the original media program. Both High caps filters then request width 960
before the existing hardware encoder; the height remains 576. There is no
additional encoding stage. Selecting a legacy size restores the original
binary. The low stream is scaled to `WidthLow` x `HeightLow` and is not patched.
The 960x576 live test does not establish the answering-machine recording format.

Saved geometry and running geometry are distinguished using the actual running
executable and process generation, including after an agent-only restart.
If the running geometry cannot be verified, `running_size` is empty. Unknown
status alone does not trigger a reboot; confirmed changes remain pending until
the device has restarted. There is no periodic geometry polling.

The agent changes the file only when each of the four values is there exactly
once, replaces those numbers and nothing else, keeps one backup of the
original file under `/home/bticino/cfg/extra/c300x-device-file-backups/original`,
writes a complete new file in one step, makes the root filesystem writable
only for the write, and reads the result back. Removing the agent puts the
original values back; a file without the values is left alone. After a
firmware update, only recognized binaries can be modified; a backup from a
different build must never be used to restore the new executable. An unsuccessful
media restoration aborts agent removal before agent files and backups are deleted.

Capabilities advertise the setting as `maintenance.camera_quality` whenever
video is enabled. A `POST` is answered `409` with
`error: "camera_quality_unsupported"` when the file does not hold the values,
and `GET` then reports `"supported": false`.

### Audio Codec

`GET /api/v1/maintenance/audio-codec` reads the codec state.

`POST /api/v1/maintenance/audio-codec/actions/apply` with
`{"confirm": "apply_audio_codec_patch"}` switches to PCMU;
`POST /api/v1/maintenance/audio-codec/actions/restore` with
`{"confirm": "restore_audio_codec_patch"}` switches to speex. Both rewrite the
same lines of `stack_open.xml` and `linphone.conf` in opposite directions, so
speex is available also on firmware 3.0.6, which comes with PCMU (not yet
tested on a 3.0.6 device). The first switch keeps a backup of the original
files; removing the agent reads the original codec from them and rewrites the
codec lines back to it, leaving the rest of both files as they are. When the
second file cannot be written, the first gets its content from before the
switch back. The codec takes effect after a reboot. When one is needed, the agent starts SSH and reboots the
device, unless the request sends `"reboot": false` or reboot maintenance is
disabled. A failed write returns `500` with `error: "audio_codec_apply_failed"`
or `"audio_codec_restore_failed"`.

## Loopback UI API

The UI listener is intended for local QML pages. Routes accept only GET, except
the guarded POST routes for preferences, touch-tone reports and station maintenance. Routes forwarding
requests to Home Assistant require an active display bridge.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | UI listener health. |
| `GET` | `/ui/memos` | Memo metadata for QML pages. |
| `GET` | `/ui/answering-machine/messages` | Video-message metadata for QML pages. |
| `GET` | `/ui/events/status` | Long-poll state for QML event bridge. |
| `GET` | `/ui/events/next` | Long-poll next QML event. |
| `GET` | `/ui/media-closed` | Display call-end hook: only wakes the display pages; does not publish `doorbell.media.closed` (the hook also fires when HA answers a ring). |
| `GET` | `/ui/ringer/next` | Core GUI ringer command/acknowledgment channel. |
| `GET` | `/ui/alerts/next` | One sleeping GUI alert delivery connection; no acknowledgement or queue. |
| `GET`, `POST` | `/ui/preferences` | Local display feedback preference, independent of HA registration. |
| `GET` | `/ui/maintenance` | Availability of SSH, reboot and removal on this station. |
| `GET`, `POST` | `/ui/maintenance/ssh` | Read SSH status or request `{"enabled":true}` or `{"enabled":false}`. A write checks the resulting process state. |
| `POST` | `/ui/maintenance/reboot` | Schedule a reboot with `{"confirm":"reboot"}`; leaves SSH unchanged. |
| `POST` | `/ui/maintenance/remove` | Schedule the existing agent removal and restoration script with `{"confirm":"remove_agent"}`. |
| `GET` | `/ui/touch-tone/next` | One sleeping GUI command connection; initial `enabled=0/1`, then matching `completed` ID and actual state acknowledge a command. |
| `POST` | `/ui/touch-tone/state` | Reports changes to the original GUI setting as `{"enabled":true}`. |
| `GET` | `/ui/state` | Display bridge state. |
| `GET` | `/ui/alarm/status` | Alarm status alias. |
| `GET` | `/homeassistant` | Render Home Assistant dashboard payload for QML. |
| `GET` | `/ui/action` | Execute configured display action. |
| `GET` | `/ui/alarm/command` | Execute configured alarm command. |

Home Assistant proxy endpoints use the display bridge and shared secret
configured through the API listener. Local metadata, preferences and core GUI
hooks do not require that registration. No route exposes configured token values.

Station maintenance works without HA. It requires the local maintenance and
per-action permissions, no browser Origin, the `X-C300X-UI: settings-v1`
header, and a loopback client socket owned by the unique trusted station GUI.
The socket must belong to UID 0. The GUI and wrapper must have root real,
effective, saved and filesystem UIDs and GIDs. Stock SysV startup runs
`bin/bt_daemon` from `/home/bticino`; its GUI entry in `stack_open.xml`
starts `bin/BtClass_qws`, whose shell waits for its direct `bin/gui/BtClass`
child. The Qt 5 display pages' start script runs `bin/gui/BtClass` inside a
pipeline instead, so up to two forks of the wrapper shell may sit between the
two; each must carry the same shell, working directory, wrapper argv and
credentials as the wrapper above it. The alternate launch from
`qml_patch.sh reload_gui` uses the absolute wrapper path and is accepted once
init has adopted the wrapper. Both paths require the expected shell, working
directory, complete wrapper argv and open script inode on the wrapper itself,
with read-only firmware files. A standalone GUI process, an
ambiguous instance or incomplete process evidence is denied, even with the
header. This identifies a local privileged process, not a physical gesture,
and does not protect against another root process. A scheduled reboot or removal returns 202:
it does not certify that the reboot or the restoration has already completed.

`GET /ui/alerts/next` requires loopback and `X-C300X-GUI: alerts-v1`, with no
`Origin` or request body. The optional exact query `protected=1` reports a
protected screen or call; all other query strings are rejected. Only one waiter
is retained; another receives
`409 display_alerts_listener_busy`. Idle waiting has no polling timer. Delivery
closes the connection and adds `remaining_ms`, `expires` (Unix milliseconds)
and `message_expires` (Unix milliseconds) to the validated alert. Delivery
freshness is limited to five seconds or the shorter notice lifetime. The GUI
checks freshness, deduplication, revision and safe-context rules before effects;
the connection is not a physical-effect acknowledgement. Failed listener
connections reconnect after a delay, without replaying past alerts.
The GUI reconnects when its protection state changes. Protection belongs to
that live connection and is cleared when it closes; it is not a persistent flag.

`GET /ui/preferences` returns `{"ok":true,"feedback_enabled":true}` by default.
Both `/ui/touch-tone/` routes require loopback, `X-C300X-UI: 1` and no `Origin`
header. Commands carry a random 32-hex-character ID and expiry; mismatched,
expired or missing acknowledgements never confirm an API write. The agent
stores only the current GUI state in memory and publishes
`display.touch_tone_changed` with `enabled` and `available`. GUI queries and
reports also carry a 32-hex-character `session` ordering identifier and an
increasing integer `revision`; older reports cannot replace newer confirmed
state, including across GUI restarts. No firmware or
agent configuration file is changed by these routes; the GUI applies the stock
`global.beepEnabled` setter. Idle operation has no poll expiry or periodic reads.

`POST /ui/preferences` accepts a boolean `feedback_enabled`, requires
`X-C300X-UI: 1` and rejects requests with an `Origin` header. Only the loopback UI
listener exposes it; browser preflight and other methods are rejected. The
agent persists changes as `displayBridge.feedbackEnabled`, preserving unrelated
pending configuration. Reads and unchanged values cause no filesystem writes.
A failed save leaves the live preference unchanged and returns HTTP 500. QML
only updates the switch after confirmation; an ambiguous timeout requires a
fresh read before another write.

The core `/ui/ringer/next` endpoint is independent of display-bridge registration.
It accepts only loopback GETs with `X-C300X-GUI: ringer-v1`; no CORS preflight
is allowed. One connection waits indefinitely without periodic device reads.
An authorized API ringer request returns `{ok, id, muted, expires}` to that
connection; `id` is a fresh 128-bit random command identifier and `expires` a
Unix-millisecond deadline. The GUI applies unexpired commands and reconnects
with `?completed=<id>&muted=0|1`, confirming its actual saved state. Stale,
incorrect and missing confirmations cannot complete another command. The API
request has a monotonic five-second deadline. Diagnostics expose
`ringer_gui_ready` and `ringer_command_pending`, but never command identifiers.

## Compatibility

Agent `2.10.0b1` retains self-test contract `api_version: "1.1"` for firmware families
`1.7.x`, `2.0.x` and `3.0.x`. `firmware_family` is derived from `device.firmware` of
the agent config, or from the station's firmware info when that is empty, which
is what the installer writes; it is `unknown` only when neither is readable. Of
the `2.0.x` family only `2.0.2` is supported, of `3.0.x` only `3.0.6`,
experimentally. The release notes list the agent changes of each version.
