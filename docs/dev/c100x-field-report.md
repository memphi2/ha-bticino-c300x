# C100X Field Report Cross-Check

Source: [issue #51, comment 7084550618](https://github.com/memphi2/ha-bticino-c300x/issues/51#issuecomment-7084550618),
posted by `abeilprincipino` on 2026-11-22 at 19:37:32 UTC, read live.
This is a contributor report, not a device test performed by this branch's
developer. Nothing from this branch was installed during that first report.

## First installation on a Companion station

In the [subsequent test on November 23](https://github.com/memphi2/ha-bticino-c300x/issues/51#issuecomment-7102558640),
the reporter installed the test package on C100X 1.5.8. Authentication, model
detection and startup verification worked. Companion kept running; the checked
GUI, media, routing and identity files kept their hashes. This does not establish
compatibility with an unmodified station. Parallel operation with Companion
is not supported. Treat this report as diagnostic evidence, not acceptance
of stair-light or door-unlock operation on a stock installation.

The reporter identified the **agent-only round** as the local ZIP matching
`58310042` (reported SHA-256 prefix `fa3eee15`), not the
[later standalone attachment](https://github.com/memphi2/ha-bticino-c300x/issues/51#issuecomment-7105073876).
The station used WLAN and root2 SSH; HA was Container 2026.11.2 with Python
3.14.10 and uv 0.13.6. No-token API access returned 401. The init check and
`startup_link_ok` passed **in that boot**.

- The station lacked the vendor IPv4 firewall hook. The reporter supplied a
  placeholder for that test; **do not repeat this workaround**. Restoring a
  stock firewall on a modified device could also cut off maintenance access.
  Current HA bootstrap skips an absent hook **before** writing payloads,
  disables agent IPv4 firewall management and leaves live rules alone. A
  symlink at the hook or in its directory path, or a non-executable hook,
  stops installation before writes. Skipping does not guarantee reachability.
  Run on its own without the hook, `bootstrap_firewall.sh` no longer exits 1:
  it adds the live rules for the API (and media, when enabled) and writes no
  file, so nothing persists across a reboot.
- HA reported `installer_dependency_missing` even though dist-info for the
  pinned AsyncSSH was present. Repeating the form did not help; checking
  configuration under Developer tools > YAML cleared HA's failed-install
  history and the next submit worked. The original resolver/import failure
  was not captured. Check the logs; do not change the pin, log private index
  URLs or bypass HA's resolver. The installer now reads the installed version
  with fresh import caches, logs which of its own pins HA reported and the
  installed asyncssh version, and the error text puts the configuration check
  first.
- The tested package enabled video and opened media ports at bootstrap. RTSP
  listening is not evidence of successful video. The reporter did not start a
  stream, and a second SIP session can conflict with Companion.
  The owner decided that video is a core function: a fresh C100X bootstrap
  writes `video.enabled: true` and opens the media ports exactly as on a C300X.
  An explicit existing video choice is kept, and old live rules are not
  closed. Separately, the
  contributor reports quality `#0` was ACKed but sent no RTP to the external
  destination, while `#1` gave 640x480. That agrees with the enforced Qt5
  low selector, not proof of an agent RTSP stream, capture, or talkback.
- The active SIP route is a regular file on this installation. Do not convert
  it to a symlink or replace it to pass the media-user check.
  The expected self-test result is `unsupported_active_route`; the text-only
  fixture below does not grant permission to edit the live file.
- The reporter restored the recorded baseline **manually**. Neither reboot
  survival nor the packaged removal script was tested on hardware.
  An earlier post-boot sweep reportedly stopped **Companion** started at S45.
  There is no observation that it killed this agent at S40. Do not add a
  respawn guardian or call startup-link verification a reboot test.
- The reporter observed that terminating the GUI rebooted this station and
  touching the vendor configuration restarted the whole stack. Neither is a
  safe GUI reload for this test package.
  Specifically, TERM to `BtClass100` reportedly rebooted the station;
  touching `/var/tmp/conf.xml` disrupted the bus for about 23 seconds. Keep
  both operations out of the agent-only test. The GUI followed bus mute but
  not unmute on the tested LCM channels; its state was
  `global.audioState.isRingtoneMute`. Offline this is the stock parser: it
  turns only a mute status into the GUI flag, and only the GUI's own
  `disableState(RingtoneMute)` clears it. Two-way mute is therefore advertised
  only on a confirmed display adapter, which writes both directions through
  AudioState, and the agent pushes an outside unmute to the GUI. Both still
  need the device test in the Classe 100X notes.
  The reporter identified a ZL38067 DSP; that is not audio-path validation.
- Discovery did not find this station; **manual setup by host succeeded**.
  There was no agent before SSH installation, the responder closes while HA
  is connected, and HA and the station were on different subnets. This run
  neither proves nor disproves discovery on one multicast segment. It does
  not justify keeping port 5353 open after connection.

## Evidence And Limits

### Firewall layouts seen in firmware and community projects

| Source | Evidence | Installer consequence |
| --- | --- | --- |
| C100X 1.5.8 stock image | `S01networking` starts `ifup -a`; WLAN is an automatic interface. The BusyBox ifup binary contains the `run-parts /etc/network/if-%s.d` hook dispatch. The IPv4 hook clears INPUT and sets its policy to DROP. Its SHA-256 is `737cf33df612f090c54505a6bdb283dd27a4d8df623837bee4d9941855235b0b`. The [firmware-tools comparison](https://github.com/daniel-sc/bticino-c100x-firmware-tools/blob/55f8aa5afe4d2e90c23d57f932a620598a6c1723/docs/WIRELESS-UPDATES.md) records the same hash for main and recovery. | Check both the live rules and the persistent hook. Do not execute the stock hook to test configuration: it replaces live INPUT rules. |
| [c300x-controller installer](https://github.com/slyoldfox/c300x-controller/blob/4234a37d0ebb009b54893e82597f1e482dab9ff2/install.sh) | One installation path edits the existing hook; another moves both vendor hooks to backups. | A present hook need not be stock, and an absent hook need not mean a missing firewall tool. Preserve other software's changes and backups. |
| [fquinto SIP guide](https://github.com/fquinto/bticinoClasse300x/blob/dc6071638a566e3cee392024683b3480668bbc79/sip/README.md) | Describes both a live policy change and moving the hooks. This is an optional SIP procedure, not evidence that every rooted installation has this layout. | Neither the existence of a backup nor the absence of the original determines the live policy. |

An offline dry run of the original ARM BusyBox 1.27.2 `ifup` under QEMU with
the shipped interfaces file printed the pre-up hook directory before the WLAN
link command, then the up hook directory. This confirms dispatch order, not
that a proposed hook works on a real boot.

On the reported station the contributor observed INPUT ACCEPT and rules
installed by Companion. An ACCEPT rule of our own would not restrict access
under that policy. Conversely, restoring the vendor hook would not preserve
the system the contributor is using. The source comparisons do not identify
which tool changed that particular station.

- The reported device is C100X Door Entry 1.5.8, ARMv7, with Companion already
  running. Manufacturer app/cloud deployment provisions vendor SIP accounts, as
  clarified by the maintainer and supported by the original firmware below.
  The comment explicitly attributes both `c100x` and `companion` to Companion,
  but that attribution is not independently established and must not be adopted
  as the origin of the vendor accounts. Account presence alone proves no author.
- The posted active route contains a `companion` destination alongside two app
  destinations. The contributor reports changes to `route.conf`, `route_int.conf`
  and `users.db.txt`; no before/after files were supplied. Distinguish that
  reported modification history from the directly visible additional target.
  Preserve all existing provisioned accounts and routes, regardless of origin.
- All three reported whole-file SHA256 values match the locally extracted
  original 1.5.8 `bt_answering_machine`, `bt_av_media` and `libc-2.27.so`.
  This supports those specific binary identities, not whole-device integrity.
  GUI/wrapper/QML hashes were not supplied, so display identity remains unverified.
- The contributor reports a successful rw/ro root remount, ending read-only.
  This does not test our install, interruption recovery or reboot behavior.
- OpenWebNet returned `*#8**33*1##` and `*#8**41*100##`. Existing parsers accept
  these as unmuted and volume 10/10; acknowledgements alone are not state.
  This is readback evidence only, not mute/volume write or persistence proof.
- Reported framebuffer virtual sizes are 800x960/800x1440, with fb0 changing
  during app video and fb1 staying 800x1440. Original QML remains 800x480;
  its wrapper selects fb1 and three buffers. Buffer allocation is consistent
  with these heights but is not a measurement of panel or encoded video size.
  No display resizing or High-video geometry change follows from this report.
- Flexisip is reported under comm name `flexisipwd-prox`; absence from a
  simplistic process-name filter is not absence of the service. The supplied
  command line identifies the executable. Agent, installer and scripts do not
  rely on a Flexisip process-name search; this is not a compatibility blocker.
- `openserver` and `scsserver` are original firmware binaries, both listed in
  `stack_open.xml`. The stock configuration identifies SCS port 20001 and OWN
  port 20000. The readback therefore does not depend on a Companion-provided
  OWN server. The helper's classification of scsserver as non-stock was wrong.
  A missing separate `openserver` process name does not disprove the service;
  whether another bt_daemon process hosts it has not been established.
- `command -v start-stop-daemon` reportedly failed. The original image contains
  a BusyBox link in `/sbin` and a standalone binary in `/usr/sbin`; our init
  script sets both in PATH. The original BusyBox applet accepts our stop options
  with an absent temporary PID file under QEMU. That checks option parsing only,
  not timed termination. The maintainer clarified that the helper shell lacked
  sbin in PATH; no new fallback or tool-path question is required. Removal
  already has its killall fallback. The Python installer and C agent do not
  invoke this tool directly.
- Companion and mosquitto were reported running. Credentials, route
  regeneration, registration and media lifecycle coexistence
  remain unproven. Do not overwrite/remove their state or suggest a concurrent
  experimental install yet.

## Original Provisioning Path

The extracted 1.5.8 image links `/etc/flexisip` to the persistent
`/home/bticino/cfg/extra/90/flexisip` tree. Its vendor `flexisip.conf` uses
`users/users.db.txt` for authentication and `users/route.conf` for static routes.
The original `bt_eliot` contains `sipAccounts`, `START ask sip users`,
`Sip user result: %s (%d)` and `/var/tmp/user_list.txt`. The original
`bt_answering_machine` contains that same handoff path, `SipUsers`,
`Refresh sip user list`, `users.db.txt`, `accounts.txt`, internal/external route
paths and the `c100x` identity. C300X 1.7.19's answering-machine binary has the
same user-list/file markers and its `c300x` identity.

These are static vendor provisioning artifacts, not a live cloud trace or proof
of who created a particular row on the reported device. They rule out treating
vendor SIP provisioning as something that inherently requires Companion. An
empty extracted persistent tree is not evidence that app deployment lacks users.

## Local Follow-Up

`tests/test_c100x_field_report.py` checks the three binary hashes, original
logical layout/buffering/tool paths and the actual C ringer parsers. A redacted
Companion-style route fixture exercises real target insertion, idempotence and
removal; the original app and Companion destinations survive byte-identically.
This narrow transformation test is not proof of complete Companion coexistence.

Tool PATH, stock OWN service, Flexisip process naming and the three specific
binary identities are cleared offline, not outstanding questions. Preserve
provisioned accounts/routes. GUI/wrapper/QML identity and the
[display activation by reboot](../c100x-experimental.md#display-activation-by-reboot-device-test)
remain hardware acceptance checks. Display capabilities stay false until that
activation is confirmed in its trial boot; the matching hashes are not
permission to activate a device.
