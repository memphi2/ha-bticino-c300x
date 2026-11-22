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

### From 2.3.0 to 2.4.0

Install the integration, then run the agent update Repair. The packaged
**2.4.0 agent** installs the display file of the optional Energy page and
delivers visitor images in the configured size. Reapplying an active Display
patch restarts the GUI once. The **Forwarding** select now uses the states
`enabled`, `homeassistant` and `blocked`; change automations of your own that
compare or set the old English texts, and import a ring blueprint again if you
changed or imported your own copy.

### From 2.1.3 to 2.3.0

2.3.0 is the direct stable successor to 2.1.3. It includes the display,
configuration, media and reliability changes developed since 2.1.3, together
with visitor images. Do not install the withdrawn 2.2.0 as an intermediate step.
Keep your existing integration entry, cards and configured pages.

The packaged **2.3.0 agent** is required for visitor images and includes the
corrected display startup timer. Update it through Repair after installing the
integration; copying HA files alone does not update the device. **Save images**
defaults to on, with a 3-second delay and 14-day retention. Review that switch
and HA media permissions before leaving capture enabled.

### Update Steps

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

The PCMU silence-frame correction is part of the packaged agent; an
integration-only update is insufficient. It needs no firmware patch or GUI
change. For the validation scope, see
[PCMU reboot troubleshooting](media-troubleshooting.md#device-reboots-after-pcmu-on-demand-video).

## Beta Versions

Betas use versions such as `2.9.0b1`; release candidates use `2.9.0rc1`. A
beta uses the same integration, card and packaged agent as a stable release,
with no separate repository or second integration entry.

To install a published beta:

1. Back up Home Assistant and read the beta's release notes.
2. In Marketplace, enable this repository's **Pre-release** switch. In HACS,
   open **Redownload**, enable beta versions and select the beta.
3. Follow the normal [update steps](#updates), including the agent update
   Repair. Installing the integration alone does not update the agent.

Stable installations do not receive betas automatically. To leave the beta,
disable pre-releases and select the stable release, or wait for the next one,
then run the agent update Repair again. A Home Assistant backup does not
restore the agent on the device.

`2.9.0b1` is a beta for the display of firmware `3.0.6`, see
[Display patch on firmware 3.0.6](#display-patch-on-firmware-306). On `1.7.x`
and `2.0.2` it works like 2.8.1.

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
not stored by the integration. The installer first logs in with the C300X
factory root login, which is built in (encoded, not secret: it is the same on
every device). It asks for a login only when the device refuses that one.

Since 2.1.0 this path uses an on-demand AsyncSSH client instead of Paramiko.
It needs no SSH tools or add-on on the Home Assistant host. The device still
requires legacy SSH algorithms. The narrowly scoped
[accepted bootstrap risk](../SECURITY.md#legacy-ssh-001-rsasha-1-during-bootstrap)
does not apply to normal agent updates, which use the authenticated agent API.

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

### Display Patch on Firmware 3.0.6

Beta from `2.9.0b1`, not yet tested on a device. On `3.0.6` the display files
are built into the vendor display program, so the Display patch does not
change them on disk: the agent reads the files it changes out of that program,
patches them and keeps the result in its own folder, and the vendor start
script of the display gets a few lines that load them at the next start. The
display then has the same buttons and pages as on `1.7.x` and `2.0.2`. The
touch fix for lost taps is not part of it; it changes a Qt 4 library that
`3.0.6` does not have.

- **Turning it off:** switching the Display patch off removes the optional
  pages, but retains the core hooks. Removing the agent restores the vendor
  start script and removes the complete overlay.
- **When the display fails with the pages:** if the display ends with an error
  within a minute of a start with the pages, it is started again as shipped,
  and the Display patch status reads **applied, but the display started as
  shipped**. Updates and switching the optional pages off and on do not clear
  this quarantine. After investigating the error, an explicit full removal
  (`qml_patch.sh restore-all`) followed by an apply can retry it. Full removal
  also removes the core hooks; use the installer or Repair to apply them again.
- **Interrupted changes:** failed activation or restore rolls back the display
  resources, startup wrapper, preload library and quarantine state together.
  If rollback cannot finish, recovery files are retained and the overlay stays
  blocked. Do not delete recovery files or quarantine to force a GUI restart.
- **Confirmation:** installed files alone do not confirm activation. The
  installer rejects a quarantined or incomplete overlay; settings and update
  follow-up stay pending instead of accepting the stock fallback as success.
  An active overlay and a running process are still not proof that every QML
  page loaded correctly. Device checks remain required before merging this beta.
- **Returning to stable:** on 3.0.6, run the beta's `qml_patch.sh restore-all`
  and confirm `qt5_overlay: off` with the stock GUI running before replacing
  the agent with stable 2.8.2. That release has no Qt 5 overlay recovery code;
  switching off just the optional pages is not a complete removal.
- **What to report:** the Display patch status, the integration diagnostics
  and, if you can reach the device, `/tmp/c300x-display-qt5.log` (the display's
  error output, at most 64 KB, cleared by a restart of the device).

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
a trusted certificate matching the URL hostname. Check the device clock and DNS as well.

Avoid:

- `homeassistant.local`,
- loopback addresses,
- unspecified addresses,
- link-local IPv6 without explicit scope,
- public or remote-only URLs.

If Home Assistant generates an unsuitable URL, set **Address of Home Assistant for the
C300X (optional)** in setup or under **Connection to the C300X** in the options. Enter the HTTP or HTTPS base URL, for
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
restarting releases the TLS libraries. Certificate failures never fall back to
unencrypted HTTP.

## Remove Home Assistant Integration

Removing an HA entry, removing the downloaded integration, and uninstalling the
native device agent are **separate operations**. None is required for a normal
update. Do not select **Remove device agent** just to remove an HA entry or fix
a dashboard. Deleting the HA entry does not uninstall the device agent or
restore persistent C300X settings.

1. Make a Home Assistant backup before removing configuration. Export any visitor
   images or Ring Captures you want to keep, and check whether your backup
   actually includes their media storage. External media and device files may
   need separate backups; an HA backup is not a C300X firmware/config backup.
   Follow the [official backup guide](https://www.home-assistant.io/common-tasks/general/backups/).
2. Stop viewing/recording sessions and disable or adapt automations that use this
   C300X. Decide separately whether the device agent should remain installed.
   If you explicitly intend to uninstall it too, read [Remove Agent](#remove-agent)
   and complete that operation while its HA maintenance entity is still present.
   Otherwise leave the device installation alone.
3. Open **Settings > Devices & services**, select **BTicino C300X**, and choose
   the three-dot menu of the intended entry, then **Delete** and confirm. Check
   the entry name when several C300X devices are configured. This removes that
   entry's HA configuration, devices and entities; the integration releases its
   runtime listeners/tasks and clears its Repair issues. Follow any HA restart
   prompt. See the [official entry-removal steps](https://www.home-assistant.io/common-tasks/general/#removing-an-integration-instance).
4. Remove broken card references, dashboard views and automations manually, or
   point them at another device deliberately. Imported blueprints and automations
   are not automatically removed. Keep the integration package while another
   C300X entry still uses it.
5. Only when no C300X entries need the package, uninstall the downloaded custom
   integration through the method used to install it:

   - **Marketplace (HA 2026.11+):** open **Settings > Marketplace**, the BTicino
     C300X repository, then its three-dot menu and **Uninstall**. Confirm and
     follow the restart prompt. If entries still exist, the dialog offers
     **View integration** or **Delete and uninstall**; use the combined action
     only when deletion of those entries is intended. [Official Marketplace instructions](https://www.home-assistant.io/integrations/marketplace/#uninstalling-a-repository).
   - **HACS:** open the downloaded BTicino C300X repository's three-dot menu and
     select **Remove**, then restart Home Assistant as requested. This removes
     downloaded code, not all related data. [Official HACS instructions](https://www.hacs.xyz/docs/use/repositories/dashboard/#removing-a-repository).
   - **Manual installation:** after deleting all C300X entries, stop HA and
     remove only `custom_components/bticino_c300x` from its configuration
     directory, then start HA again. Do not remove the whole `custom_components`
     directory or manually edit HA's config-entry registry.

### Data That Can Remain

- **Device installation:** if you did not explicitly uninstall the agent, its
  files, tokens/config, startup integration, patches and device-file backups
  remain. The device may still try its old HA callbacks; deleting an HA entry
  is not credential revocation or a device reset. Reconfiguring or removing
  those device settings is a separate, deliberate maintenance operation.
- **Saved media:** visitor images remain under
  `<HA media root>/c300x/snapshots/<device-directory>/`; Ring Capture recordings
  and metadata remain under the `c300x` media area or a chosen export location.
  Snapshot retention stops for an unloaded/removed entry. Re-adding the device
  creates a new entry ID and does not adopt that old snapshot directory.
  Review/export these files and delete only the identified device's data if you
  want it erased; never delete a shared media root wholesale.
- **HA-local settings and UI:** the snapshot switch's private storage record
  `.storage/bticino_c300x.snapshots.<entry_id>` can remain, as can downloaded
  blueprints, dashboard/card resources, customized automations and HA history.
  Clean up user-facing references through HA first. Do not edit `.storage` while
  HA is running; any manual cleanup needs a backup and positive identification
  of the removed entry. Package removal is not a historical-data purge.
- **Backups and copies:** old HA backups, device backups and exported recordings
  may still contain credentials, configuration or personal media. Decide their
  retention separately. Removing live files does not erase older backup copies;
  keep backups private, and do not discard the only recovery copy prematurely.

HA/HACS UI sources checked on **2026-11-16**. Removal behavior was checked against
`__init__.py:async_remove_entry`, `runtime_manager.py`, `events.py`,
`snapshots.py` and `snapshot_store.py`; no removal operation was performed.

## Remove Agent

Use the **Remove device agent** maintenance button only when uninstalling or
recovering the C300X. The flow removes agent-owned files and supported patch
state. It should not be part of normal update work.

This is an explicit **device-writing, rebooting operation**, not the HA-entry
Delete action. Arrange a maintenance window with no active call or recording,
preserve needed configuration/media and recovery backups first, then enable/use
the maintenance entity only if you intend this removal. Keep the HA entry until
the device operation reports its outcome; do not repeatedly retry an uncertain
result or manually delete recovery files.

The current removal script restores supported QML, firewall and media patches,
removes startup files and the agent directory (including `config.json`), and on
success also removes its managed device-file backup root before scheduling a
device reboot. It starts SSH for recovery. On restoration failure it reports an
error and retains agent files/backups; this is not a promise that every earlier
step was rolled back. Only a display library without a valid stock backup does
not stop it: the library keeps the wider tap tolerance. It is not a factory reset and does not erase HA media or
HA backups. Review any remaining device users/settings separately; never assume
all device credentials or unrelated firmware configuration were reset.

Source: [`native_agent/scripts/remove_agent.sh`](../native_agent/scripts/remove_agent.sh).

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
