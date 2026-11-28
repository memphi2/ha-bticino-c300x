# Behaviour Details

Detailed behaviour that the user pages leave out: how setup, maintenance,
recovery, media, the display pages and the automation features work in
detail. It was moved here from the user documentation when that was
rewritten for 3.0.0; the user pages ([Classe 300X](../classe-300x/1-setup.md),
[Classe 100X](../classe-100x/1-setup.md), [Reference](../reference.md)) hold
the short version.

## Setup and Agent Installation


The device agent is a small program on the station that Home Assistant talks
to. What happens next depends on what Home Assistant finds:

- **No agent:** setup offers **Install native agent on the C300X/C100X**; the
  model is not known yet. Use it only on a rooted or SSH-enabled station. Home
  Assistant logs in over SSH with the station's factory root login first. While
  the model is still unknown it tries the C300X factory login and the C100X one
  only after the station refused the first; a connection failure is not
  retried. If the station refuses the login, setup asks for an SSH user with
  root rights (`root` or `root2`, never `bticino2`) and its password, an
  optional private key, or both. The key is pasted as text (OpenSSH or PEM,
  with its passphrase if it has one): RSA or ECDSA on `1.7.x`, `2.0.2` and the
  C100X `1.5.8`, Ed25519 as well on `3.0.6`. A login you enter always takes
  priority. Before it writes anything it checks for the folder `/home/bticino`
  that every station has; any other host that accepts the login, such as a NAS
  or a Raspberry Pi, is refused and left unchanged. It installs the agent, a
  configuration with generated keys, the startup script and the display support
  files, then keeps the keys itself. SSH credentials and the key are used for
  this installation only and are not stored in the entry, diagnostics or logs.
- **Agent already installed:** setup asks for its **Access key** and
  **Maintenance key**. See [Tokens and Access](#tokens-and-access).
- **Agent already installed, keys lost** (for example the integration was
  removed and only its entry had the keys): tick **I do not have the keys:
  reinstall the agent** in the same dialog. Setup then runs the SSH install
  step above: it stops the installed agent, writes the bundled agent with newly
  generated keys and starts it again. The old keys stop working. If this
  station already has an entry in Home Assistant, that entry gets the new keys
  and no second entry is created. Display pages, the core media hook and the
  other settings on the station stay; the station is not restarted.
- **Older agent:** run the **C300X device agent update required** Repair before
  testing camera or calls.

## Device Agent

The native device agent runs on the C300X and serves the authenticated
`/api/v1` API that Home Assistant uses. The setup flow and Repairs install it
on a rooted, SSH-enabled station, update it ([Update](../classe-300x/5-update-and-removal.md#update)),
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
[Station Changed Its Address](#station-changed-its-address).

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
[display activation](../classe-100x/3-display.md#activate-the-display-pages).

### Display Patch

The optional Display patch writes the files for the
[station display pages](../classe-300x/3-display.md#enable-the-display-pages) and reloads the
device UI, which can take about a minute. Use Repairs instead of editing device
files. The Display patch is for the C300X; the C100X display pages use the
[activation by reboot](../classe-100x/3-display.md#activate-the-display-pages), with the
**Activate display pages** and **Restore original display** buttons.

On firmware 3.0.6 the display program loads the patched pages at its start;
its files are not changed. Read
[Display Patch on Firmware 3.0.6](#display-patch-on-firmware-306)
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
[Token Handling](../../SECURITY.md#token-handling).

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
  logs in with the factory login (if the station refuses it, it asks for an SSH
  login as described under [SSH](#ssh) and does not store it), stops the
  installed agent, writes the bundled agent with two newly generated keys and
  starts it again. The entry of this station stores the new keys, also when
  the reinstall ran from a new setup; the old ones stop working. Display pages,
  the core media hook and the other settings on the station stay, and the
  station is not restarted. See [Agent already installed](#setup-and-agent-installation).

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
built-in factory root login (not secret: the same on every device of a model).
While the model is unknown it tries the C300X login and then, only after the
station refused it, the C100X login. The C100X factory login was checked
against the original 1.5.8 firmware, not on a device; a changed password needs
your own login. Only when the device refuses the factory login does Home
Assistant ask for an SSH user with root rights (`root` or `root2`, never
`bticino2`) with a password, an optional private key (OpenSSH or PEM, with an
optional passphrase), or both. Key types: RSA or ECDSA on `1.7.x`, `2.0.2` and
the C100X `1.5.8`; `3.0.6` also accepts Ed25519. A station that accepts keys
only needs the key. Every SSH install (setup, reinstall, Repair) first checks
for the folder `/home/bticino` and refuses a host without it as not a BTicino
station, before anything is written. SSH credentials and keys are used for
this installation only and are not stored. Home Assistant installs the
AsyncSSH client on demand; its host needs no SSH tools or add-on. The device
still requires legacy SSH algorithms, an accepted risk documented as
[LEGACY-SSH-001](../../SECURITY.md#legacy-ssh-001-rsasha-1-during-bootstrap).

The **SSH** switch starts and stops the station's SSH service. Where another
tool keeps SSH running with its own SSH service (davemajor's and daniel-sc's
tools) or restarts it, the switch shows on, its **SSH state** reads **Run by
another tool** with the tool under **Run by**, and it cannot be switched: Home
Assistant and the station's **SSH** control refuse the change. Use that tool
instead.

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
  [Classe 100X Display Pages](../classe-100x/4-troubleshooting.md#display-pages).
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

## Data That Can Remain

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
Removing the agent gives fquinto's old MQTT bridge
(`/etc/tcpdump2mqtt/TcpDump2Mqtt`) its start rights back; its start link stays
as the legacy MQTT switch left it.

On a C100X, removal first checks that the display files are the original ones,
or restores them from their verified backups and checks the result, and
restores the stock routing program; unknown changes or damaged backups stop
the removal before anything is deleted and without a reboot. Removal on a
C100X is in test.

Source: [`native_agent/scripts/remove_agent.sh`](../../native_agent/scripts/remove_agent.sh).

## Media Readiness Attributes

`failed_checks` lists the blocking checks and `warnings` the non-blocking
ones; `recommended_action` is the code Repairs and diagnostics use. Single
results: `agent_reachable`, `agent_version_ok`,
`media_user_ok` (media user and routing), `rtsp_ok`, `talkback_rtp_ok` and
`callback_url_ok`. `forwarding_homeassistant` is `true` when Ring Calls go to
Home Assistant; `false` does not block on-demand video.
`ring_call_supported`, `home_call_supported` and `doorbell_video_supported`
show what the installed agent offers.

## Media Readiness Repairs

When readiness is not `ready` and a known safe fix exists, Home Assistant
raises a Repair. It can re-check the agent, refresh its setup data, open the
IPv4 media firewall, repair the media user and routing, or guide you to a
reachable callback address. Repairs run only when you start them. After one
that changes the station, wait for it to finish and check readiness again
before testing the card.

IPv6 is optional. Enable IPv6 firewall support only when Home Assistant
reaches the station over stable IPv6.

## Connection Paths: Implementation

Implementation reference:
[`webrtc_ice_filter.py`](../../custom_components/bticino_c300x/camera_media/webrtc_ice_filter.py),
[`const.py`](../../custom_components/bticino_c300x/const.py), and
[`test_webrtc_ice_filter.py`](../../tests/test_webrtc_ice_filter.py).

## Station Changed Its Address

When the station gets a new IPv4 address, for example from DHCP, Home Assistant
follows it without your help:

1. Home Assistant renews its connection every 5 minutes. After 15 minutes
   without an authenticated request from it, the station announces itself
   again on the network (mDNS). When its IPv4 address changes, it reopens the
   announcement on the new address.
2. Home Assistant sees the announcement and asks the station at the new
   address to prove that it holds the saved access key. The request carries
   only a fresh random value; the key is never sent to the new address.
3. When the proof matches, the entry moves to the new address and reloads.
   Nothing moves while the station still proves itself at the old address.

Expect up to about 15 minutes until the station announces itself, plus the
time Home Assistant needs to pick it up; meanwhile Media readiness shows
`unavailable`. Home Assistant tries at most once every 10 minutes per entry.
When the station did not answer, Home Assistant tries again up to two more
times, 10 minutes apart. A station that fails the proof is ignored, and the log
warns that it "did not prove the saved identity".

Enter the new address yourself with **Reconfigure** (**Settings > Devices &
services > BTicino C300X/C100X**, entry menu) when:

- the entry uses a host name or an IPv6 address (only IPv4 entries move, and
  only to an IPv4 announcement);
- the entry has no station ID, or its access key is shorter than 32
  characters;
- **Agent mDNS discovery** is off, or the announcements do not reach Home
  Assistant;
- the log shows the failed proof: check that it is your station and that the
  access key is right;
- you do not want to wait.

A DHCP reservation for the station avoids address changes.

## Log Clues

| Log or symptom | Meaning |
| --- | --- |
| `ring_call_not_active` | There was no answerable Ring Call at that moment. |
| `external_session_active` | Another route or client owns the media session. |
| `rtsp_consumer_active` | A capture or stream tried to start while the path was busy. |
| `go2rtc ... error=EOF` on stop | Usually the native RTSP source closing. Relevant when it repeats during start or leaves the card busy. |
| `callback_url` readiness failure | The station cannot reach the HA callback address. |
| Browser microphone unavailable | Use HTTPS or HA Cloud and allow the microphone. |

## Keys

- New keys, and keys of a changed connection, are checked before saving; a
  rejected key gives a different error than an unreachable station. An empty
  key field keeps the saved key.
- A rejected access key takes the entry offline until it is corrected through
  Home Assistant's reauthentication prompt; the other settings are kept.
- A rejected maintenance key locks only maintenance actions such as restart,
  update and repair. Calls, video, door and events keep working.

More: [Tokens and Access](#tokens-and-access).

## Entity Notes

- Enabling the **Audio codec** entity does not change the codec.
- The status attribute `agent_restart_count` counts changes of the agent
  process seen since the entry was loaded. It does not count device reboots; a
  lower uptime alone is not taken as a restart.
- Volatile diagnostics attributes (loop counters, descriptor counts,
  observation times) are kept out of Recorder history. Health states, CPU
  values, write counters and watchdog triggers keep their history.
- `media_watchdog_last_percent` is the CPU value of the last watchdog trigger,
  not the current load; use **Device CPU** for that.

## What Fires and What Does Not

- Initial values, availability updates and a reconnect only refresh the
  entities; they fire no change event. This applies to ringer mute and volume,
  forwarding, touch tone, messages and memos. Home Assistant never sets the
  touch tone on start.
- A changed value first seen after an outage describes the new state, not who
  changed it.
- Message and memo lists keep their last valid content across an access
  failure: unchanged recovery refreshes state, real content changes fire.
- Repeated physical actions, doorbell rings and call steps stay separate
  events, even when their data is identical.

## Events for Automations

For a ring, trigger on the event entities: the outdoor unit's Doorbell ring
event to know which unit rang, the Station ring for the fastest reaction. The
bundled blueprints use the outdoor unit's event.

The integration also fires `bticino_c300x_agent_event_received` for every
station event. Data: `event_type` (the key from the
[event table](../reference.md#events), never a label), `entry_id`,
`device_id` (the outdoor unit's device, else the station's), `unit` and
`call_id` (`null` when the event has none), `event_at`, `data` (the agent's
raw event data, with `raw` and `address` for door and stair light frames),
`source_event_id` when the agent sends one, and the extra data of the event.

The logbook shows each station event on its device (the outdoor unit or the
station) in the language of Home Assistant.

## Media Transport

- Live browser media goes through Home Assistant's WebRTC provider (go2rtc).
  Ring Calls do not need to be forwarded to HA for on-demand video.
- The agent serves RTSP sources for the ring preview video, answered Ring Call
  audio and video with the talkback back channel, on-demand audio and video,
  and Home Call audio.
- RTSP carries interleaved RTP over TCP. UDP is not supported; external
  clients must select TCP.
- A viewer that briefly stops reading loses whole media packets, never part of
  one; the agent keeps no backlog. A sustained stall ends that session.
- With `pcmu` the browser plays the station's audio as it is; with `speex` the
  agent converts it. Codec and audio levels:
  [Codec and Audio Levels](../classe-300x/2-use.md#sound).
- Browser addresses: [Connection Paths for the Live Picture](../reference.md#connection-paths-for-the-live-picture).
  Talkback needs a secure frontend:
  [Live Picture and Talkback](../classe-300x/2-use.md#talking-to-the-door).
- Doorbell, call, ringer, forwarding, memo and message state is pushed by the
  agent; Home Assistant does not poll for it.

For developers: the agent API is in [Native Agent API](../../native_agent/API.md),
packaging in [Native Agent](native-agent.md) and hardware checks in
[Release Validation](release-validation.md).

## Picture Controls

The card's sliders icon reads and changes **brightness**, **contrast** and
**colour saturation** of the live picture in 10 % steps; releasing a slider
changes that one setting. These are station settings, not browser filters, so
saved recordings and snapshots are never recoloured.

While the sliders panel is open, the card hides the play, mute and volume
controls under it; they return when the panel closes.

- **Ring Call:** uses the stock controls of the video call. Opening the sliders
  does not answer.
- **On-demand video:** start live video first; the sliders icon appears about
  two seconds later. On firmware 1.7.19, 2.0.2 (either video decoder),
  3.0.6 (TVP5150 boards only) and the Classe 100X on 1.5.8 the agent checks
  during the session whether the video source offers all three settings. A slider move writes only that
  setting and succeeds only after reading the exact value back; otherwise the
  old value is put back. On a TVP5150 board contrast reads back from the
  driver's own copy, so a contrast write the decoder missed goes unnoticed.
  That copy reads 0 after a station start until the station itself writes
  the contrast once; until then the sliders icon does not appear for
  on-demand video, and the controls may only work during a Ring Call
  (through the display). Every 3.0.6 station has a TVP5150. Tested on
  1.7.19; 2.0.2 and 3.0.6 are checked offline only. Changes last until the
  video ends; the station starts each video with its own values.
- **Classe 100X:** in test in issue #51. The percentages are the station's own day settings. In the
  dark the station switches to its night values, and its own menu has steps
  between the 10 % marks; the sliders then show the nearest 10 % step.

Automations use `bticino_c300x.camera_picture` in an active session: omit
`control` and `value` to read, or send both (for example `control: contrast`,
`value: 60`). The response holds `brightness`, `contrast` and `saturation`.
With more than one station, target the station or one of its entities.

## Stream Settings

**Configure > Camera quality** sets picture size, bit rate and frame rate of the
station's video stream. The settings are stored on the station, not in Home
Assistant, and the form shows the saved values and the ones the device
currently runs with. **Saving reboots the station** (allow about a minute);
choose a time without a call or recording, then open a new stream.


| Firmware | Stream | Sizes | Bit rate | Frame rate |
| --- | --- | --- | --- | --- |
| 1.7.x, 2.0.2 | High | 688x480 (factory cut-out), 704x576 (full height), optional 960x576 | 300-3000 kbit/s (factory 800) | 5-24 fps (factory 15) |
| 3.0.6 | Low | 320x240 to 720x576, including the 5:3 sizes 480x288, 640x384 and 720x432 (factory 400x288) | 100-2000 kbit/s (factory 180) | 5-25 fps (factory 10) |
| Classe 100X 1.5.8 | Low | 352x288 to 720x576 (factory 640x480) | 100-2000 kbit/s (factory 800) | 5-25 fps (factory 12) |

On 3.0.6 only the factory size is tested on a device. The 5:3 sizes match the
display's ratio, not its pixel count, and do not change its picture. Only the
station's Low configuration changes; no program is patched. The other sizes,
their framing and performance are checked offline only; keep the factory size
unless you deliberately test another one
([offline evidence and limits](firmware-3.0.6-camera.md)). On the Classe 100X the camera quality is in test. High video stops at
**24 fps**: at 25 the older firmware turns its frame-rate control off and sends
only about 8 fps. A higher bit rate reduces compression artifacts; lower it
again if your network shows stalls or grey blocks.

The **Camera resolution** select picks the high (688x480 from the factory,
default) or low (400x288) stream from the next stream on. Firmware 3.0.x and
the Classe 100X always use the low stream and have no such select.

## 960x576

The camera delivers 720x576; 704x576 keeps all 576 lines. The optional
**960x576** scales that picture before the station's encoder to the **5:3**
shape of the 800x480 display, without transcoding and without real 960-pixel
detail.

- Offered only for the exact, verified media program of firmware **1.7.19** or
  **2.0.2**; the version number alone is not enough. The live picture is tested
  on 1.7.19; 2.0.2 is checked offline only. Firmware 3.0.x and the Classe 100X
  are not changed.
- Applying it patches the media program after keeping a verified backup of the
  original on the station; choosing 688x480 or 704x576 restores the original.
  A missing or invalid backup blocks restoring: do not delete recovery backups
  or force the option onto an unrecognised program.
- Answering-machine recordings at 960x576 are not verified.

## Snapshot Size

Snapshots read the 800x480 display, not the stream, so 960x576 does not make
them larger. When you change the stream size, tick **Use recommended snapshot
size (800×480)** to keep the display proportions for future snapshots, or
leave it unticked to keep your size. See [Automatic Images](#automatic-images).

## Automatic Images

The device switch **Save images** (on by default) saves one image on every ring
and every video stream started through HA, also with every dashboard closed.
The agent reads the station's 800x480 display picture; HA encodes and stores
the JPEG, and no image files are written to the C300X.

**Configure > Visitor Snapshot** (offered while video is on):

| Setting | Default | Notes |
| --- | --- | --- |
| Image width and height | 800x480 | The display's own pixels and 5:3 shape. Width 64-800, height 64-480. For a smaller image with the same shape use 400x240; other shapes stretch the image. |
| Image delay | 3 seconds | Counted from the ring or stream start. A call or stream that ends earlier may give no image. |
| Keep images | 14 days | Expired images are deleted, also with **Save images** off. |
| Write date and time into the image | On | Drawn in the lower right corner. The card adds no second stamp. |


The agent resizes the full frame without cropping; HA does not resize it again.
A saved size such as 688x480 stays as it is; select 800x480 for the display
proportions in future images. Existing images are never resized.

Images are kept per device in `c300x/snapshots/<device-directory>/` under the HA
media root (not `www`) and appear in **Media > BTicino C300X/C100X Media**, at most
**1,000 images or 128 MiB per device**, oldest removed first. The latest image
is the preview of the camera entity and the card: a saved image, not live
video, and absent until the first capture.

Turning **Save images** off stops new images and hides snapshots in the card,
including the history. Clips and clip automations are not affected; existing
images stay until they expire.

When an image cannot be taken, the last one stays, HA logs a warning once per
cause, and **Save images** shows the cause as **Last failure** (attribute
`last_failure`) until the next image succeeds; after a success the attribute
is absent. The entity shows the text in your language, automations and
templates read the code:

| Code | Shown as |
| --- | --- |
| `snapshot_unavailable` | Display picture could not be read |
| `snapshot_throttled` | Requested too soon after the previous image |
| `invalid_snapshot_size` | Station rejected the image size |
| `invalid_image` | Station delivered an invalid image |
| `agent_unreachable` | Device agent not reachable |
| `agent_error` | Device agent reported an error |
| `save_failed` | Home Assistant could not save the image |

The log names the code. On firmware 3.0.6 reading the display picture is
checked offline only and may fail.

## Browsing in the Card

With **Browse saved images and videos** on, the arrows on the picture (**Older
media** / **Newer media**) page through snapshots and clips, newest first. A
label shows **Snapshot**, **Recording** or **Live**; **Newer media** on the
newest item leaves the history without starting a stream.

Clips have play/pause, a timeline and volume/mute, with their recording time at
the lower right; playback starts with Play. On iPhone and iPad only mute is
shown, because the system leaves media volume to the hardware keys.

Live video and incoming rings take priority. Browsing never starts, answers or
stops a call, asks for the microphone, takes an image or records a clip.

## Storage and Retention

The history only links media that already exists in HA:

| Media | Default location |
| --- | --- |
| Snapshots | `<HA media root>/c300x/snapshots/<device-directory>/` |
| Capture MP4s | `<HA media root>/c300x/`, normally `/media/c300x/` |
| Capture WAV/JPEG/metadata | `/config/c300x/captures/<capture_id>/` |

New successful captures join the history of the C300X that made them when the
service's `output_path` is left unset, even while the history is hidden. Custom
output paths, older MP4s and clips over **64 MiB** are not included. The
history follows **Keep images** (14 days) and holds at most **1,000 items per
device**. An expired history entry leaves its MP4 in place: manage MP4 storage
yourself.

The card history needs camera read permission, but HA's media browser and clip
and message playback follow other rules; read
[Stored Media Access](../../SECURITY.md#stored-media-access) before giving others
HA access.

## Recording: Capture Modes

| `capture_mode` | Starts from | Call handling |
| --- | --- | --- |
| `ring` (default) | An active Ring Call | With audio or `announcement_path`, the call is answered first and may be hung up during cleanup. |
| `on_demand` | Idle media, no ring | Starts a live view and records video with optional audio. Never answers or hangs up a call. |

```yaml
- action: bticino_c300x.capture_doorbell_call
  target:
    device_id: YOUR_STATION_DEVICE_ID
  data:
    capture_mode: on_demand
    duration_seconds: 5
    include_audio: true
  response_variable: capture
```

Set `include_audio: false` for video only. Both modes record 1-15 seconds, and
a second capture on the same device is rejected while one runs.

- `ring` never takes over an answered call. Audio capture or an announcement is
  refused while a client watches the ring preview, so the call keeps ringing
  instead of being answered and dropped; video only can share the preview.
  Hang-up is skipped when the captured call cannot be identified reliably.
- `on_demand` needs idle media with no other camera client; close your live
  view first. A call that starts while the recording connects can make it fail
  or record ring video. `announcement_path` is rejected.
- Unloading the integration or a replacement call cancels a capture.

## Recording: Files and Response

MP4 files go to `/media/c300x/`; WAV audio, three JPEG frames and JSON metadata
go to a workspace per recording in `/config/c300x/captures/<capture_id>/`.
Output paths must stay below `/media/c300x/`, `/config/c300x/` or
`/config/www/c300x/`. The response holds `capture_id`, `entry_id`,
`metadata_path`, `output_path` and, with audio, `raw_wav_path`; use these exact
paths in later steps, for example `{{ capture.output_path }}`. The
`/config/c300x/latest.*` files only point to the newest capture of any device.

At most 64 workspaces are kept per capture folder; those older than one hour
are removed when the next recording starts, and a full limit rejects new
captures instead of deleting recent ones. MP4 files are never removed by this
cleanup.

## Speaker Announcements and TTS

The **Speaker** media player is the station's own loudspeaker. It exists on the
Classe 300X only: on the Classe 100X no safe way to play sound on the station
is known, so the agent offers no speaker and Home Assistant creates none. Use
it like any other speaker in Home Assistant:

```yaml
action: tts.speak
target:
  entity_id: tts.piper
data:
  media_player_entity_id: media_player.bticino_c300x_speaker
  message: The washing machine is done.
```

HA creates the speech with the engine you choose and converts it with `ffmpeg`
to the one format the station plays (8000 Hz mono, telephone quality); media
browser sounds play the same way. With a local engine such as Piper nothing
leaves your network.

- The player's **volume** applies to the next sound, on the station's ringing
  volume range.
- One sound plays at a time, up to about 110 seconds; others wait in order.
  **Stop** ends the current one.
- **A door call always wins.** A ring, a call or a camera request ends the sound
  at once.
- No sound starts during a door call, during a ring and up to a minute after
  its last bus message, for a minute after the agent restarted during a sound,
  or while the station plays a message itself; the action then fails and says
  so. It returns once the station has handed over its speaker.
- A touch tone on the display can cut a sound short.

The attribute `last_result` reports the outcome:

| Value | Meaning |
| --- | --- |
| `played`, `stopped` | Finished or stopped with **Stop**. |
| `preempted` | Ended by a door call. |
| `device_busy` | Not started: the station was using its speaker. |
| `not_played` | The agent did not take the sound. |
| `sound_path_failed`, `play_failed` | The station could not switch the speaker on or play. |
| `failed` | Broke off for another reason. |
| `unknown` | The agent could not be asked or restarted during the sound. |

Tested on firmware 1.7.19. On firmware 2.0.2 and 3.0.6 the agent uses each
station's own sound files, such as its speaker setup for playing messages; that
file differs between firmware versions. Playing is not yet tested on such a
device.

## Notifications

For phone alerts on a ring, use the [Blueprints](#blueprints). For notices on
the station, each entry registers a standard Notify action while **Home
Assistant pages on the display** is on (see
[Enable the Display Pages](../classe-300x/3-display.md#enable-the-display-pages)). The first entry
uses `notify.bticino_c300x`; an entry named **Front door** gets
`notify.bticino_c300x_front_door`, and a name clash adds a short suffix. Use the
ID shown in HA's action editor; it survives restarts and renames. If HA cannot
read its saved name reservations, it registers no action under another
device's name; fix the HA storage or restore it from a working HA backup.

On a Classe 100X the action exists once the
[display activation](../classe-100x/3-display.md#activate-the-display-pages) is
confirmed, and only `display` works there: the notice wakes the screen without
a tone, a positive `sound_duration` is refused, and `tts` and `led` are refused
because the station has no speaker backend and no message LED.

```yaml
action: notify.bticino_c300x
data:
  title: Front window
  message: The front window is still open.
  data:
    display: true
    notification_id: front_window
    severity: warning
    wake_duration: 30
    sound_duration: 30
    expires_in: 3600
```

The target is fixed to the entry, so do not set `target`; `title` defaults to
**Home Assistant**. Fields in the nested `data`:

| Field | Values |
| --- | --- |
| `display`, `tts`, `led` | Channel switches, `true` or `false`; see below. |
| `severity` | `info` (default), `warning`, `error`. A higher severity can replace a lower one, not the reverse. |
| `wake_duration`, `sound_duration` | 0-300 seconds, default 30; `0` turns the effect off. Only with `display`. |
| `expires_in` | 1 second to 7 days, default one hour. |
| `notification_id` | Optional; lowercase letters, digits, `_`, `-`, up to 64 characters. The same ID replaces a notice. |
| `tts_engine`, `language` | Engine and language for the speech. Only with `tts`. |
| `mode` | Legacy; see below. |

The title allows 80 characters. A longer message is cut to 500 characters
and ends with "…". No URLs, audio files or executable actions. This is
supplementary information, **not a fire alarm or other life-safety alerting
system**.

Each switch turns on one channel; combine them freely, at least one on:

| Switch | Channel |
| --- | --- |
| `display` | Notice with popup, screen wake and tone, for `wake_duration` and `sound_duration`. |
| `tts` | The [Speaker](#speaker-announcements-and-tts) says the message, not the title. |
| `led` | The station's message LED, with an unread notice on the HA page. |

| Switches on | Result |
| --- | --- |
| `display` | Notice, popup, wake, tone. The LED stays off. |
| `tts` | Spoken only; nothing is stored. |
| `led` | Notice and LED; no popup, wake, tone or speech. |
| `display`, `tts` | Notice, popup and wake, spoken; no tone. |
| `display`, `led` | Notice, popup, wake, tone and LED. |
| `tts`, `led` | Notice and LED, spoken; no popup, wake or tone. |
| `display`, `tts`, `led` | Notice, popup and wake, spoken, LED; no tone. |

- **Speech wins over the tone.** With `display` and `tts` there is no tone,
  even when `sound_duration` is set; popup and wake still run. The station has
  one speaker, and the tone would hold it while the message should be spoken.
- A switch left out counts as `false`. All switches `false` is refused.
- Positive `wake_duration` or `sound_duration` without `display`, and
  `tts_engine` or `language` without `tts`, are refused. With only `tts`,
  `severity`, `expires_in` and `notification_id` are refused, because nothing
  is stored.
- `led` needs an agent that reports message LED support; otherwise HA refuses
  the call and nothing is shown or spoken. Success means HA stored the notice,
  not that the LED changed. The LED stays on while any unread HA notice that
  asked for it is live; a replacement without `led` releases it. An unread
  station memo keeps the LED on by itself.

To light the message LED as well, add `led: true`. This needs an agent that
reports message LED support, which depends on the station hardware:

```yaml
action: notify.bticino_c300x
data:
  title: Front window
  message: The front window is still open.
  data:
    display: true
    led: true
```

**Without switches** the call shows the notice with popup, wake and tone, and
the notice also lights the LED where the agent supports it, without requiring
that support. `tts_engine` and `language` are ignored then; nothing is spoken.

The `mode` field of earlier releases is gone; a call that still sends it is
refused and names the switches. Replace it like this:

| Old `mode` | Switches in `data` |
| --- | --- |
| `display` | `display: true` |
| `speech` | `tts: true` |
| `both` | `display: true`, `tts: true` |
| `led` | `led: true` |

Set engine and language for the speech once under **Configure > Speech** (for
example `tts.piper`); a language is saved the way the engine names it, such as
`de_DE` for `de`. A notification can name its own `tts_engine` and
`language`. Without any engine, HA uses its default, which is the cloud engine
where Home Assistant Cloud is set up. Engine, language and speaker are checked
before anything is shown or stored. Speech can still fail after the notice is
shown, for example when the engine is unreachable or a door call holds the
speaker; the action then fails and says why. `tts.speak` on the speaker works
without the display pages.

Popup, wake and beep run only on the stock Home or HA page while no call is
active or ringing. Alarmo, PIN entry, settings and other protected pages
suppress them: the action succeeds, keeps the notice and logs the suppression;
speech and the LED still follow their switches. Effects stop on a touch,
standby, a call or leaving the page and are never queued. HA keeps notices in
memory and sends each once; without a connected display a call with `display`
fails, with no retry. Success does not
prove the notice was seen or heard, so test on the device before relying on
it. Notices from `bticino_c300x.show_display_notification` are described in
[Display Notifications](#display-notifications).

## Blueprints

The integration ships optional automation blueprints that use the public C300X
services and entities and change no device configuration. On startup, missing
ones are copied to `/config/blueprints/automation/bticino_c300x/` and appear
under **Settings > Automations & scenes > Blueprints**. Unchanged bundled files
are updated, changed ones kept; old bundled files are removed only while they
match a known original. If one is missing, restart Home Assistant once, or use
**Import Blueprint** with
`https://github.com/memphi2/ha-bticino-c300x/blob/main/blueprints/automation/bticino_c300x/<file>`.

| Blueprint | File | Purpose |
| --- | --- | --- |
| BTicino Doorbell notification | `doorbell_notification.yaml` | Your own notification action on a ring; does not answer. |
| BTicino Ring Call Android phone alert | `doorbell_call_android.yaml` | Rings an Android phone with **Answer**, **Hang Up**, **Open**. |
| BTicino Ring Call iOS phone alert | `doorbell_call_ios.yaml` | Rings an iPhone (critical sound) with **Answer**, **Hang Up**, **Open**. |
| BTicino Ring capture | `ring_capture.yaml` | [Records a clip on a ring](../classe-300x/2-use.md#recording-a-ring). |
| BTicino Ring capture and Wyoming transcription | `ring_capture_wyoming.yaml` | Records and transcribes with a local Wyoming Whisper service. |
| BTicino strict phrase decision | `strict_phrase_decision.yaml` | Checks a transcription for an exact phrase; optional unlock. |
| BTicino Calendar display reminder | `calendar_display_reminder.yaml` | Reminder on the station's HA page before a calendar event. |

The ring blueprints start from the **Doorbell ring event** of the outdoor unit
you select and act on that unit's call. They find the forwarding select and
the Media Readiness sensor on the station the unit belongs to. For the fastest
reaction, without the unit's name, select the station's **Station ring**
event instead: it fires at once with every ring, the unit's event as soon as
the station names the caller (about 0.3 s, at most 1 s; at once with a single
unit). Phone alerts and captures run only while readiness is `ready` or
`warning`.

### Phone Alerts

Both phone alerts need **Forwarding** set to **Home Assistant** and the Companion
App notify service of the phone, for example `notify.mobile_app_your_phone`.
The alert stops ringing when a **Door** event of the station fires, whatever
opened the door; the call itself goes on.

- **Android:** a high-priority notification. **Answer** calls
  `bticino_c300x.answer_call` for this call, swaps the ringing notification for a
  quiet in-call one with **Hang Up**, and opens the dashboard with a temporary
  `c300x_ring_answer` URL marker so the card attaches to the answered call.
  **Open** alone does not answer. Set the ringtone in the Companion App for the
  blueprint's notification channel. Opening uses the `command_webview` command;
  the app may ask once to display over other apps.
- **iOS:** a critical notification. **Answer** opens the dashboard with the same
  marker and calls `bticino_c300x.answer_call` for this call.

### Doorbell Notification

This blueprint leaves the action to you (mobile app, persistent notification or
script). The action can use `camera_entity`, `dashboard_path`, `call_id`,
`unit_name` and `entry_id`:

```yaml
action: notify.mobile_app_your_phone
data:
  title: Doorbell
  message: Someone is at the door.
  data:
    url: "{{ dashboard_path }}"
    clickAction: "{{ dashboard_path }}"
    entity_id: "{{ camera_entity }}"
```

### Capture and Transcription

The Wyoming blueprint always records audio, so it answers the Ring Call. It
stores the capture response as `capture` and passes `capture.metadata_path` and
`capture.raw_wav_path` to `bticino_c300x.run_ring_wyoming_analysis`; that
response (`analysis`) holds `result_path`. With the result path left empty, the
result goes to `analysis/result.json` beside the recording's metadata; a custom
path must not be shared between automations or devices.
`/config/c300x/analysis/result.json` points to the latest result of any device.

### Strict Phrase Decision

Run it after transcription, for example from an `input_button`. It calls
`bticino_c300x.evaluate_ring_analysis`, which unlocks only if the result
belongs to a fresh capture not yet used for an unlock, the phrase matches
exactly and `unlock_on_match` is on (off by default). Select the door station
or the door's outdoor unit as the device. The unlock opens the door of the
outdoor unit that rang; a capture from another station, or a device of another
outdoor unit, is rejected. Each capture is reserved before the unlock is sent,
also across HA restarts within the freshness window, so it is never used
twice. After a
failed or cancelled unlock, make a new capture. An unreadable reservation file
blocks unlocking; do not delete it to retry a still-fresh capture.

### Calendar Reminder

Select an HA calendar, the C300X, the lead time (15 minutes by default), the
text and the expiry. It uses a calendar event trigger and does not wake the
display or interrupt calls. For a test, create the event more than 15 minutes
ahead (see the
[Home Assistant calendar documentation](https://www.home-assistant.io/integrations/calendar/#automation)).

## Device Activations

Extra door locks and actuators of the door system, for example a second door
or a gate opener, become activations: button entities (`button.press`).
Configure them in setup, options or reconfigure under **Activations: locks,
actuators, stair light**. Changes are
collected and saved with **Finish and save**; the device is written only when
its activation list differs, never on a plain HA start.

| Field | Rule |
| --- | --- |
| ID | Letters, numbers, `_` and `-`, up to 32 characters, unique. |
| Name | Button name, up to 63 characters. |
| Type | Door lock, Actuator or Stair light. An actuator is what the station's display calls "Generic": it is pressed and released like a door lock. Activations reported by the agent can also be `scenario` or `generic`. |
| Address | OpenWebNet `where` value, up to 31 characters. |

**Stair light address:**

- **Automatic** switches the stair light at the station's own address, which
  the station knows from its configuration (for example `11`), as its
  display does. Home Assistant sends no address.
- **Manual (P and N)** uses the address built from the P and N parts (0-99
  each) for the stair light button and builds one `stair_light` activation
  from it; that ID is reserved, so up to 15 more activations fit.

At most 16 activations are sent to the agent.

**From the station:** the door locks of the outdoor units, the actuators and
the stair light that the station itself is set up with (its own
configuration, as its display shows them) are activations too, each with a
button. The settings list them under **From the station**, the ones set up
here under **Manual**; a manual activation of the same type at the same
address replaces the station's. The button's attributes name the `source`
(`config` for manual, `station`) and, for a station lock, the `unit` whose
door it opens.

## Display Pages: General

The pages speak German, English, French, Italian and Spanish; any other
language shows English. What Home Assistant sends (tile states, the energy,
agenda, leave home and situations texts) follows Home Assistant's language;
the pages' own texts (Alarm page, settings tab, buttons) follow the
station's language.

Page and tile settings are stored in Home Assistant, and the display asks for
them, so changing them writes nothing to the station. Entity changes reach the
display through the existing event connection, without polling. Only entities
selected for the display can be operated from it, and Home Assistant checks
every command against the current selection and the entity's capabilities.

## Display Patch on Firmware 3.0.6

The display has the same buttons, pages and **Integration** tab as on 1.7.x
and 2.0.2, and is switched on and off the same way. Its pages are part of the
station's display program, so the Display patch keeps the changed pages in the
agent's folder and the display loads them at each start. On a 3.0.6 station
the pages loaded at start and the Alarm and Home Assistant buttons sat in the
right place; the other pages are checked offline only.

- **When the display fails with the pages:** the agent starts it once more
  and then as shipped, until the station restarts. The Display patch status
  reads **applied, but the display started as shipped**. Turning the
  **Display patch** switch on, the core hook Repair or an agent update tries
  the pages again; saving the display settings does not.
- **Restarts:** the agent runs one display restart at a time, after the old
  display has ended; changes close together share one restart. Home Assistant
  waits for a restart that takes longer.
- **Install and update:** a display step that fails does not fail the
  installation or the agent update; the core hook Repair stays until it has
  run the display steps again. A step that could not run at all, for example
  without a connection, still fails.
- **On a display the agent does not know**, for example after a firmware
  update, the display stays as shipped and the agent runs without the pages.
  Repairs shows **C300X display pages are not available on this station**
  with the reason.
- **Removal:** removing the agent restores the station's display start. Before
  going back to a release older than 2.10.0, remove the pages completely over
  SSH with `/home/bticino/cfg/extra/c300x-native-agent/qml_patch.sh restore-all`
  and check that its last line contains `"qt5_overlay":"off"`; older releases
  cannot remove them, and the agent update refuses an older agent with
  `qt5_recovery_required` until then.
- **If the station keeps restarting** after an install, an update or saving
  the display settings:
  1. Over SSH, between two restarts, rename the display resource file:
     `mv /home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc /home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc.hang`.
     The next start uses the original display.
  2. Once the original display runs, remove the pages and the core hook over
     SSH: `/home/bticino/cfg/extra/c300x-native-agent/qml_patch.sh restore-all`.
     Its last line contains `"qt5_overlay":"off"`; the display restarts once,
     as shipped. If it answers `An unfinished GUI write is still in place`,
     wait a minute and run it again.
  3. If the restarts began with an install from Home Assistant or after
     saving the display settings, also turn off **Home Assistant pages on the
     display** (this discards the page settings); otherwise Home Assistant
     applies the pages again at its next start. After step 2 this writes
     nothing to the station.
  4. Until you have reported it, do not run the core hook Repair, the
     **Display patch** switch or an agent update: each writes the resource
     file again. Keep `display-qt5.rcc.hang` for the report.
- **What to report:** the Display patch status, the integration diagnostics
  and, if you can reach the device, `/tmp/c300x-display-qt5.log` (the display's
  error output, at most 64 KB, cleared by a restart of the device).

Technical details: [Native Agent](native-agent.md#supported-firmware-versions)
and the [firmware display audit](firmware-3.0.6-display.md).

## Pages and Positions

**Configure > Display > Display pages** lists the pages in display order, for
example **Page 2: Living room**. Pick one to open its form; submitting returns
to the list. **Add a page** appears while a page of your own is still free.

| Page | Default position | Default |
| --- | --- | --- |
| Status page | 1 | On |
| [Energy](#energy-page) | 2 | Off |
| [Agenda](#agenda) | 10 | Off |
| [Leave home](#leave-home) | 11 | Off |
| [Situations](#situations) | 12 | Off |
| Up to seven pages of your own | After the existing pages | - |

| Field | Meaning |
| --- | --- |
| **Name** | Heading of the page on the display, in place of Home Assistant. Up to 60 characters; each name once, in any capitalisation. A page with entities needs one. The status page has none. |
| **Position** | Place among all pages, 1 to 12. |
| **Entities** | The page's tiles, in the order picked; drag to reorder. An entity is on one page only. In the form of a single page under **Display pages**, picking one that another page shows moves it, with its tile settings, to this page; setup and reconfigure, which show all pages at once, refuse it instead. |

How positions work:

- In the settings, a page takes the position it asks for and the other pages
  are numbered around it. Left empty, a page keeps its place and a new page
  goes to the end. Decimals are rounded.
- On equal positions Energy comes first, then Agenda, Leave home, Situations
  and the regular pages in their own order.
- A page the display does not show (switched off, or without entities) has no
  number and follows the shown pages. Switching an optional page off keeps its
  position and selections.
- Two things the form cannot count can shift the numbers on the display: a
  page used only by allowed actions, and an Energy page that is on while Home
  Assistant has no energy data.
- A page of your own without name and entities is removed.

In the setup and the reconfigure all pages are sections of one form, headed
with their page number. Free sections come last, titled **Page +**; fill one in
to add a page. There, an empty position returns an existing page to its
section's number.

### Status Page

The status page keeps the heading Home Assistant and shows the HA, alarm and
time badges, an optional weather card at the top (**Weather** field) and its
entities. With arrow navigation it also has a button for every other visible
page. **Show the status page** (on by default) switches the whole page,
independently of weather and entities; off keeps its settings. If no page is
visible at all, display notices still get a neutral page. The name `C300X` is
reserved for the status page.

### Page Navigation


| Choice | On the display |
| --- | --- |
| **Favourites bar** | A bar along the bottom edge with one button per page; the current page is marked in yellow. The status page is labelled **Home**, other pages show their name on up to two lines. |
| **Arrows (previous / next)** | `<`, the page number and `>` below the tiles. |

The bar has four places in page order. With more than four pages the fourth
is **More**: it opens a list of the other pages and stays marked while one of
them is shown. The station's back button closes the open list first. Changing
pages uses the data already loaded and requests nothing new.

## Controls by Entity Type

A tile with a chevron opens a detail page: tap anywhere on it. Back returns to
the same page and scroll position. Controls appear only where the entity
reports the feature.

| Entity | Tile | Detail page |
| --- | --- | --- |
| Light | On/off switch, brightness | Brightness, eight colour swatches, warm, neutral and cool white within the light's Kelvin range, a Kelvin slider and effects. White and colour get separate tabs where both are supported. |
| Cover | Position, opening or closing | Up, stop and down stay visible at the top; position and tilt separately. A missing position is not shown as closed. |
| Climate | Measured temperature, heating or cooling activity | Target temperature or range and HVAC mode; presets, fan mode and swing on a settings tab. |
| Fan | On/off switch, speed | Speed, oscillation, presets and direction. |
| Media player | On/off switch; artist and title, or the state, as its State line | Previous, play/pause and next, volume, mute, source, sound mode, shuffle and repeat (off, all, one). |
| Lock | Locked, unlocked, locking, unlocking or jammed | Lock, unlock and open the latch. Unlock and open ask for a second tap on the same button, which then reads "Sure?". |
| Vacuum | What the robot is doing | Start, pause, stop, return to base, locate and suction. |
| Valve | Position, or the state | Open, stop, close and a position slider. |
| Humidifier | Switch, room humidity | Target humidity and modes. |
| Water heater | Water temperature | Target temperature and operation mode. |
| Number, select and their input helpers | Value | Home Assistant's units, bounds and steps; the entity's own options. |
| Switch, input boolean, automation, siren | Switch | - |
| Button, input button, scene, script | Button | - |
| Sensor, binary sensor | Large reading with its unit and precision | Read-only; battery, humidity and illuminance where reported. |
| Person, device tracker | Home, away or the zone | - |
| Camera, image | Picture | See [Picture tiles](#picture-tiles). |

| Entity | Buttons on a full-height tile |
| --- | --- |
| Cover | Up, stop, down |
| Climate | Target temperature minus/plus by the entity's step |
| Light | On/off, brightness minus/plus in 10 % steps |
| Fan | On/off, speed minus/plus by about 10 % |
| Number | Minus/plus by the entity's step |
| Select | Previous/next option, wrapping at either end |
| Media player | On/off, previous, play/pause, next |

Minus and plus are dimmed while there is no value to step from, for example a
light that is off; tapping them then opens the detail page. A press while the
previous command is still under way is ignored.

More tile behaviour:

- A small symbol before the name shows the type or device class, for example
  a sun for a light or a note for a media player.
- Timestamp sensors show a short local form such as `14.11. 10:30`, date
  sensors the date such as `14.11.2026`.
  Text cut to fit ends in three dots.
- Sliders send one command when released, not while moving.
- Numbers and select options follow Home Assistant's language: a decimal
  comma in German, French, Italian and Spanish, a point in English and all
  other languages.
- A lock's second-tap question moves to another button when that is tapped
  and stays until the page is left or the screen goes off. Locking needs no
  second tap.
- Long choice lists (a select's options, a player's sources) offer their first
  options, at most 50. If the content is still too large for the display, the
  longest lists are shortened further; if even that is not enough, the display
  shows Home Assistant as unavailable and Home Assistant logs a warning.
  Select fewer entities.

Command feedback shows sending, accepted, and confirmed once Home Assistant
reports the matching state. This is not a physical check for entities that
report their state optimistically. A command Home Assistant never reflects is
marked unconfirmed after 15 seconds; a track skip stays accepted. Feedback
clears a minute after the last change. Errors stay at the control and an
uncertain result is not retried. During a connection outage the last state
stays visible, marked as stale, with all actions disabled.

## Picture Tiles


A camera or image entity becomes a picture tile. By default it spans the page
and takes the picture's proportions, up to 320 px high; a taller picture is
shown whole and narrower. With **Width** Half two pictures stand side by side.
With **Height** Half (138 px) or Full (286 px) the picture is cut around its
centre to fill the tile. Home Assistant scales the picture to the tile before
the display loads it. At Automatic height a smaller picture is enlarged up to
twice its size; with Half or Full it is enlarged as far as the tile needs.

It is a still, not a stream: an image entity reloads when it has a new
picture, a camera about every five minutes. The entity name is written in the
bottom left corner; a tap does nothing. An unavailable entity has no tile
until it is back, and a picture that cannot be read shows only the name until
the next one.

The display loads the picture from Home Assistant at an address signed with
the entry's secret. It serves only camera and image entities on the display
pages and needs no login, so anyone who can reach Home Assistant and has seen
the address can load that scaled picture. It does not expire; it stops working
when the entity leaves the display pages or the display pages are switched off. Picture tiles
need a plain `http://` callback address, because the display cannot open
`https://`; with an HTTPS callback address they are left out. They are not
offered for the Alarm page.

## Energy Page


The Energy page shows Home Assistant's own Energy setup (**Settings >
Dashboards > Energy**): meters, names, prices and power sensors come from
there and are not configured twice. Turn it on with **Show the energy page**
and pick its views. With more than one view, buttons at the bottom switch
between them; all views off hides the page and keeps its settings.

| View | Shows |
| --- | --- |
| **Now** | Solar, grid, battery and home with today's energy, and the current W/kW beneath the flow arrows. A source without a power sensor counts as 0 W; an unavailable sensor stays unknown. A power sensor shared by several meters counts once. |
| **Today** | Hourly bars: grid import, solar and battery discharge above zero, grid export below. A table of up to eight rows with costs; further meters are grouped as **Other meters**. |
| **Power** (form: **Power history**) | Today's power for grid, solar, battery and home as 15-minute means of recorded statistics, on one W/kW scale. Export and battery charging go below zero; missing statistics leave gaps. |
| **Consumers** | The ten individual devices with the highest current power, in two columns of five. |
| **Balance** | Share of solar used at home, self-sufficiency, net energy from the grid and today's cost. |

- Tap the Today or Power chart to see the exact values of one interval.
  Nothing is filled in between recorded values.
- **Consumers** uses the power sensors set for individual devices in Home
  Assistant's Energy settings, with their names. Unavailable, invalid or
  negative readings are left out and a hint marks the list as incomplete; a
  measured 0 W shows an empty bar. Each column scales its bars on its own, so
  compare the W values across columns.
- A kind of source not set up in Home Assistant is left out. Without any
  electricity source the page is hidden, unless **Consumers** is on. Gas and
  water are not shown.
- Colours: blue grid, yellow solar, green battery, violet export, coral home.
- An energy meter in kWh has no current W value: add power sensors in Home
  Assistant's Energy settings for the live readings.
- Home Assistant computes the charts from its recorder statistics and changes
  none of them. Now and Consumers update at most every ten seconds; switched-off
  views request nothing. No charts are stored on the station.
- The page's texts follow Home Assistant's language in German, English, French,
  Italian and Spanish; other languages show English.

## Agenda


Turn on **Show Agenda** and select up to eight Home Assistant calendars. The
page shows up to five ongoing or upcoming events within the next seven days,
all-day events included. A loading message appears on the first read, and a
slow calendar does not hold up the other pages. A failed calendar read is
shown as such, not as an empty agenda. Turning the page off or selecting no
calendars stops its reads.

Showing an event does not trigger anything. For a reminder before an event,
use the calendar reminder blueprint ([Blueprints](#blueprints)).

## Leave Home

Turn on **Show Leave home** and select what to check before leaving: up to 24
door and window contacts (**Windows and doors**), up to 24 lights and up to
eight **Actions** from the allowed actions. Nothing else in Home Assistant is
inspected. An unavailable contact stays unknown, never counted as closed.

Opening or refreshing the page never runs an action. The first tap on an
action asks for **Confirm** within eight seconds and can be cancelled. Leaving
the page, changed page data, a running command or a lost connection clears the
pending confirmation.

**Show Alarmo readiness** adds the alarm configured for the display. It opens
the Alarm page with its usual readiness checks and PIN; it never arms the alarm
by itself. A disarmed panel shows its readiness, an armed or arming one its
state.

## Situations

Turn on **Show Situations** and pick the entities to watch, up to 24 in total.
The page lists only those that need attention, one row each with the state on
the right:

| Field | Shown when |
| --- | --- |
| **Windows and doors** | A contact with device class door, window, opening or garage door is open. |
| **Garage doors** | A cover with device class garage is open, opening or closing. |
| **Lights** | The light is on. |
| **Task lists** | The to-do list has pending items; the row shows their number. |

An unknown or unavailable entity stays on the list in yellow and never counts
as closed or off; an entity of another kind shows as unsupported. With nothing
to show the page says so in one line. The page is read-only: it runs no
action, does not wake the display and never changes the page by itself.

## Display Notifications

Automations can put a compact notice on the station's Home Assistant page;
tap it for details. It does not open by itself, wake the display, cover the
Alarmo PIN entry or interrupt a Ring Call. For notices that wake the screen,
sound a tone or speak, use the Notify service in
[Notifications](#notifications).

```yaml
action: bticino_c300x.show_display_notification
data:
  notification_id: front_window
  title: Front window
  message: The front window is still open.
  icon: warning
  priority: important
  expires_in: 3600
```

| Field | Values |
| --- | --- |
| `notification_id` | Required. 1 to 64 lowercase letters, digits, `_` or `-`. The same ID replaces a notice. |
| `title` | Required, up to 80 characters. |
| `message` | Required. A longer text is cut to 500 characters and ends with "…". |
| `icon` | `info` (default), `warning` or `calendar`. |
| `priority` | `normal` (default), `important` or `urgent`. |
| `expires_in` | Seconds, 1 to 604800 (7 days); default 3600. |
| `actions` | Up to two `{action_id: ..., label: ...}` entries from the allowed actions. |

With more than one station, add a `target` with the station's device.

`bticino_c300x.dismiss_display_notification` with the same `notification_id`
removes a notice.

- Up to eight notices (16 KiB in total) are kept, highest priority first. When
  full, the oldest notice of the lowest priority is replaced; a lower-priority
  notice cannot push out a higher one.
- Notices live in Home Assistant's memory only. Restarting Home Assistant or
  reloading the integration clears them, so automations should resend
  conditions that still apply. Nothing is written to the station or the
  recorder.
- Where the agent reports message LED support, a notice also lights the
  station's message LED until it is dismissed or expires. The Classe 100X has
  none.
- An action never runs because a notice arrives, only when tapped. **Mark
  read** only dismisses the notice; it neither fixes the condition nor runs an
  action. Commands for a notice that has since changed are rejected.
- The bundled **BTicino Calendar display reminder** blueprint shows a notice
  before a calendar event ([Blueprints](#blueprints)). For a
  reliable test, create the event more than 15 minutes ahead, as the
  [Home Assistant calendar documentation](https://www.home-assistant.io/integrations/calendar/#automation)
  notes.

## Station Settings Tab

The Display patch adds an **Integration** tab (it **Integrazione**) to the
station's **Settings** menu, below **Configuration**. **Status messages**,
**SSH** and the maintenance operations work without Home Assistant; the two
Display options need it and are greyed out while it cannot be reached. Only
maintenance operations the agent has enabled are offered.


The tab starts with a short status block:

| Line | Meaning |
| --- | --- |
| **Home Assistant** | **reachable** with the name of the Home Assistant instance, or **not reachable** with the reason underneath (see [Home Assistant not reachable](#home-assistant-not-reachable)). |
| **Address** | The address the station calls Home Assistant at: `http` or `https`, host and port. A long address takes a second line; a very long one is shortened in the middle, so that its start and its port stay visible. Nothing else of the address is shown. |
| **Last contact** | How long ago the agent and Home Assistant last exchanged a request, or **never since start**. Read when the tab opens, and once more after Home Assistant has answered. |
| **Integration**, **Agent** | The version of the integration, and of the agent with the station firmware. The integration version is known only while Home Assistant answers. |

Address, last contact, agent and firmware version come from the agent on the
station, so they also show while Home Assistant cannot be reached.

| Control | Effect |
| --- | --- |
| **Status messages** | Shows (default) or hides coloured action confirmations and routine messages on the Home Assistant and Alarm pages, such as "Page loaded", "Connected", "Sending" or "Ready to arm". Text at a control, errors, a required PIN, sensors that block arming, connection warnings and real alarm or entity states always stay visible; while a command runs, the Alarm page still names it in its state box. |
| **Keep page open in standby** | The integration's Display option of the same name: whether the Home Assistant and Alarm pages stay open when the screen goes to standby. |
| **Page change: favourites bar / arrows** | The integration's Display option **Page navigation**: on shows the favourites bar, off the arrows. The label names the current choice. |
| **SSH** | Switches the station's SSH access; not where another tool keeps SSH running ([SSH](#ssh)). |
| **Reboot station** | Restarts the station. |
| **Remove agent** | Removes the device agent; see [Remove Agent](#remove-agent). |

Reboot and removal ask first, in the station's own confirmation window with
**Yes** and **No**. Nothing is sent before **Yes**; the question closes by
itself after 30 seconds, and leaving the tab, a call or the screen going off
cancels it. **Keep page open in standby** and **Page change** are stored in Home
Assistant: the switch shows the value Home Assistant confirmed, the
integration's options show the same value, and a change made there reaches
the station as well. Neither reloads the integration or touches the Display
patch. While Home Assistant cannot be reached, both switches are greyed out.
**Status messages** is a
station preference, not an integration option, and survives restarts. If the
agent cannot read or save it, the switch shows **Setting unavailable**; reopen
the tab before trying again.

What the tab cannot read when it opens shows at the rows: the switch or button
concerned is greyed out. A line at the foot of the tab appears only as the
result of something done there: a request the station accepted, a setting
that could not be saved, or a request that got no answer in time.

### Home Assistant not reachable

A house symbol beside the power button of the home page stands for the
connection to Home Assistant; tapping it opens the **Integration** tab. The
home page asks Home Assistant which of its two buttons to show. If that fails
seven times in a row (about a minute), the symbol gets a yellow exclamation
mark and the page keeps asking every five minutes while it is visible. The
next answer removes the mark. The symbol follows what the home page last
read: when it is shown, on a message from Home Assistant, and on those
retries. It is hidden while the display pages are switched off in the
integration, also when Home Assistant has told the agent so and no longer
answers the station. The **Integration** tab names the reason for as long as the
problem lasts:

- **Home Assistant has not registered since the agent started.** The agent is
  running, but Home Assistant has not connected to it yet, for example
  shortly after a station restart or while the integration is not loaded.
- **The station pages are switched off in Home Assistant.** The integration
  option **Home Assistant pages on the display** is off, so Home Assistant has
  told the agent not to ask it.
- **Home Assistant does not answer.** The station cannot reach Home Assistant
  at the address the integration gave it. Check the address of Home Assistant
  for the C300X in the integration's connection settings: it must be
  reachable from the station over http, or over https with a trusted
  certificate.

**Settings > Generals > Tone buttons** stays the station's own touch-sound
control. With the Display patch active, the device page in Home Assistant
offers the same setting as the **Touch tone** switch under **Configuration**.
It follows changes made on the station, is unavailable while the agent has no
connection to the station's interface, and Home Assistant never sets it on
start. A confirmed
change fires a **Touch tone changed** device event; see
[Events](../reference.md#events).

Turning the Display patch off restores the original Settings menu. A Settings
page in an unknown layout, or a missing backup of an already patched page,
stops the patch instead of replacing the original with a guess.
