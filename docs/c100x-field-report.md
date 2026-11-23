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
compatibility with an unmodified station.

- The station lacked the vendor IPv4 firewall hook. The reporter supplied a
  placeholder for that test; **do not repeat this workaround**. Restoring a
  stock firewall on a modified device could also cut off maintenance access.
- The tested package enabled video and opened media ports at bootstrap. RTSP
  listening is not evidence of successful video. The reporter did not start a
  stream, and a second SIP session can conflict with Companion.
- The active SIP route is a regular file on this installation. Do not convert
  it to a symlink or replace it to pass the media-user check.
- The reporter restored the recorded baseline **manually**. Neither reboot
  survival nor the packaged removal script was tested on hardware.
- The reporter observed that terminating the GUI rebooted this station and
  touching the vendor configuration restarted the whole stack. Neither is a
  safe GUI reload for this test package.

## Evidence And Limits

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
provisioned accounts/routes and finish the supervised activation/readiness/
rollback path. GUI/wrapper/QML identity and actual activation remain separate
hardware acceptance checks. Display capabilities remain false until that path
is complete; the matching hashes are not permission to activate a device.
