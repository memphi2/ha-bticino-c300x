# Advanced Maintenance

This page is for recovery, maintenance and device-changing actions. Normal
daily use should not need it.

## Maintenance Rules

- Device-changing actions are explicit.
- Home Assistant startup must not silently patch, reboot or remove anything.
- Keep SSH and noAuth bootstrap access disabled unless you are actively using
  them.
- Keep real tokens, device configs, logs and captures out of issues and commits.

## Device Agent

The native C300X device agent runs locally on the C300X and exposes the
authenticated `/api/v1` API used by Home Assistant.

Use the Home Assistant setup or Repair flow to:

- install the packaged agent on an already rooted/SSH-enabled C300X,
- update an older packaged agent,
- repair startup after a device reboot,
- remove the agent when uninstalling.

The installer deploys project-owned files only. It does not contain vendor
firmware, extracted firmware files, APKs or third-party controller code.

## Tokens

Installer-based setup generates:

- an API bearer token,
- a separate maintenance token.

The C300X stores them in:

```text
/home/bticino/cfg/extra/c300x-native-agent/config.json
```

Home Assistant stores its own copy in the config entry/options and uses it
automatically. Do not paste token values into logs, screenshots, issues,
commits or documentation.

The agent setup page shows token state and fingerprints only. It does not reveal
existing token values.

## SSH and noAuth

SSH credentials are used only for explicit install or recovery steps. They are
not stored by the integration.

`noAuth` is a bootstrap state. Disable it after tokens are configured. The
maintenance switch entities are for temporary recovery, not normal operation.

## Firewall

Use the firewall Repair when Media Readiness reports missing IPv4 media ports or
talkback RTP readiness.

IPv6 firewall support is optional. Enable it only when your Home Assistant host
uses stable IPv6 to reach the C300X.

## Display Patch

The Display patch is optional. Enable it only if you want C300X display pages
for Alarmo, weather or selected Home Assistant entities.

The Display patch writes display files on the C300X and reloads the device UI.
The operation can take up to about a minute. Use the integration status and
Repairs instead of manually editing device files.

The core media hook is separate from the optional display dashboard. It is used
for media session state tracking and is handled by the integration/Repair flow
when required.

## Home Assistant Media User

Doorbell video, Ring Call and Home Call use a local C300X media identity. The
recommended setup is the dedicated `homeassistant` media user created by the
Repair or setup flow.

Use the Repair when Readiness reports:

- `homeassistant_user`,
- `device_routing`,
- media-user label or route inconsistencies.

To remove the user manually, use the C300X display/user management UI, then run
setup or Repair again if media features are still enabled.

## Device Activations

Additional device activations are configured in setup, options or reconfigure.
Normal users should use the structured forms, not raw JSON.

Automatic mode leaves the built-in stair-light action alone. Manual mode
generates one `stair_light` activation from P/N address parts and reserves that
id, so up to 15 more user activations can be added.

The integration syncs activation config to the native agent after saving only
when the desired activation list differs from the agent state. It should not
write activation config during normal Home Assistant startup when nothing
changed.

## Callback URL

Callbacks must use a local HTTP URL that the C300X can reach directly.

Avoid:

- `homeassistant.local`,
- loopback addresses,
- unspecified addresses,
- link-local IPv6 without explicit scope,
- public or remote-only URLs.

If Home Assistant generates an unsuitable URL, set **Local Home Assistant
callback base URL** in setup/options. Use only the local HTTP base URL, for
example:

```text
http://192.0.2.10:8123
```

Home Assistant keeps the generated webhook path and token.

## Remove Agent

Use the **Remove device agent** maintenance button only when uninstalling or
recovering the C300X. The flow removes agent-owned files and supported patch
state. It should not be part of normal update work.

## Developer Checks

For repository validation:

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/python scripts/check_coverage.py
.venv/bin/python scripts/check_typing.py
.venv/bin/ruff check .
.venv/bin/python -m pytest
make -C native_agent check
```

For native-agent details, see [native-agent.md](native-agent.md).
