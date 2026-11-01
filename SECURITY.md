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

## Token Handling

Home Assistant stores the configured agent token, maintenance token, webhook id,
and webhook secret in its config entry storage. The native agent stores its
local API token and maintenance token in its local JSON config unless the API
token is supplied through the `C300X_AGENT_TOKEN` environment variable.

The setup page and diagnostics only report whether tokens are configured. They
do not echo token values back.

## Legacy SSH Installer Dependency

The Home Assistant package pins `paramiko==3.5.1` for the optional first-install
and fallback repair path because the C300X SSH server needs legacy SSH
compatibility. Normal C300X agent operation does not use Paramiko after the
native agent is installed; it communicates through the local token-protected
agent API.

Security scanners may flag Paramiko for SHA-1/RSA-key handling
(`CVE-2026-44405`). Keep SSH and the native-agent installer on a trusted local
network, use the installer only for rooted/SSH-enabled devices you control, and
disable SSH again after bootstrap when your maintenance model allows it.

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

The `paramiko >=4` ignore range remains a deliberate legacy SSH exception:
a fix available only there needs manual security triage and device compatibility
testing. The minimum-HA **tool** file is also maintained manually and excluded
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

The following scanner findings are documented and intentionally suppressed in
source:

- CodeQL `py/paramiko-missing-host-key-validation`: the rooted C300X can
  regenerate its SSH host key after reboot, so stable host-key pinning would
  make the local bootstrap/repair installer unreliable. The Paramiko path is
  optional, pinned to `paramiko==3.5.1`, and used only for trusted local devices
  during install or repair.
- CodeQL `cpp/cleartext-transmission`: the native MQTT bridge uses the device's
  local MQTT transport model. TLS is not available on this device-side path, so
  MQTT must stay on a trusted local network and must not be exposed externally.

These exceptions do not apply to internet-exposed deployments. Do not expose
SSH, MQTT, native-agent HTTP, RTSP, WebRTC, or Home Assistant callback surfaces
outside the trusted local network.

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
