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

## Updates

1. Install the integration update offered by Marketplace or HACS and follow any
   Home Assistant restart request.
2. Run the device-agent update Repair if offered. Supported self-updates use the
   existing maintenance credentials; SSH is needed for first install or recovery.
3. Apply or update the core GUI hook when Repairs requests it, then reload the
   C300X GUI. Updating only the integration does not update device-side behavior.
4. Run the C300X Lovelace card Repair if offered. Hard-reload the browser if the
   card still shows old frontend state.
5. Check **Media readiness** before testing video and calls.

Keep existing integration entries when updating. The integration archive includes
the agent, its GUI components and the Lovelace card; no separate card repository
is needed.

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

## Core GUI Hook

The core GUI hook is separate from the optional display dashboard. It tracks
media session state and synchronizes ringer mute/unmute with the GUI's saved
audio state. The integration's Repair flow applies it when required.

Use the matching agent and core GUI files, then reload the C300X GUI to activate
changes. Ringer commands require GUI confirmation and device readback; a missing
or unresponsive GUI returns an error rather than changing only the LED/device
value. Optional Alarmo, weather and Home Assistant display pages are not required.

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

This setting controls the C300X-to-Home Assistant connection for events and
display callbacks. It is independent of the browser's frontend URL: using HTTPS
for browser microphone access does not require HTTPS callbacks on the C300X.

Callbacks must use an HTTP or HTTPS URL that the C300X can reach directly.
HTTPS must be explicitly selected in the callback base URL override. It requires
an updated agent advertising `https_callbacks_configurable` and a trusted
certificate matching the URL hostname. Check the device clock and DNS as well.

Avoid:

- `homeassistant.local`,
- loopback addresses,
- unspecified addresses,
- link-local IPv6 without explicit scope,
- public or remote-only URLs.

If Home Assistant generates an unsuitable URL, set **Local Home Assistant
callback base URL** in setup/options. Enter the HTTP or HTTPS base URL, for
example:

```text
http://192.0.2.10:8123
https://ha.example.com:8123
```

Home Assistant keeps the generated webhook path and token.

An empty override keeps the existing behavior and does not opt in to HTTPS.
An `http://` override keeps the device on its lightweight HTTP transport, including
when the browser uses an HTTPS reverse proxy in front of HA. An `https://` override
enables TLS for both event subscriptions and display callbacks and adds TLS work
on the C300X. The hostname must match the server certificate; it is not replaced
with an IP address.

Changing HTTP/HTTPS modes writes the internal agent setting only when it changes
and requires one agent restart. The device and GUI are not rebooted. The agent
defers the restart while a call, stream or media teardown is active; HA retries
using its existing callback registration mechanism. Switching back to HTTP and
restarting releases the TLS libraries. Old agents continue to support HTTP;
update the agent before selecting HTTPS. Certificate failures never fall back to
unencrypted HTTP.

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
