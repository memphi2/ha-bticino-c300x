# Native Agent

## Runtime target

The device runtime is a native C binary from `native_agent/`. Node.js and `node_modules` are not part of the runtime path.

## Build

```bash
make -C native_agent
make -C native_agent armhf armhf-abi-check armhf-stack-check
```

For HACS/user installs the preferred path is a version-matched packaged ARMHF
agent bundle. The Home Assistant config flow can install that bundle before the
normal token and feature pages when the agent is not reachable yet. A source
checkout may use `native_agent/build/armhf/c300x-agent-native`, but the config
flow never runs `make` itself.

Release packages are built with `scripts/build_hacs_release.py`. The script
builds the ARMHF binary once, copies the device QML support files and QML patch
helper into the custom component package, and writes a HACS-ready zip under
`.release/`.

The bootstrap installer puts the following files on the C300X:

- `c300x-agent-native`
- generated `config.json` with generated API and maintenance tokens
- `/etc/init.d/c300x-native-agent` and `/etc/rc5.d/S40c300x-native-agent`
- QML support files under the agent directory
- `qml_patch.sh`
- `remove_agent.sh`

It does not silently apply GUI, firewall, or IPv6 firewall changes during Home
Assistant startup.

## Config

Use `native_agent/config.example.json` as template. Keep real config untracked.
The example is deliberately a first-setup bootstrap profile:
`api.noAuth=true`, `maintenance.enabled=true`, and
`maintenance.allowNoAuth=true` with empty tokens. Set the API and maintenance
tokens through `/setup` or HA maintenance controls, then close noAuth access.
Installer-generated device tokens are stored on the C300X in
`/home/bticino/cfg/extra/c300x-native-agent/config.json` as `api.token` and
`maintenance.adminToken`. Home Assistant stores its own copy in the integration
config entry/options and uses it automatically; do not edit HA `.storage`
manually and do not copy token values into logs, issues, commits or
documentation.
The HA-facing controls for this are maintenance switch entities. They are not
normal integration options, and turning off the `noAuth` entity after token setup
also turns off noAuth maintenance access. `/setup` never reads configured token
values back from the agent; it only shows configured state and non-secret
fingerprints. Paste known tokens into the request fields when manual API calls
need authorization. Saves from `/setup` are
treated as bootstrap completion: once an API token is configured, that save
automatically turns off `api.noAuth` and `maintenance.allowNoAuth`.

Default runtime security is deliberately low-load and local-first: token auth
after bootstrap, video disabled until HA enables it, media starts only when Home
Assistant requests it, and no GUI/firewall writes unless a maintenance action is
explicitly invoked.

Key sections:

- `listen`: API/UI bind and ports
- `api`: bearer token
- `openwebnet`: local OpenWebNet endpoint
- `events`: callback store and timeout
- `maintenance`: gated SSH/reboot/GUI-reload commands
- `systemMetrics`: optional low-frequency push updates for load and temperature
- `video`: optional app-like doorstation media support
- `displayBridge`: optional dashboard proxy for QML

Callback URLs for event subscriptions and the display bridge must use a local
Home Assistant HTTP URL with a stable local IPv4 address or stable ULA/global
IPv6 address. Do not use `homeassistant.local`, other `.local` names, or
link-local addresses for callbacks or media routing; those names can resolve to
different paths for Home Assistant, the C300X, browsers and HA Cloud.

The Home Assistant integration can override only the callback base URL sent to
the agent. This is a Home Assistant-side setting; the agent still receives the
normal generated webhook path and shared secret. The override must be plain
local HTTP and must not use `.local`, loopback or link-local addresses.

The native agent intentionally has no TLS client stack; HTTPS termination
belongs on the Home Assistant side or a local reverse proxy. The same applies
to the agent API: Home Assistant may connect through HTTPS if a local reverse
proxy terminates TLS, but the shipped native binary itself stays plain HTTP to
avoid TLS library dependencies and idle CPU/memory cost on the C300X.

## API surface

Public:

- `GET /health`
- `GET /api/v1/health`

Loopback-only display endpoints:

- `GET /ui/memos`
- `GET /ui/answering-machine/messages`

Authenticated with bearer token:

- `GET /api/v1/capabilities`
- `GET /api/v1/state`
- `GET /api/v1/events/recent`
- `GET/POST /api/v1/events/subscriptions`
- `DELETE /api/v1/events/subscriptions/{id}`
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
- `GET /api/v1/video/doorbell`
- `GET /api/v1/video/doorbell/status`
- `POST /api/v1/video/doorbell/actions/activate`
- `POST /api/v1/video/doorbell/actions/stop`
- `POST /api/v1/maintenance/ssh/actions/start`
- `POST /api/v1/maintenance/reboot`
- `POST /api/v1/maintenance/agent/actions/remove`
- `POST /api/v1/maintenance/gui/actions/reload`
- `GET /api/v1/maintenance/qml-patch`
- `POST /api/v1/maintenance/qml-patch/actions/apply`
- `POST /api/v1/maintenance/qml-patch/actions/restore`

Activation items use `addressMode: "manual"` when the configured `address`
contains the OpenWebNet `where` value. `addressMode: "auto"` is reserved for
read-only device discovery; auto items without a discovered address or explicit
command are returned as non-executable.

Maintenance capabilities are only advertised when explicitly enabled. During
first setup, the example allows noAuth access to the auth/config maintenance
surface so tokens can be set without SSH-editing secrets. Close that setup
window after configuration; token-based maintenance remains intact when noAuth
maintenance access is turned off.

The optional mDNS responder advertises `_bticino-c300x-agent._tcp.local` only
while the agent has no HA event subscription or display-bridge registration. It
uses a per-device TXT `id` and host name derived from the device MAC address
when available, with a hostname fallback, and is controlled by the `mdns.enabled`
config flag and the HA mDNS maintenance switch.

The QML patch and GUI reload maintenance paths are intentionally narrow: the
agent can only run the configured local UI helper with fixed `status`, `apply`,
`restore`, or `reload` arguments. The patch is a complete device-GUI function
patch, not just two extra pages: it wires MainApp navigation, transforms the
original-device HomePage for unread memo/video-message badges, transforms the
original-device MemoPage for external-delete refresh, installs the project-owned
Alarmo/Home Assistant pages, and installs the local QML JavaScript bridge.
Original GUI files are backed up under
`/home/bticino/cfg/extra/c300x-device-file-backups/original`; generated agent
files are not backed up on the device.

The remove-agent maintenance action is explicit and token protected. It first
restores the GUI patch, then restores IPv6 and IPv4 firewall scripts, then
removes the native-agent init files, agent directory, and agent-owned backups.
SSH is started before and after the cleanup and is deliberately not removed. If
a restore step fails, the script stops before deleting the backups.

System metrics are sampled by the agent, not polled by Home Assistant. The
default config emits a push event when values change from the last HA push by
the configured threshold, plus a 600 second heartbeat. CPU/load use
percentage-point thresholds; temperature uses percent change.

## Agent updates

Agent updates are HA-orchestrated and explicit. The C300X does not download
arbitrary binaries on its own and does not check for updates in idle.

- HA compares the installed agent and bundle state with the packaged bundle.
- If an update is needed, Home Assistant raises a Repair.
- The Repair uploads the packaged files through the maintenance API only after
  user confirmation.
- The agent verifies staged files before apply, preserves the existing config
  and subscription store, and restarts only after the update request.
- Older agents without self-update support still require the installer/SSH path.

## Smoke tests

```bash
make -C native_agent check
```

`make -C native_agent smoke` is optional and intentionally separate because it
exercises maintenance/write paths in a temporary runtime tree.

## ABI and stack guards

`armhf-abi-check` ensures the produced ARMHF binary stays compatible with the
firmware glibc baseline and needs a C300X firmware sysroot through
`C300X_DEVICE_SYSROOT`. Public CI runners do not ship that proprietary sysroot,
so they still compile the ARMHF target and run `armhf-stack-check`, while local
release builds must run the ABI check against the real device sysroot.
`armhf-stack-check` rejects oversized or dynamic stack usage records for the
ARMHF build.
