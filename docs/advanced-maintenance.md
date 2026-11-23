# Maintenance and Removal

Every device-changing action is explicit; Home Assistant startup never
patches, reboots or removes anything on the C300X. Keep real keys, device
configs, logs and captures out of issues and commits.

## Device Agent

The native device agent runs on the C300X and serves the authenticated
`/api/v1` API that Home Assistant uses. The setup flow and Repairs install it
on a rooted, SSH-enabled C300X, update it ([Update](quickstart.md#update)),
recreate its startup link after a device reboot and remove it
([Remove Agent](#remove-agent)).

Updating only the integration does not change the device. The agent-update
Repair installs the agent and its display files together through the agent API
and the saved maintenance key.

When the station gets a new IPv4 address, the agent announces itself again and
Home Assistant follows it once the station has proved that it holds the access
key. Limits and the cases that need **Reconfigure**:
[Station Changed Its Address](media-troubleshooting.md#station-changed-its-address).

### Firewall

Use the firewall Repair when Media Readiness reports missing IPv4 media ports
or talkback RTP readiness. Enable IPv6 firewall support only when Home
Assistant reaches the C300X over stable IPv6.

### Core GUI Hook

Separate from the optional display pages, the core GUI hook tracks media
session state and keeps ringer mute/unmute in step with the GUI's saved audio
state. Repairs applies it when required; reload the C300X GUI afterwards.
Without a responding GUI, ringer commands fail instead of changing only the LED.

### Display Patch

The optional Display patch writes the files for the
[station display pages](display.md#enable-the-display-pages) and reloads the
device UI, which can take about a minute. Use Repairs instead of editing device
files.

### Home Assistant Media User

Doorbell video, Ring Call and Home Call use the dedicated `homeassistant` media
user that setup or Repair creates. Run the Repair when Readiness reports
`homeassistant_user`, `device_routing`, or media-user label or route
inconsistencies. To remove the user, use the C300X display's user management,
then run setup or Repair again if media features are still enabled.

## Tokens and Access

Installer-based setup generates an **access key** (API token) and a separate
**maintenance key**. The C300X stores them in
`/home/bticino/cfg/extra/c300x-native-agent/config.json`; Home Assistant keeps
its own copy in the config entry. The agent setup page shows only whether a key
is set and its fingerprint, diagnostics only whether it is set. Policy:
[Token Handling](../SECURITY.md#token-handling).

- **Change a key:** **Reconfigure** or **Configure > Connection to the C300X**.
  An empty key field keeps the saved key; a value replaces it. These forms
  cannot remove a saved maintenance key.
- **Key rejected:** Home Assistant starts a re-authentication flow that asks
  for the current keys.
- **Webhook credentials:** **Reconfigure > Rotate shared secret**.
- **Lost maintenance key:** an access key cannot create one. Without a working
  maintenance key or the noAuth bootstrap configuration, recovery needs SSH.

`noAuth` is a bootstrap state; turn it off once keys are configured. Saving the
agent's `/setup` page with an access key set, or turning off the
**Agent noAuth** switch, turns off both `api.noAuth` and noAuth maintenance
access. The maintenance entities **SSH**, **Agent noAuth**, **Agent noAuth
maintenance** and **Remove device agent** are disabled by default; use them
only for a recovery step and switch SSH and noAuth off again afterwards. Leave
**Agent mDNS discovery** on, or Home Assistant cannot find the station at a new
address.

### SSH

SSH is used only for the first installation and explicit recovery; normal agent
updates use the authenticated agent API. The installer first tries the
built-in C300X factory root login (not secret: the same on every device) and
asks for an SSH user and password only when the device refuses it. SSH
credentials are not stored. Home Assistant installs the AsyncSSH client on
demand; its host needs no SSH tools or add-on. The device still requires
legacy SSH algorithms, an accepted risk documented as
[LEGACY-SSH-001](../SECURITY.md#legacy-ssh-001-rsasha-1-during-bootstrap).

## Callback URL

The address the C300X uses to reach Home Assistant for events and display
callbacks. It is independent of the browser's frontend URL, so HTTPS for the
browser microphone does not need HTTPS callbacks.

The URL must be reachable from the C300X directly. Avoid `homeassistant.local`
and other `.local` names, loopback, unspecified and link-local addresses, and
public or remote-only URLs. For an `http://` URL, Home Assistant replaces a
`.local`, loopback or link-local host with its own address on the route to the
C300X. When the URL still cannot work, Repairs shows **C300X callback URL is
not usable by the device agent** with a suggested value.

To set it yourself, enter a base URL in **Address of Home Assistant for the
C300X (optional)** in setup or under **Configure > Connection to the C300X**,
for example `http://192.0.2.10:8123` or `https://ha.example.com:8123`. Home
Assistant keeps the generated webhook path and token.

| Address field | Transport |
| --- | --- |
| Empty | The address Home Assistant knows for itself; no HTTPS. |
| `http://` | Lightweight HTTP, also when browsers use an HTTPS reverse proxy in front of Home Assistant. |
| `https://` | TLS for events and display callbacks; adds TLS work on the C300X. |

HTTPS needs a trusted certificate matching the hostname, a correct device clock
and working DNS. The hostname is never replaced with an IP address, and a
certificate failure never falls back to unencrypted HTTP. Switching between
HTTP and HTTPS restarts only the agent, not the device or its GUI, and waits
while a call, stream or media teardown is active. Home Assistant itself still
reaches the agent over plain local HTTP.

## Recovery

Recovery steps write to the device. Use a window with no active call or
recording, and keep every recovery file or directory a message names until the
step is complete.

- **Agent does not start after reboot (Repair):** the startup link is missing
  or invalid. Run the agent-update Repair, or reinstall over SSH.
- **Update refused after an interrupted update:** the agent rolls back reported
  apply errors itself, but not an update cut off by a power loss. Over SSH,
  look for `<file>.update-backup` files next to the agent files, the init script
  and the init link; each is the file as it was before the update. If the installed
  file next to it works, delete the backup; if it is missing or broken, move
  the backup over it first.
- **Camera size back from 960x576 reports missing or invalid backup data:** keep
  the recovery files and resolve the error before retrying; never guess the
  original file.

When agent removal fails:

| Removal reports | What to do |
| --- | --- |
| The agent could not be stopped | Nothing was restored or deleted. |
| Read-only remount failed, startup entries restored | Agent and backups are kept; no reboot is requested. Reboot the device fully, then retry removal. |
| Startup rollback failed | Restore the startup entries from the reported recovery location before rebooting. Do not delete them or force removal. |
| Deletion failed partway | Startup stays disabled; no reboot is requested. Keep the recovery directory and device backups, repair the agent installation, restore its startup entries, then reboot. |

The recovery directory holds startup entries and an identity manifest, not
copies of deleted agent files. A successful removal requests a reboot; the
request does not confirm that the device has restarted.

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
