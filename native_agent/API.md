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
- Current agent version: `2.7.0`
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
  QML pages running on the device.

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
| `201 Created` | Runtime subscription or text memo was created. |
| `202 Accepted` | Display wake-up accepted, or reboot, agent removal or restart scheduled. |
| `400 Bad Request` | Invalid body, missing field, invalid id, or missing confirmation token. |
| `401 Unauthorized` | Normal API token is missing or invalid. |
| `403 Forbidden` | Maintenance token is missing/invalid or maintenance is disabled, the endpoint requires loopback, or a required UI header is missing. |
| `404 Not Found` | Setup disabled, media item missing, feature disabled, or maintenance module disabled (`maintenance_disabled`). |
| `405 Method Not Allowed` | Wrong method on a loopback UI route. |
| `409 Conflict` | Media action conflicts with the current device/media state. |
| `413 Payload Too Large` | HTTP body exceeded the static parser buffer. |
| `429 Too Many Requests` | Snapshot requested less than two seconds after the previous one. |
| `500 Internal Server Error` | Agent-side operation failed. |
| `501 Not Implemented` | Unknown endpoint. |
| `502 Bad Gateway` | Home Assistant callback/display bridge is unavailable. |
| `503 Service Unavailable` | Resource busy or inactive (transfer slots, system metrics, snapshot source, ringer GUI, display command). |
| `504 Gateway Timeout` | The GUI did not acknowledge a ringer command within five seconds. |

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
| `GET` | `/api/v1/maintenance/audio-codec` | maintenance | Reads the device audio codec (speex/PCMU) state. |
| `POST` | `/api/v1/maintenance/audio-codec/actions/apply` | maintenance | Switches the device to PCMU and reboots after confirmation. |
| `POST` | `/api/v1/maintenance/audio-codec/actions/restore` | maintenance | Restores the stock speex codec and reboots after confirmation. |

## Health, Capabilities, State

### `GET /api/v1/health`

Authentication: none.

Side effects: none.

Response:

```json
{"ok": true, "agent": "native-c", "version": "2.4.0"}
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
- `events` must contain at least one event.
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

Response status: `202 Accepted` on success.

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

Returns active ring-call status, media ownership, capture readiness, and
`hangup_requested` while the native ring-call hangup path is being driven.

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
`docs/native-http-blocking-inventory.md`). QML status/patch, GUI reload, the read-only device-user
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
the existing `502` responses. Device-user status alone also has a 10-second
deadline and a 4096-byte bounded-prefix capture; script failure retains HTTP 200
with unavailable/unknown label status. SSH/service jobs have no execution
deadline and discard output, preserving their previous wait semantics.

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
label transaction. Existing QML-write job cancellation is unchanged, not newly
certified as transaction-safe by the label-write fix.

See [HTTP maintenance ownership](../docs/native-http-maintenance.md) and the
[remaining blocking-path inventory](../docs/native-http-blocking-inventory.md).

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

### Camera Resolution

`GET /api/v1/maintenance/camera-resolution` returns
`{"ok": true, "high_resolution": true}`. `POST` with
`{"high_resolution": false}` saves `video.av.highResolution` and returns the
same body; it applies from the next stream that starts. Capabilities advertise
it as `maintenance.camera_resolution`. On firmware 3.0.x the agent fixes the low
resolution, does not advertise the setting, and answers a request for high
resolution with `409` and `error: "high_resolution_unsupported"`.

### Audio Codec

`GET /api/v1/maintenance/audio-codec` reads the codec state.

`POST /api/v1/maintenance/audio-codec/actions/apply` with
`{"confirm": "apply_audio_codec_patch"}` switches to PCMU;
`POST /api/v1/maintenance/audio-codec/actions/restore` with
`{"confirm": "restore_audio_codec_patch"}` restores speex. The codec takes
effect after a reboot. When one is needed, the agent starts SSH and reboots the
device, unless the request sends `"reboot": false` or reboot maintenance is
disabled. A failed write returns `500` with `error: "audio_codec_apply_failed"`
or `"audio_codec_restore_failed"`.

## Loopback UI API

The UI listener is intended for local QML pages. Routes accept only GET, except
the guarded POST routes `/ui/preferences` and `/ui/touch-tone/state`. Routes forwarding
requests to Home Assistant require an active display bridge.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | UI listener health. |
| `GET` | `/ui/memos` | Memo metadata for QML pages. |
| `GET` | `/ui/answering-machine/messages` | Video-message metadata for QML pages. |
| `GET` | `/ui/events/status` | Long-poll state for QML event bridge. |
| `GET` | `/ui/events/next` | Long-poll next QML event. |
| `GET` | `/ui/media-closed` | Reports device media-close event. |
| `GET` | `/ui/ringer/next` | Core GUI ringer command/acknowledgment channel. |
| `GET` | `/ui/alerts/next` | One sleeping GUI alert delivery connection; no acknowledgement or queue. |
| `GET`, `POST` | `/ui/preferences` | Local display feedback preference, independent of HA registration. |
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

Agent `2.7.0` retains self-test contract `api_version: "1.1"` for firmware families
`1.7.x`, `2.0.x` and `3.0.x`. `firmware_family` reflects `device.firmware` of the agent
config and is `unknown` when that value is empty, which is what the installer
writes. Of the `2.0.x` family only `2.0.2` is supported, of `3.0.x` only `3.0.6`,
experimentally. The release notes list the agent changes of each version.
