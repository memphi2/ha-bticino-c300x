# Maintenance and Removal

Every device-changing action is explicit; Home Assistant startup never
patches, reboots or removes anything on the station. This page applies to the
Classe 300X (C300X) and the Classe 100X (C100X); model differences are named
where they occur. Keep real keys, device
configs, logs and captures out of issues and commits.

## Device Agent

The native device agent runs on the C300X and serves the authenticated
`/api/v1` API that Home Assistant uses. The setup flow and Repairs install it
on a rooted, SSH-enabled station, update it ([Update](quickstart.md#update)),
recreate its startup link after a device reboot and remove it
([Remove Agent](#remove-agent)).

Updating only the integration does not change the device. The agent-update
Repair installs the agent and its display files together through the agent API
and the saved maintenance key.

One package updates both models. A C100X agent takes only a package that
declares itself C100X-compatible: Home Assistant refuses any other before the
upload, and the C100X agent's own updater refuses it as well.

When the station gets a new IPv4 address, the agent announces itself again and
Home Assistant follows it once the station has proved that it holds the access
key. Limits and the cases that need **Reconfigure**:
[Station Changed Its Address](media-troubleshooting.md#station-changed-its-address).

### Firewall

Use the firewall Repair when Media Readiness reports missing IPv4 media ports
or talkback RTP readiness. Enable IPv6 firewall support only when Home
Assistant reaches the C300X over stable IPv6. Stations without an IPv6
firewall script, such as firmware 3.0.6, have no IPv6 firewall switch.

### Core GUI Hook

Separate from the optional display pages, the core GUI hook tracks media
session state and keeps ringer mute/unmute in step with the GUI's saved audio
state. Repairs applies it when required; reload the C300X GUI afterwards.
Without a responding GUI, ringer commands fail instead of changing only the LED.
The C100X has no core GUI hook: its ringer mute and touch tone come with the
[display activation](display.md#classe-100x-activation-by-reboot).

### Display Patch

The optional Display patch writes the files for the
[station display pages](display.md#enable-the-display-pages) and reloads the
device UI, which can take about a minute. Use Repairs instead of editing device
files. The Display patch is for the C300X; the C100X display pages use the
[activation by reboot](display.md#classe-100x-activation-by-reboot), with the
**Activate display pages** and **Restore original display** buttons.

On firmware 3.0.6 the display program loads the patched pages at its start;
its files are not changed. Read
[Display Patch on Firmware 3.0.6](display.md#display-patch-on-firmware-306)
before going back to a release older than 2.10.0.

### Home Assistant Media User

Doorbell video, Ring Call and Home Call use the dedicated `homeassistant` media
user that setup or Repair creates. Run the Repair when Readiness reports
`homeassistant_user`, `device_routing`, or media-user label or route
inconsistencies. To remove the user, use the C300X display's user management,
then run setup or Repair again if media features are still enabled.

On a C100X the media user is set up the same way, in test. Setup refuses a
station whose active SIP route is not one of the stock route files, for
example one changed by BTicino Companion (`unsupported_active_route`), and
writes nothing then. Turning the **Home Assistant media user** switch off
restores the stock routing program from its backup; the added user lines
stay.

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
- **Lost keys:** an access key cannot create a maintenance key. Without a
  working maintenance key or the noAuth bootstrap configuration, recovery needs
  SSH: tick **I do not have the keys: reinstall the agent** in the
  re-authentication dialog, or in the key dialog of a new setup. Home Assistant
  logs in with the factory login (it asks for the SSH user and password only if
  the station refuses it, and does not store them), stops the installed agent,
  writes the bundled agent with two newly generated keys and starts it again.
  The entry stores the new keys; the old ones stop working. Display pages, the
  core media hook and the other settings on the station stay, and the station
  is not restarted. See [Agent already installed](quickstart.md#install-the-device-agent).

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
built-in factory root login (not secret: the same on every device of a model)
and asks for an SSH user and password only when the device refuses it. While
the model is unknown it tries the C300X login and then, only after the station
refused it, the C100X login. The C100X factory login was checked against the
original 1.5.8 firmware, not on a device; a changed password needs your own
login. Every SSH install (setup, reinstall, Repair) first checks for the
folder `/home/bticino` and refuses a host without it as not a BTicino
station, before anything is written. SSH
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
- **Update cut off (power loss, crash):** the agent rolls back reported apply
  errors itself. An update cut off before it finished leaves
  `<file>.update-backup` files next to the agent files, the init script and the
  init link; the next agent update clears them before it starts. When the
  installed files match the installed bundle, that update had finished and
  only the leftovers are removed; otherwise each backup is moved back first.
  Run the agent-update Repair again; no SSH step is needed.
- **Display patch write interrupted (power loss, crash, forced stop):** the
  agent finishes it itself, at its next start and before the next Display
  patch write: the display files from before the write are put back, `/` goes
  read-only again and the display restarts. Diagnostics show the Display patch
  status `transaction`: `pending` until then, `recovered` after it.
  If it reports `stuck` (Repairs shows "C300X display write left unfinished"),
  the display files were left as they are and the files from before the write
  stay in the hidden folder `.c300x-qml-transaction.<number>` in
  `/home/bticino/bin/gui/skins/default`. Check the display, then apply the
  Display patch again, which rebuilds every display file from the stock
  backups; if the warning stays, reboot the device so that the agent tries
  again. A leftover of agent 2.9.0 or older is restored only when every file
  in it is proven complete and no later write has replaced the display files
  (then it is only removed), otherwise never: once the display works, delete
  that folder over SSH.
- **Camera size back from 960x576 reports missing or invalid backup data:** keep
  the recovery files and resolve the error before retrying; never guess the
  original file.
- **C100X display pages rolled back or boot check failed (Repairs):** see
  [Classe 100X Display Pages](media-troubleshooting.md#classe-100x-display-pages).
  The backups of the original display stay on the station in both cases.

When agent removal fails:

| Removal reports | What to do |
| --- | --- |
| The agent could not be stopped | Nothing was restored or deleted; the agent keeps running or is started again. |
| Failed to restore a display, firewall or media patch | Agent files, startup entries and backups are kept; the agent is started again. Resolve the reported error, then retry removal. |
| Read-only remount failed, startup entries restored | Agent and backups are kept; no reboot is requested. Reboot the device fully, then retry removal. |
| Startup rollback failed | Restore the startup entries from the reported recovery location before rebooting. Do not delete them or force removal. |
| Deletion failed partway | Startup stays disabled; no reboot is requested. Keep the recovery directory and device backups, repair the agent installation, restore its startup entries, then reboot. |

When a removal stopped the agent and then gives up before its final deletion,
it restarts the agent and checks that it runs, so Home Assistant can reach the
station and retry; the message says "Agent started again so the removal can be
retried", or names the init script's `restart` command to run over SSH. After a
failed startup rollback or a deletion that had started, the agent stays
stopped.

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

The current removal script restores supported QML and media patches,
including the stock routing program the Home Assistant media user changed,
strips the agent's IPv4 and IPv6 rule blocks from the live firewall scripts and
keeps the rest of them (a backup only recreates a missing script), removes
startup files and the agent directory (including `config.json`), and on
success also removes its managed device-file backup root before scheduling a
device reboot. It starts SSH for recovery. On restoration failure it reports an
error, retains agent files/backups and starts the agent again; this is not a
promise that every earlier step was rolled back. Only a display library without a valid stock backup does
not stop it: the library keeps the wider tap tolerance. It is not a factory reset and does not erase HA media or
HA backups. Review any remaining device users/settings separately; never assume
all device credentials or unrelated firmware configuration were reset.

On a C100X, removal first checks that the display files are the original ones,
or restores them from their verified backups and checks the result, and
restores the stock routing program; unknown changes or damaged backups stop
the removal before anything is deleted and without a reboot. Removal on a
C100X is in test.

Source: [`native_agent/scripts/remove_agent.sh`](../native_agent/scripts/remove_agent.sh).
