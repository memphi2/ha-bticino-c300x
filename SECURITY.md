# Security Policy

## Scope

This project is intended for local use with a BTicino Classe 300X / C300X on a
trusted Home Assistant network. It contains a Home Assistant custom integration,
a native C device agent, and optional project-owned QML pages.

The repository must not contain firmware images, APKs, vendored third-party
controller code, private hosts, usernames, tokens, or runtime payloads.
See [docs/legal.md](docs/legal.md) for the corresponding legal and asset-hygiene
gate.

## Recommendations

- Do not expose the native agent API, setup page, display bridge, RTSP/WebRTC
  ports, or the C300X device to the internet.
- Keep the native agent bound to the smallest reachable network surface needed
  by Home Assistant.
- Keep `api.noAuth` disabled after bootstrap.
- Use a strong API token and a separate maintenance token.
- Keep maintenance features disabled unless they are actively needed.
- Treat Home Assistant backups and the device agent config as sensitive because
  they can contain local access tokens.
- Avoid sharing debug logs, diagnostics, screenshots, or packet captures without
  reviewing them for private hosts and local identifiers.

Maintenance steps for keys, noAuth and SSH are in
[Keys and access](docs/classe-300x/5-update-and-removal.md#keys-and-access).

## Home Assistant Service Permissions

Calls with a Home Assistant user context are checked before sending device
commands. Doors, the stair light, activations, maintenance and deleting stored
messages are buttons: Home Assistant checks control permission for the button
entity on `button.press`. Media and call services (picture, doorbell video,
answer, hang up, Home Call) require control permission for the station's
camera entity. Alarm commands require permission for the configured alarm
entity. Configured HA actions retain the original user context and the target
service's permission checks.

Capture and analysis (including the unlock after a ring analysis), display
notification management and stored-message services require an administrator.
Context-free HA automations remain trusted. The physical display uses its
separate authenticated bridge and configured action allowlist, not HA user
impersonation.

Picture tiles are the exception to the bridge: the display loads a scaled
still of a camera or image entity directly from Home Assistant. The address
needs no login. It is signed with the entry's shared secret, serves only
entities placed on the display pages while the entry is loaded and the display
feature is on, and is sent to the device over the same connection as the other
display data. The address does not expire and is served by Home Assistant's
own web server, so it works from wherever Home Assistant can be reached. Do not
place a camera on the display pages whose picture must not be readable on the
local network.

## Stored Media Access

Playback endpoints for answering-machine videos, voice memos and Ring Capture
MP4 files intentionally allow every authenticated HA user. They do not apply
camera entity permissions or require an administrator. This shared-media policy
is separate from the service permissions above: playback does not authorize
recording, deletion or device control.

The integration's snapshot-image endpoint does check camera read permission.
The media-history metadata and playback endpoints use that same permission
decision and isolate entries. History clip links do not change permissions on
the existing shared Ring Capture endpoint or the standard HA media browser.
However, copies in HA's standard local-media directory follow HA media access
rules, independently of camera permissions. Neither hiding an entity nor
denying camera access protects the shared archive. Only provide HA access to
users trusted to access these recordings; see [PRIVACY.md](PRIVACY.md).

## Token Handling

Authenticated agent requests do not follow HTTP redirects, including redirects
to another path on the same origin. Connection changes are checked against the
entry's confirmed device identity; discovery identity adoption verifies the
saved endpoint instead of trusting an mDNS identifier alone.

`POST /api/v1/identity/proof` needs no authentication, so that Home Assistant
can follow the station to a new IPv4 address without sending the token there.
It reveals only the device id and an HMAC-SHA256, keyed with the API token,
over that id, the address and port the request arrived on, and a fresh nonce
from Home Assistant. It never returns the token, and the address binding means
a relay gets a proof for the station's address, not for its own. The route is
disabled while `api.noAuth` is on and for API tokens shorter than 32
characters, which a single proof would expose to offline guessing. See
[The station has a new address](docs/classe-300x/4-troubleshooting.md#the-station-has-a-new-address).

Home Assistant stores the configured agent token, maintenance token, webhook id,
and webhook secret in its config entry storage. The native agent stores its
local API token and maintenance token in its local JSON config unless the API
token is supplied through the `C300X_AGENT_TOKEN` environment variable.

The setup page and diagnostics only report whether tokens are configured. They
do not echo token values back.

Reconfigure and options forms never display saved access and maintenance keys;
an empty key field keeps the stored key. Changing keys:
[Keys and access](docs/classe-300x/5-update-and-removal.md#keys-and-access).

### RTSP Access

The agent enforces `video.rtsp.username` and `video.rtsp.password` when both
are configured. Partial credentials deny access; leaving both empty retains
unauthenticated RTSP for the normal local integration setup. API tokens do not
protect the RTSP port. Restrict that port to trusted clients with network rules.

RTSP Basic authentication does not encrypt credentials or media. External
clients must support the authentication challenge. Home Assistant's automatic
RTSP readiness probe and ring capture do not yet fully support these separate
credentials; configuring them manually can disable those integration features.
Do not treat an absolute credential-bearing stream URL as a complete workaround.

UDP talkback on port 40004 is accepted only from the IP address of a live,
played RTSP connection admitted by that policy, and only into an active protected
media session. Idle traffic is discarded, never relayed to the local audio port.
HA ring recording uses its same-host FFmpeg reader for this admission; packets
sent before PLAY or after disconnect are discarded. WebRTC uses the separate
RTSP backchannel. This IP binding is a trusted-LAN restriction, not per-packet
cryptographic authentication: a shared/NATed host or source-IP spoofing can defeat
it. Keep both ports restricted to trusted clients. A separate-host UDP sender
without its own played RTSP connection is not admitted.

## Legacy SSH Bootstrap

First installation and explicit SSH recovery use `asyncssh==2.24.1`. Home
Assistant installs it on demand; it is not a mandatory manifest requirement or
bundled Python package. The project does not import, request or pin Paramiko,
which addresses its advisory
[GHSA-r374-rxx8-8654 / CVE-2026-44405](https://github.com/advisories/GHSA-r374-rxx8-8654)
by removing that dependency, not by hiding the scanner result.

### LEGACY-SSH-001: RSA/SHA-1 During Bootstrap

- **Decision:** accepted device-protocol risk, reviewed 2026-11-07; owner:
  repository maintainer.
- **Scope:** only the explicit installer connection to a supported local C300X.
  RSA/SHA-1 host signatures and legacy key exchange/cipher fallbacks are enabled
  per connection. No global SSH configuration or library defaults are changed.
  A station whose SSH server offers an ECDSA or Ed25519 host key (as set up by
  some root tools), or signs its RSA host key with SHA-2 (rsa-sha2-512/256),
  is accepted as well; these are preferred over RSA/SHA-1 when offered.
- **Reason:** the device's SSH implementation needs legacy interoperability.
  Updating the client does not modernize the device protocol. Paramiko 5 removes
  the required RSA/SHA-1 support; AsyncSSH retains a configurable legacy path.
- **Host identity:** rooted devices can regenerate SSH host keys, so this
  one-shot installer does not enforce persistent host-key pinning. Use it only
  for a device you control on an isolated/trusted network.
- **Credentials:** the installer first tries the C300X factory root login,
  which is the same on every device and therefore no secret. It is built in
  encoded only so that it is not plain text in the code. A typed password, or
  a private key pasted into the form (with its passphrase), is used only when
  the device refuses that login, in process memory. No local key discovery,
  SSH agent, user SSH config, proxy or interactive terminal is used.
  Credentials and keys are not stored or logged by the integration.
- **Exposure:** temporary first installation or explicit SSH recovery.
  Normal operation and supported agent self-updates use the authenticated agent
  API and existing maintenance credentials, not SSH. Startup never silently
  invokes the installer. Disable SSH after bootstrap when practical.
- **Residual risk:** the connection is encrypted, but legacy cryptography and
  unverified host identity still permit on-path attacks. Network isolation is
  a mitigation, not proof of safety. This exception never permits internet exposure.
- **Review triggers:** changes to the client, negotiated algorithms, host-key
  handling, supported devices, or relevant advisories. A newly reported issue
  needs separate triage.

Repeated reports of this exact device-protocol limitation should reference
`LEGACY-SSH-001` instead of removing required interoperability or filing a
duplicate fix. New memory-safety, credential-leak, authentication-bypass or update
validation bugs are not covered. Do not dismiss findings based on a package name
or reporter. Leave Dependabot alerts and security-update PRs enabled; how
dependency updates are grouped and validated is described in
[Release Validation](docs/dev/release-validation.md).

## Accepted Local-Only Security Exceptions

The following narrowly scoped exceptions remain:

- Bootstrap host-key validation and legacy algorithms: see `LEGACY-SSH-001`
  above.
- CodeQL `cpp/cleartext-transmission`: the native MQTT bridge uses the device's
  local MQTT transport model. TLS is not available on this device-side path, so
  MQTT must stay on a trusted local network and must not be exposed externally.
- UDP device events: the native agent receives the device's OpenWebNet event
  frames on UDP port 7667 (multicast group 239.255.76.67). A capture on a C300X
  showed every frame sent by the device's own address, so the agent takes
  frames only from loopback or the device's own addresses and drops the rest.
  The frames themselves carry no authentication, so a host that can forge the
  device's source address on the local segment can still inject events. Keep
  the C300X on a trusted network segment.

These exceptions do not apply to internet-exposed deployments. Do not expose
SSH, MQTT, native-agent HTTP, RTSP, WebRTC, or Home Assistant callback surfaces
outside the trusted local network.

A newer SSH library must pass the legacy-device interoperability checks before
replacing the pin. An accepted exception is not evidence that a dependency has
no vulnerabilities; the release SBOM records the optional installer dependency
separately.

## Availability Limits

The agent and the integration bound their request buffers, queues, timeouts,
response sizes and media downloads and conversions. Excess load is rejected
instead of blocking the device or growing without limit, and failed or dropped
event deliveries are not reported as successful. Display actions are not
retried or queued, and a callback timeout is not proof that a physical action
did not run. These limits reduce resource-exhaustion risk but do not replace
authentication, network isolation or timely dependency review. The exact
limits are in [Architecture](docs/dev/architecture.md#resource-limits).

## Maintenance Surface

Maintenance endpoints are disabled unless explicitly enabled in agent config and
require the maintenance token. They are limited to fixed local actions such as
SSH state, reboot, firewall port block management, GUI reload, and QML patch
apply/restore. They do not accept arbitrary shell commands.

Writing `/api/v1/maintenance/auth` requires the existing maintenance token,
including when maintenance actions are disabled. The API token only permits
reading this endpoint. Token-free setup requires all three explicit bootstrap
flags: `api.noAuth`, `maintenance.enabled`, and `maintenance.allowNoAuth`.
Without an existing maintenance credential or that bootstrap configuration,
use explicit SSH recovery; an API token cannot create its own administrator.

## Reporting Issues

Please report security-related issues privately if possible, or through GitHub
issues without including tokens, private hosts, usernames, or device-specific
files:

https://github.com/memphi2/ha-bticino-c300x/issues
