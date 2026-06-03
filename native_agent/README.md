# C300X Native Agent

Native C runtime for BTicino C300X.

## Goals

- Single on-device runtime without Node.js.
- Authenticated local API for Home Assistant.
- Push/event-driven callbacks.
- Optional video and display-bridge modules behind capabilities/config.

The native binary deliberately ships without a TLS stack. Use local HTTP on the
trusted HA/device segment or terminate HTTPS in a local reverse proxy if a
deployment requires TLS.

## Build

```bash
make -C native_agent
make -C native_agent check
make -C native_agent armhf armhf-abi-check
make -C native_agent armhf-stack-check
```

## Run locally

```bash
cp native_agent/config.example.json native_agent/config.json
$EDITOR native_agent/config.json
native_agent/build/host/c300x-agent-native --config native_agent/config.json
```

## Main API endpoints

Public on the API listener:

- `GET /` (only while `api.noAuth=true`)
- `GET /setup` (only while `api.noAuth=true`)
- `GET /api/v1/health`

Public on the internal loopback UI listener:

- `GET /health`

`config.example.json` intentionally starts with `api.noAuth=true`,
`maintenance.enabled=true`, `maintenance.allowNoAuth=true`, and empty tokens so a
fresh local install can be bootstrapped through `/setup` without editing secrets
over SSH. Use `/setup` or Home Assistant's maintenance switch to write the API
token and maintenance token, then disable `noAuth` and noAuth maintenance access.
The setup page does not expose configured token values; it only reports whether
they exist plus non-secret fingerprints. Paste known tokens into the request
fields when you need manual API calls from the setup page. Saves from the setup
page are treated as bootstrap completion: once an API token is configured, that
save automatically closes `noAuth` and noAuth maintenance access. The Home
Assistant maintenance switches can still explicitly reopen those windows later
when needed.
When `api.noAuth=false`, the setup website is not served at all. Token-based API
and maintenance endpoints remain available, but the browser bootstrap UI is
closed.
In Home Assistant these bootstrap flags are represented as maintenance switch
entities, not normal integration options. Turning the `noAuth` entity off after
tokens are configured also closes the noAuth maintenance window.

Authenticated (bearer token):

- `GET /api/v1/capabilities`
- `GET /api/v1/state`
- `GET /api/v1/events/recent`
- `GET /api/v1/events/subscriptions`
- `POST /api/v1/events/subscriptions`
- `DELETE /api/v1/events/subscriptions/{id}`
- `GET /api/v1/diagnostics`
- `POST /api/v1/locks/{id}/actions/unlock`
- `POST /api/v1/stair-light/actions/activate`
- `GET /api/v1/activations`
- `POST /api/v1/activations/{id}/actions/run`
- `GET/POST /api/v1/ringer`
- `GET/POST /api/v1/smartphone-forwarding`
- `GET/POST /api/v1/answering-machine`
- `GET /api/v1/answering-machine/messages`
- `GET /api/v1/answering-machine/messages/{id}/video`
- `POST /api/v1/answering-machine/messages/actions/delete`
- `GET /api/v1/memos`
- `POST /api/v1/memos/actions/delete`
- `GET /api/v1/system/metrics`
- `GET/POST /api/v1/maintenance/auth`
- `GET /api/v1/video/doorbell` (when video module enabled)
- `GET /api/v1/video/doorbell/status`
- `POST /api/v1/video/doorbell/actions/activate`
- `POST /api/v1/video/doorbell/actions/stop`
- `GET/POST /api/v1/maintenance/ssh`
- `POST /api/v1/maintenance/ssh/actions/start`
- `POST /api/v1/maintenance/ssh/actions/stop`
- `POST /api/v1/maintenance/reboot`
- `POST /api/v1/maintenance/agent/actions/remove`
- `POST /api/v1/maintenance/gui/actions/reload`
- `GET /api/v1/maintenance/firewall`
- `POST /api/v1/maintenance/firewall/actions/apply`
- `POST /api/v1/maintenance/firewall/actions/restore`
- `GET /api/v1/maintenance/ipv6-firewall`
- `POST /api/v1/maintenance/ipv6-firewall/actions/apply`
- `POST /api/v1/maintenance/ipv6-firewall/actions/restore`
- `GET /api/v1/maintenance/qml-patch`
- `POST /api/v1/maintenance/qml-patch/actions/apply`
- `POST /api/v1/maintenance/qml-patch/actions/restore`

Activation items use `addressMode: "manual"` when the configured `address`
contains the OpenWebNet `where` value. `addressMode: "auto"` is reserved for
read-only device discovery; auto items without a discovered address or explicit
command are returned as non-executable.

Maintenance endpoints (`ssh`, `reboot`, `agentRemove`, `guiReload`, `firewall`,
`qmlPatch`) stay unavailable unless each command is explicitly enabled in
config. The sample opens `maintenance.allowNoAuth` only as a bootstrap default
for initial setup.
The HA noAuth-maintenance switch sets `maintenance.enabled=true` when it opens
that window, but turning the switch off only disables noAuth maintenance access;
token-based maintenance remains available when configured.

The optional mDNS responder is intentionally limited to Home Assistant Zeroconf:
it advertises `_bticino-c300x-agent._tcp.local` with PTR/SRV/TXT/A records only
until HA connects in the current agent process through event subscription or the
display bridge. Persisted subscriptions from an earlier run do not suppress
discovery by themselves. The TXT `id` and advertised host name are derived from
the device MAC address when available, with a hostname fallback, so multiple
C300X devices do not collide in HA discovery. mDNS can be disabled through
`/setup` or the HA maintenance mDNS switch.

The firewall maintenance endpoints manage one explicit IPv4 block in
`/etc/network/if-pre-up.d/iptables` and one explicit IPv6 block in
`/etc/network/if-pre-up.d/iptables6`. The IPv6 block allows `ipv6-icmp` and
the configured API TCP port as destination and source port, using idempotent
`ip6tables -C` checks before inserting rules. Status is read-only.
Apply/restore compare the final content first, back up each original file once under
`/home/bticino/cfg/extra/c300x-device-file-backups/original`, remount the root
filesystem writable only for the final write when needed, and remount it
read-only immediately afterwards. The endpoint never accepts arbitrary iptables
or ip6tables rules or shell commands.

The device UI maintenance endpoints only run the configured fixed local helper;
they do not accept arbitrary commands. `core-apply` installs the small
EventManager media-close hook required for reliable doorbell video ownership
tracking, independently from the optional device dashboard patch. `apply`
installs that core hook plus the complete GUI function patch: MainApp navigation,
HomePage unread memo/video-message badges, MemoPage external-delete refresh,
Alarmo/Home Assistant pages, and the local QML JavaScript bridge. `restore`
removes only the optional GUI function patch and keeps the core media hook;
`restore-all` is reserved for agent removal and restores the core hook too. The
script backs up original GUI files under
`/home/bticino/cfg/extra/c300x-device-file-backups/original` and does not back
up generated agent files on the device. Apply/restore first render the desired
tree into a temporary staging directory, compare target files byte-for-byte, and
only remount the root filesystem writable for the final copy when at least one
file differs. The `status` action is read-only and reports both the optional GUI
patch state and the core media-hook state.

`/api/v1/diagnostics` exposes non-secret write counters (`agent_write_count`,
`last_write_class`, `last_write_reason`, `subscription_store_writes`, and
`qml_patch_last_action`) so HA can verify that idle operation stays write-free.
Firewall apply/restore writes are reported with `last_write_class=firewall`;
IPv6 firewall writes use `last_write_class=ipv6_firewall`.

`systemMetrics` defaults to agent-side sampling every 30 seconds. It pushes
updates only when the value differs from the last HA push by the configured
threshold, or after the 600 second heartbeat. CPU/load use percentage-point
thresholds; temperature uses percent change. HA does not need a periodic
metrics poll.
