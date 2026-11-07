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

## Home Assistant Service Permissions

Calls with a Home Assistant user context are checked before sending device
commands. Door, configured stair-light and activation services require control
permission for the corresponding enabled entity; media services use the camera
entity. Alarm commands require permission for the configured alarm entity.
Configured HA actions retain the original user context and the target service's
permission checks.

Maintenance, arbitrary stair-light addresses, capture/analysis, display
notification management and stored-message services require an administrator.
Context-free HA automations remain trusted. The physical display uses its
separate authenticated bridge and configured action allowlist, not HA user
impersonation.

## Token Handling

Home Assistant stores the configured agent token, maintenance token, webhook id,
and webhook secret in its config entry storage. The native agent stores its
local API token and maintenance token in its local JSON config unless the API
token is supplied through the `C300X_AGENT_TOKEN` environment variable.

The setup page and diagnostics only report whether tokens are configured. They
do not echo token values back.

## Legacy SSH Bootstrap

From 2.1.0b2, first installation and explicit SSH recovery use
`asyncssh==2.24.1`. Home Assistant installs it on demand; it is not a mandatory
manifest requirement or bundled Python package. Paramiko is no longer imported,
requested or pinned by this project. Its former advisory
[GHSA-r374-rxx8-8654 / CVE-2026-44405](https://github.com/advisories/GHSA-r374-rxx8-8654)
is addressed by removing that dependency, not by hiding the scanner result.
Older releases keep their original dependency and limitations.

### LEGACY-SSH-001: RSA/SHA-1 During Bootstrap

- **Decision:** accepted device-protocol risk, reviewed 2026-11-07; owner:
  repository maintainer.
- **Scope:** only the explicit installer connection to a supported local C300X.
  RSA/SHA-1 host signatures and legacy key exchange/cipher fallbacks are enabled
  per connection. No global SSH configuration or library defaults are changed.
- **Reason:** the device's SSH implementation needs legacy interoperability.
  Updating the client does not modernize the device protocol. Paramiko 5 removes
  the required RSA/SHA-1 support; AsyncSSH retains a configurable legacy path.
- **Host identity:** rooted devices can regenerate SSH host keys, so this
  one-shot installer does not enforce persistent host-key pinning. Use it only
  for a device you control on an isolated/trusted network.
- **Credentials:** only the supplied password is used, in process memory.
  No local key discovery, SSH agent, user SSH config, proxy or interactive
  terminal is used. Credentials are not stored by the integration.
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
or reporter. Leave Dependabot alerts and security-update PRs enabled.

## Dependency Update Coverage

Normal GitHub Actions and Python tool updates are grouped quarterly, with at
most one open version-update PR per ecosystem. Python major-version changes
remain manual compatibility work. The groups explicitly apply only to version
updates: security-update PRs do not wait for the quarterly schedule and use
GitHub's separate security PR limit.

The HA versions used in CI live in separate
`requirements/ha-min/requirements.txt` and
`requirements/ha-current/requirements.txt` manifests. Validate and Release
install those exact manifests together with their corresponding direct tool
pins. Neither HA target is excluded from its Dependabot entry. Routine HA
version updates remain manual; `open-pull-requests-limit: 0` does not disable
security-update PRs.

Dependabot alerts and automatic security-update PRs must be enabled in the
repository settings. A local configuration change cannot enable those settings.
Alerts, security-update PRs and normal version-update schedules are distinct;
an ignored update version does not suppress the advisory itself.

There is no longer a package-specific SSH dependency ignore range. AsyncSSH
updates follow the normal policy and require legacy-device compatibility tests.
The minimum-HA **tool** file is maintained manually and excluded
from automatic updates; that exception does not cover the minimum HA manifest.

`requirements-dev.txt` and `requirements-dev-min-ha.txt` contain direct tools,
not generated transitive lockfiles. Do not restore a matching `.in` file:
Dependabot would treat the pair as pip-compile input/output and regenerate the
transitive pins. `scripts/check_dependency_updates.py` checks parsed YAML,
manifest contents and CI wiring, including forbidden coverage restrictions.
Security PRs are not auto-merged; align `project-versions.json` and compatibility
metadata with a changed HA pin and pass both validation targets before merging.

See the [Dependabot configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

## Accepted Local-Only Security Exceptions

The following narrowly scoped exceptions remain:

- Bootstrap host-key validation and legacy algorithms: see `LEGACY-SSH-001`
  above. The former Paramiko-specific source suppression has been removed
  together with that client; the device-side limitation remains explicit.
- CodeQL `cpp/cleartext-transmission`: the native MQTT bridge uses the device's
  local MQTT transport model. TLS is not available on this device-side path, so
  MQTT must stay on a trusted local network and must not be exposed externally.

These exceptions do not apply to internet-exposed deployments. Do not expose
SSH, MQTT, native-agent HTTP, RTSP, WebRTC, or Home Assistant callback surfaces
outside the trusted local network.

Reassess the SSH exception when changing the installer, its dependency pin, or
device compatibility, and whenever a relevant advisory appears. A newer library
must pass the legacy-device interoperability checks before replacing the pin.
An accepted exception is not evidence that a dependency has no vulnerabilities;
the release SBOM records the optional installer dependency separately.

## Availability Limits

Incoming HTTP requests have bounded buffers, a total receive deadline and a
bounded pending-client pool. Event delivery has one worker and a bounded queue;
overflow and failed delivery are not reported as successful callbacks. Home
Assistant media downloads, conversions and cache retention have explicit limits.
Display forwarding uses a separate worker with at most one outstanding request,
leaving the HTTP loop available for nested HA commands. It does not retry or
queue additional physical actions. A callback timeout is not proof that a
downstream physical action did not execute.
These controls reduce resource-exhaustion risk but do not replace authentication,
network isolation, or timely dependency review. They add no persistent packet
capture or additional device polling.

## Maintenance Surface

Maintenance endpoints are disabled unless explicitly enabled in agent config and
require the maintenance token. They are limited to fixed local actions such as
SSH state, reboot, firewall port block management, GUI reload, and QML patch
apply/restore. They do not accept arbitrary shell commands.

## Reporting Issues

Please report security-related issues privately if possible, or through GitHub
issues without including tokens, private hosts, usernames, or device-specific
files:

https://github.com/memphi2/ha-bticino-c300x/issues
