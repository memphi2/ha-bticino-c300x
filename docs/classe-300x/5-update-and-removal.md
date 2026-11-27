# Classe 300X: Update and Removal

**Step 5 of 5:** [1. Setup](1-setup.md) | [2. Use](2-use.md) | [3. Station display](3-display.md) |
[4. Troubleshooting](4-troubleshooting.md) | **5. Update and removal**

This page explains how to update, how to handle the agent's keys and how to
remove the integration and the device agent.

## Update

1. Install the update offered by Marketplace or HACS. Restart Home Assistant
   if it asks you to.
2. Open **Settings > Repairs** and run **C300X device agent update
   required**. It updates the agent and its display files with the saved
   maintenance key; no SSH is needed.
3. If Repairs offers **C300X core media hook is missing**, run it, then press
   **Reload device display**.
4. If Repairs offers **Add the C300X Lovelace card**, run it. If the card
   still looks old, reload the browser page without cache.
5. Check **Media readiness**.

Updating the integration alone does not change the station: always run the
agent update Repair.

### Beta Versions

Betas are versions like `3.0.0b3`. They are opt-in.

1. Make a Home Assistant backup and read the beta's release notes.
2. In Marketplace, turn on **Pre-release** for this repository. In HACS, open
   **Redownload**, enable beta versions and pick the beta.
3. Follow the [update steps](#update), including the agent update Repair.

To leave the beta, pick the stable release the same way and run the agent
update Repair again. A Home Assistant backup does not restore the agent on
the station.

In beta `3.0.0b3` a **Door level** above Stock also makes calls in the
BTicino app louder. Set it to Stock before you go back to a stable release.

### Going Back on Firmware 3.0.6

Before going back to a release older than 2.10.0, remove the display pages
completely over SSH:
`/home/bticino/cfg/extra/c300x-native-agent/qml_patch.sh restore-all`. Its
last line must contain `"qt5_overlay":"off"`. Older releases cannot remove
the pages, and the agent update refuses an older agent with
`qt5_recovery_required` until then.

## Keys and Access

Setup creates two keys: the **Access key** for daily use and the
**Maintenance key** for updates and repairs. Home Assistant keeps both.

- **Change a key:** **Configure > Connection to the C300X**. An empty field
  keeps the saved key.
- **Key rejected:** Home Assistant asks for the current keys. A rejected
  maintenance key only blocks updates and repairs; calls, video and the door
  keep working.
- **Keys lost:** in the key dialog, tick **I do not have the keys: reinstall
  the agent**. Home Assistant reinstalls the agent over SSH with new keys. The
  old keys stop working; display pages and settings on the station stay.
- **New webhook secret:** **Reconfigure > Rotate shared secret**.

## Maintenance Switches and Buttons

These entities on the device page change the station. **SSH**, **Agent
noAuth**, **Agent noAuth maintenance** and **Remove device agent** are
disabled by default; enable them only when you need them.

| Entity | Use |
| --- | --- |
| **SSH** | Starts or stops SSH on the station. If another tool runs SSH, it shows on and cannot be switched. Switch it off again after use. |
| **Agent noAuth**, **Agent noAuth maintenance** | Recovery only. Keep them off. |
| **Agent mDNS discovery** | Keep it on, so Home Assistant finds the station at a new address. |
| **API firewall patch**, **IPv6 firewall patch** | Open the station's firewall for the agent. Repairs turns on what is needed. Turn IPv6 on only if Home Assistant reaches the station over IPv6. |
| **Home Assistant media user** | The station access for video and calls. |
| **Native MQTT bridge**, **Legacy MQTT bridge** | Local MQTT. **Legacy MQTT bridge** off keeps fquinto's old bridge off. |
| **Reboot**, **Restart device agent**, **Reload device display** | Restart the station, the agent or the display. |
| **Remove device agent** | See [below](#remove-the-device-agent). |

Home Assistant's own start never changes anything on the station.

## Remove the Integration

Removing the Home Assistant entry, removing the integration package and
removing the device agent are **separate operations**. Deleting the entry
does not uninstall the device agent and does not reset the station.

1. Make a Home Assistant backup before removing configuration
   ([backups](https://www.home-assistant.io/common-tasks/general/backups/)).
   Export visitor images and recordings you want to keep, and check that your
   backup actually includes their media storage. A Home Assistant backup is
   not a backup of the station.
2. Stop streams and recordings, and turn off automations that use the station.
   If you also want to [remove the device agent](#remove-the-device-agent), do
   that now, while its button still exists.
3. Go to **Settings > Devices & services**, open **BTicino C300X**, choose the
   three-dot menu of the entry, then **Delete**
   ([official steps](https://www.home-assistant.io/common-tasks/general/#removing-an-integration-instance)).
   With several stations, check the entry name.
4. Remove cards, dashboard views and automations that used the station.
   Blueprints are not removed automatically.
5. Only when no other station entry still uses it, uninstall the package:
   - **Marketplace (HA 2026.11+):** **Settings > Marketplace**, open BTicino
     C300X, three-dot menu, **Uninstall**
     ([official steps](https://www.home-assistant.io/integrations/marketplace/#uninstalling-a-repository)).
   - **HACS:** open BTicino C300X, three-dot menu, **Remove**, then restart
     Home Assistant
     ([official steps](https://www.hacs.xyz/docs/use/repositories/dashboard/#removing-a-repository)).
   - **Manual installation:** stop Home Assistant and delete only
     `custom_components/bticino_c300x`.

### Data That Stays

- **On the station:** without step 2 the agent, its keys, patches and backups
  stay. The station may still try to reach Home Assistant. Deleting the entry
  does not revoke the agent's keys.
- **Visitor images:** under `<HA media root>/c300x/snapshots/`; they are no
  longer cleaned up. A new entry does not take over the old images.
- **Recordings:** under `/media/c300x/` and `/config/c300x/`.
- **Settings file:** `.storage/bticino_c300x.snapshots.<entry_id>` can remain.
  Do not edit `.storage` while Home Assistant is running.
- **History and blueprints:** Home Assistant's history and the copied
  blueprints stay; removing the package does not purge them.
- **Backups:** older Home Assistant backups still contain the keys and media.
  Removing files does not erase older backup copies.

## Remove the Device Agent

**Remove device agent** writes to the station and restarts it. It is not the
same as deleting the entry. Use it only when you want the agent gone.

1. Choose a time with no active call or recording.
2. Enable the **Remove device agent** button on the device page and press it.
3. Keep the Home Assistant entry until the removal reports its result.

What it does:

- restores the original display files, the original call routing and the
  firewall rules;
- deletes the agent folder with its keys (`config.json`) and, on success, its
  backups;
- starts SSH, so you can still reach the station;
- restarts the station;
- gives fquinto's old MQTT bridge (`/etc/tcpdump2mqtt/TcpDump2Mqtt`) its start
  rights back; its start link stays as the **Legacy MQTT bridge** switch left
  it.

It is not a factory reset and does not unroot the station. It does not touch
Home Assistant media or backups.

If a step fails, the removal stops and keeps the agent and its backups. Steps
that already ran are not always undone. In most cases it starts the agent
again so you can retry; the message says what to do. Do not delete recovery
files by hand.

**Back to the [overview](../../README.md#start-here)**
