# Root and SSH Access

Home Assistant installs the device agent over SSH once. A stock station has no
SSH login you can use, so it needs a one-time change with a third-party tool
first. This page lists the community tools we know of, which station and
firmware each one names, and what to choose for this integration.

This project provides no firmware images, APKs, exploits, rooting instructions
or vendor files, and it is not affiliated with these tools, BTicino or Legrand.
Each tool is a third-party project, used at your own risk and without
warranty; follow its own documentation. Modifying a station can brick it. Keep
a copy of the original firmware, and a backup of the station where the tool
makes one, before you start.

## Tools

| Station and firmware | Tool | Runs on | Notes |
| --- | --- | --- | --- |
| C300X `1.7.17`, `1.7.19` | [fquinto/bticinoClasse300x](https://github.com/fquinto/bticinoClasse300x) | Linux with Docker, or Python 3 with `sudo`; flashing with BTicino's MyHOME Suite on Windows | Builds a modified `.fwz` from the official one. Tested by its author on a Classe 300X13E (hardware 2.0) with both versions; its C100X option is marked as not validated there. Login afterwards: `root2`. |
| C300X `1.7.17`, `1.7.19`; C100X `1.5.8` | [jorgeavlobo/intercom-firmware-tool](https://github.com/jorgeavlobo/intercom-firmware-tool) | Windows x64; flashing with MyHOME Suite | A Windows app that produces the same result as fquinto's script. Modifies Door Entry firmware of the Classe 300X13E (344642 / 344643) and the Classe 100X16E (344682). Login afterwards: `root2`; the factory `root` stays unchanged. Since v1.1.0 it avoids MyHOME Suite error 1063 on the 300X13E. |
| C300X (344642) `2.0.2`, `3.0.6` | [davemajor/c300x-root](https://github.com/davemajor/c300x-root) | A computer with a 3.3 V USB-UART adapter and a USB cable | Works on the opened circuit board over a serial console and USB recovery, with soldering; it can destroy the station. Login afterwards: `root` with the password chosen when building. |
| C100X `1.5.8` | [daniel-sc/bticino-c100x-firmware-tools](https://github.com/daniel-sc/bticino-c100x-firmware-tools) | Apple Silicon Mac or x86-64 Linux; USB flashing on Ubuntu 24.04 / 26.04 Desktop is experimental | Builds and flashes over USB without SSH beforehand. Accepts hardware family `02.*.*`. Login afterwards: `root2`. |

The firmware column lists what each project states for itself, limited to the
firmware this integration supports. Read the project's own page for the current
state before you start.

## Hints

- **Choose only SSH.** Some tools also offer an MQTT bridge, a camera stack
  (ffmpeg, go2rtc, RTSP), Home Assistant discovery or a bridge of their own.
  These run next to the device agent on the same station, share its video and
  firewall, and are not tested together with this integration. Prefer to leave
  them off.
- **Firmware version.** Where a C300X tool asks for a firmware version, choose
  `1.7.19`.
- **Keep a password login.** Setup connects to a station with an RSA, ECDSA or
  ed25519 host key and logs in with a user name and password only; SSH keys
  are not supported. It tries the station's factory login first and asks for a
  user and password only if the station refuses it. Enter the account the tool
  created and the password you chose: `root2` for fquinto's, jorgeavlobo's and
  daniel-sc's tools, `root` for davemajor's. Do not build a key-only image or
  turn off password login in the tool. Setup uses the credentials for the
  installation only and does not store them.
- **Firmware families do not mix.** A C300X on `1.7.x` or `2.0.2` never updates
  to `3.0.x`; firmware `3.0.6` needs hardware revision 4. Use a tool made for
  the firmware the station has now.
- **Vendor updates.** Blocking them is the tool's choice: daniel-sc's and
  davemajor's tools block them by default, jorgeavlobo's offers it as an
  option. A vendor update can overwrite the modified firmware and remove SSH
  access.

Next: [Quick Start](quickstart.md#install-the-device-agent).
