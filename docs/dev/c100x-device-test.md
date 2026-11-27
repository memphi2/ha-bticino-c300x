# Classe 100X Device Test

Material for testers and developers of the Classe 100X support (firmware
1.5.8, [issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51)).
The user pages are in [docs/classe-100x](../classe-100x/1-setup.md); the
private backup to make first is in
[Make a Private Backup](../classe-100x/1-setup.md#make-a-private-backup).

## What Is Different on the C100X

| Area | On the C100X |
| --- | --- |
| Model detection | The agent reads the model from the station's own `<webserver_type>` (`/home/bticino/sp/dbfiles_ws.xml`); the display program (`BtClass100` on a C100X) is the cross-check and decides where that name is missing or disagrees. A disagreement is reported and blocks the display activation. The agent announces `_bticino-c100x-agent._tcp`; an announcement of one model never matches or moves an entry of the other. |
| Camera | Only the low stream; no **Camera resolution** select and no 960x576. Picture controls use the station's day ranges (brightness 30-220, contrast 80-255, saturation 80-255); at night and on off-grid menu steps the sliders show the nearest 10 % step. |
| Audio | The firmware codec stays Speex/8000: the station's audio runs at 16 kHz, the firmware's PCMU path accepts only 8 kHz, and the audio chip clocks every profile at 16 kHz. The agent therefore refuses a firmware PCMU switch, and Home Assistant offers no **Audio codec** select. HA and the browser still get PCMU through the agent ([audio analysis](c100x-audio-analysis.md)). |
| Speaker and TTS | Not offered. The station's own sound paths have no safe owner or cancellation for a door call, so the agent blocks the C300X playback path on a C100X. |
| Answering machine | Not offered: the vendor library switches it off for this board, so nothing is recorded. The agent refuses the answering-machine, voice-memo and memo-delete requests; HA creates no such entities. |
| Text memos | Not offered: HA creates no memo entities, `write_text_memo` is refused with a translated message, and the display has no memo page. |
| Message LED | Not driven; the agent reports none, and HA refuses Notify `led`. |
| Display | A separate Qt 5 adapter activated by one reboot, confirmed in its first boot and otherwise rolled back; entered through the items **Home Assistant** and **Alarmo** of the station's main menu and operated like the station's own menus (Up/Down, Return, EXIT as the last entry). No Display patch, no home page buttons, no display reload ([details](c100x-display-parity.md#activation-by-reboot)). |
| Agent update | With active, confirmed display pages the agent update Repair renews them when the update brings newer pages: the agent prepares them and reboots the station once, after it has been idle for about two minutes, never during a call and only while the maintenance reboot is allowed. The boot confirms the new pages; otherwise the station goes back to its original display. A station with the original display is not rebooted. |
| Ringer mute, touch tone, display notifications | Only after the display activation; notifications without a tone. **Ringer volume** works without it. |

## What Setup Changes on the Station

Setup installs nothing on a C100X until you tick **experimental support** in
the setup dialog. Then, with the default paths and API port 8091:

| Where | What |
| --- | --- |
| `/home/bticino/cfg/extra/c300x-native-agent/` | The agent, its display files and scripts, `bundle.json`, `config.json`, `c300x-agent.env`. |
| `/etc/init.d/c300x-native-agent`, `/etc/rc5.d/S40c300x-native-agent` | The start script and its boot link. |
| `/etc/network/if-pre-up.d/iptables` | If the vendor file exists, one managed IPv4 block; if it is absent, it stays absent and no rule is changed. |
| Live IPv4 rules | With the vendor file present: the API port (TCP 8091), RTSP (TCP 6554) and talkback (UDP 40004). |
| `/home/bticino/cfg/extra/c300x-device-file-backups/` | Backups of what the integration changes. |

Setup does not write the IPv6 firewall, the vendor display, SIP accounts or
Companion. With video on, the first Home Assistant start afterwards sets up the
media user, as on a C300X:

- `/home/bticino/bin/bt_answering_machine` changes from the stock 1.5.8 hash
  `cc53dd834361e8a76268b108ce2562b8447d597798dd2f136ce4707142485e12` to
  `86caa9773895063b44e680e2508c7a9fb5579b89e2a484180d4c6a3536afa6b3`; the stock
  copy is kept in the backup directory.
- In the Flexisip `users/` directory, `users.db.txt` gains one
  `homeassistant-…` line, `accounts.txt` its label line, and the `alluser`
  route in `route_int.conf` gains that user as one more target. Every existing
  account and target stays.

A `route.conf` that is a regular file, or a link to anything but
`route_int.conf` or `route_ext.conf` (for example Companion's), is refused with
`unsupported_active_route`; nothing is written and video and calls cannot be
tested on that station.

## Test Plan

Run the steps in order, after the backup. Stop at the first failure.

| # | Do | Expected |
|---|---|---|
| 1 | Add **BTicino C300X** with the C100X host and tick **experimental support** when asked | Setup completes without a workaround; model C100X, firmware 1.5.8 |
| 2 | Press **Stair light** once | The light comes on |
| 3 | Press **Door unlock** once, with an authorized person at the door | The door releases |
| 4 | Start the live stream on the card | Picture and sound; the stream ends cleanly |
| 5 | Ring at the outdoor station and answer in HA | Picture, two-way audio, hang-up works |
| 6 | Move brightness, contrast and saturation on the card | The picture changes; a new stream shows the station's own values again |
| 7 | Enable Maintenance with reboot, press **Activate display pages** ([details](#display-activation-by-reboot-device-test)) | One reboot after two minutes idle, then **Home Assistant** and **Alarmo** follow the ringtone item in the station's main menu |
| 8 | Press **Restore original display** | One reboot, stock display back |
| 9 | Optional: repeat step 7 and pull the power within 60 s after the reboot | Stock display back, repair message in HA, no further reboot |

After step 1, before the others: the physical keys and the BTicino app work as
before, and the display programs (`BtClass100`, `BtClass100_qws`, the QML
files) have their hashes from the backup. An accepted Home Assistant service
call is no proof that a light or a door operated; report what happened at the
door. After any reboot the diagnostics show `agent_init_link_ok: true` and a
small `agent_started_after_boot_seconds`.

**Display pages, after step 7,** with the station's keys only (Up, Down,
Return):

1. Main menu: Ringtone, then **Home Assistant**, then **Alarmo**, then the
   station's own items in their usual order. Without a dashboard or without
   Alarmo the matching item is missing.
2. **Home Assistant** opens the dashboard. Up and Down change the page, the
   dots follow, the last entry is **EXIT**; Return on EXIT returns to the menu.
3. Return on a page with controls selects its first control (white bar). Down
   walks through all of them and the page scrolls along; arrows show more
   content above or below. Past the last control the page title is marked again.
4. A light tile opens its detail page on the switch. Select the brightness,
   press Return, change it with Up or Down, press Return: the light follows.
5. **Alarmo** opens the Alarmo page (blue, titled Alarmo). With a PIN the keypad
   follows the modes.
6. Send a display notification without sound: it covers the whole screen and
   Return marks it read. Afterwards Up, Down and Return work again. Also send
   one and, while it shows, ring the station: the call menu reacts to Up, Down
   and Return, and after the call the main menu does too. The same after a
   notification on the Home Assistant page that was still open when the screen
   went off.
7. Settings: **Status messages** stands before EXIT; Return switches it on and
   off, and the routine confirmations on our pages follow.
8. A door call during any of these pages shows the call as usual.

Report what differs, with a photo of the screen.

## Display Activation by Reboot (device test)

Only after steps 1 to 6 passed, and only with Maintenance and its reboot
enabled. Every step reboots the station at most once, and only after it has
been idle for two minutes; do not ring or call meanwhile unless a step says so.

1. **Baseline.** Record `cat /proc/sys/kernel/random/boot_id`, the GUI hashes,
   `ls -l /home/bticino/cfg/extra/c300x-device-file-backups/c100x-display` and `GET /api/v1/maintenance/c100x-display`: `phase` `stock`,
   `confirmed` false, `activate` true.
2. **Activation.** Press **Activate display pages** in HA. Expect `phase`
   `prepared`, `reboot_blocked` `waiting_for_idle`, then one reboot about two
   minutes later. After the boot: a new boot id, `pending.trial-boot` holding it,
   the agent running, and within a minute `phase` `installed`, `confirmed` true,
   `last_result` `confirmed`. HA reloads, the device-UI setting is on and the
   additional pages open from the menu. A call during the wait must postpone the
   reboot (`call_active`/`call_recent`) and never interrupt the call.
3. **Power pull in the trial boot.** Repeat step 2 from a restored station, but
   pull the power within 60 seconds after the trial boot started (before
   `confirmed`). After power returns: the start rolls back, `phase` `stock`,
   `last_result` `rolled_back`, original GUI hashes, the repair "C100X display
   pages were rolled back" in HA, and no further reboot.
4. **Restore.** With confirmed pages, press **Restore original display** (or
   turn the device-UI setting off). Expect `confirmed` false at once,
   `reboot_pending` true, one reboot once idle, and afterwards the original display with
   the original hashes and `phase` `stock`.
5. **Ringer mute, after step 2** (analysis steps 2, 4, 5):
   - Stock path: on the device press Down to mute, then Up to unmute. Each time
     check `[Answering Machine] RingEnable` in
     `/home/bticino/cfg/extra/47/aswm_settings.ini`, `GET /api/v1/ringer`, the
     tile icon and an actual ring.
   - HA mute on/off three times; each time the icon, the ini value, GET, a ring
     and the HA state must agree.
   - Toggle on the device: the HA state follows. Reboot while muted: the icon is
     muted after the boot.
   - An HA command during a call is refused and causes no later change.
   - Unmute from outside the GUI (vendor app): the GUI icon follows within a few
     seconds, and a following HA mute works.
6. Afterwards the ini value, the GUI icon and HA agree.

## Stop Conditions and Recovery

Stop on an unexpected reboot (the display activation's own reboots are
expected), if a vendor call, the BTicino app or a physical key stops working,
if a display file changed outside the display activation, if
`bt_answering_machine` has neither of the two hashes above, if an account or
route target from your backup is missing, or if setup fails. Do not repeat a
failing installation, force a capability, delete backups, restart the vendor
programs or replace SIP accounts to recover.

To go back, in this order:

1. If the display pages are active, press **Restore original display** and wait
   for its reboot and the stock display.
2. Turn the **Home Assistant media user** switch off: the stock routing program
   comes back from its backup; the Flexisip user lines stay.
3. Remove the agent as [Routing and Removal](#routing-and-removal) describes.

### Manual Recovery

If that fails, the files setup wrote can be put back by hand from
`pretest.tar`, one path at a time and only after the agent has stopped
(`pidof c300x-agent-native` returns nothing). Never extract the whole archive
over `/`: it holds the configuration of the BTicino app and of Companion.
Remount `/` writable only for the three paths outside `/home/bticino/cfg` and
return it read-only afterwards.

| Managed path | Pre-test present | Pre-test absent |
| --- | --- | --- |
| `/etc/init.d/c300x-native-agent` | Restore archived file and executable mode. | Remove only the test-created file. |
| `/etc/rc5.d/S40c300x-native-agent` | Restore archived link/file exactly. | Remove only the test-created link/file. |
| `/etc/network/if-pre-up.d/iptables` | Restore archived content, owner and mode. | Remove only the test-created file. |

Remove a firewall rule only when it was absent in `iptables-before.txt` and
setup added it; never flush chains or replay the saved rules. Restoring files
does not unload a display that is already running. If SSH is lost, there is no
automatic recovery: this is the reason for the backup and for stopping early.

## How to Report

Report in [issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51):
**pass / fail / not tested** per step, with the integration version, Home
Assistant version, agent version, reported model and firmware, how long you
observed the station and the exact step that failed. Add the integration's
**Download diagnostics** after removing identifiers and addresses, short log
excerpts, whether the agent is running, whether the display hashes stayed the
same and which of the two hashes the routing program has. For display pages add
a photo of the screen; for card problems the browser, a screenshot and the
console error. Never upload the private archive, configuration files, tokens,
passwords, SIP accounts or the complete routing configuration.

## Package Protection

The package declares itself C100X-compatible in its device bundle. The
declaration is part of the bundle hash; it marks package compatibility, not
proven hardware features.

- Setup recognises a C100X and installs nothing on it until you confirm the
  experimental support in the setup dialog. A C300X is never asked.
- Home Assistant refuses to install or update a C100X from a package without
  the declaration, before any upload or write.
- The C100X agent's own updater refuses a package that is not marked
  C100X-compatible, even when an older Home Assistant sends it. A refused upload
  can leave staging files, never replaced runtime files.
- The SSH installer checks the C100X model, the package declaration and the
  agent's SHA256 before its first write.

These are compatibility guards, not signatures. They do not stop a manual
privileged overwrite or a deliberately relabelled package, and older C300X
updaters do not know them. Do not edit the manifest to force a package through.

## Routing and Removal

The media user patches the routing program `bt_answering_machine` from its
known stock 1.5.8 version and keeps the stock copy as a backup. Restoring needs
the known stock hash and the matching firmware: a backup with that hash, or an
interrupted patch whose known patch ranges rebuild it. Foreign or damaged
files, symlinks and missing targets stop it, and the recovery files stay for
investigation.

Removing the agent restores the original display files and the stock routing
program and verifies both before it deletes the agent or its backups. A failed
restore stops the removal without a reboot. Removal is not a factory reset or
an unroot. Removal and recovery are in test on a C100X.

## Evidence

The C100X work is checked offline against the original firmware: ABI checks of
the agent build, the routing patch on a firmware copy, the display transaction
on firmware copies under the firmware's own shell, and a compile of the
generated display files with the original Qt 5.10.1. One contributor ran an
earlier agent-only package on a modified station with Companion; that was not a
test of a stock station ([field report](c100x-field-report.md)). None of
this replaces the device tests in issue #51. Developer details:
[Display parity](c100x-display-parity.md),
[Audio analysis](c100x-audio-analysis.md),
[Release validation](release-validation.md#c100x-offline-checks).
