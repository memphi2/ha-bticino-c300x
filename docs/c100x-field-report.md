# C100X Field Report Cross-Check

Source: [issue #51, comment 7084550618](https://github.com/memphi2/ha-bticino-c300x/issues/51#issuecomment-7084550618),
posted by `abeilprincipino` on 2026-11-22 at 19:37:32 UTC, read live.
This is a contributor report, not a device test performed by this branch's
developer. Nothing from this branch was installed on that device.

## Evidence And Limits

- The reported device is C100X Door Entry 1.5.8, ARMv7, with Companion already
  running. Companion changed the SIP users and route files. `c100x` and
  `companion` were reportedly added by Companion; their presence must not be
  treated as evidence of untouched vendor provisioning.
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
  command line identifies the executable. No `openserver` process was reported,
  but OpenWebNet answered; do not make that name a readiness prerequisite.
- `command -v start-stop-daemon` reportedly failed. The original image contains
  a BusyBox link in `/sbin` and a standalone binary in `/usr/sbin`; our init
  script sets both in PATH. The original BusyBox applet accepts our stop options
  with an absent temporary PID file under QEMU. That checks option parsing only,
  not timed termination. Confirm the tester's paths/PATH before adding fallbacks.
- Companion, mosquitto and scsserver were reported running. Port ownership,
  credentials, route regeneration, registration and media lifecycle coexistence
  remain unproven. Do not overwrite/remove their state or suggest a concurrent
  experimental install yet.

## Local Follow-Up

`tests/test_c100x_field_report.py` checks the three binary hashes, original
logical layout/buffering/tool paths and the actual C ringer parsers. A redacted
Companion-style route fixture exercises real target insertion, idempotence and
removal; the original app and Companion destinations survive byte-identically.
This narrow transformation test is not proof of complete Companion coexistence.

Before a device trial, audit full media-user/account transactions and service
port ownership with this modified baseline. Request the Companion version,
explicit daemon-tool paths and GUI identity hashes read-only, with no SIP
passwords, full user databases or unredacted device identifiers. Display
capabilities remain false pending supervised activation/readiness/rollback.
