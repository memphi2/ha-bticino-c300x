# Classe 100X: Setup

**Step 1 of 5:** **1. Setup** | [2. Use](2-use.md) | [3. Station display](3-display.md) |
[4. Troubleshooting](4-troubleshooting.md) | [5. Update and removal](5-update-and-removal.md)

This page takes a Classe 100X from SSH access to a working doorbell card in
Home Assistant.

## Status: Experimental

Support for the Classe 100X on firmware `1.5.8` is built and checked against
the original firmware, but not yet confirmed on a Classe 100X. Testing runs in
[issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51). Use a
station you can do without for a while, ideally with a separate Home
Assistant test instance. What works and what does not:
[2. Use](2-use.md#what-works). Testers make a private backup first:
[C100X device test](../dev/c100x-device-test.md#make-a-private-backup).

## Requirements

- Home Assistant `2026.10.0` or newer.
- A Classe 100X with the original firmware `1.5.8`, changed only to enable
  SSH.
- The station is set up in the BTicino Door Entry app.
- No BTicino Companion or other controller on the station.
- Home Assistant and the station are in the same trusted local network.

## Enable SSH on the Station

The integration needs root access to the station over SSH. It cannot root a
stock station itself, and this project provides no firmware images, no tools and
no rooting instructions.

Enable nothing but SSH: no camera, MQTT or other extras. Flashing can brick
the station; you do it at your own risk and without warranty.

## Install the Integration

[![Open your Home Assistant instance and open this repository in the Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=memphi2&repository=ha-bticino-c300x&category=integration)

The Classe 100X needs `3.0.0` or newer.

**Home Assistant 2026.11 or newer:**

1. Open the button above, or go to **Settings > Marketplace**.
2. Find **BTicino C300X/C100X** and install it.
3. Restart Home Assistant if it asks you to.

**Home Assistant 2026.10:**

1. Open **HACS** and search for **BTicino C300X/C100X**.
2. Download it and restart Home Assistant.

## Add the Station

1. Go to **Settings > Devices & services > Add integration** and choose
   **BTicino C300X/C100X**.
2. Enter **Address of the C300X/C100X** (the station's IP address; give it a
   fixed address in your router) and **Port** `8091`. Leave **Address of Home
   Assistant for the C300X/C100X (optional)** empty.
3. The dialog **Native agent not found** appears. Tick **Install native agent
   on the C300X/C100X** and submit.
4. Home Assistant logs in with the station's factory login (checked against
   the original firmware only). If the station refuses it, enter your own SSH
   user (`root`), its password or a private key (RSA or ECDSA).
5. Home Assistant recognises the Classe 100X and shows **Classe 100X:
   experimental support**. Tick **Set up the experimental Classe 100X
   support** and submit. Nothing is changed on the station before this.
6. Wait until the installation is done. The SSH login is not stored.

## Choose Options

| Setting | Choose |
| --- | --- |
| **Door station video and audio** | On. |
| **Set up video and audio access on the C100X** | On. |
| **Door level** | Stock. |
| **Fine adjustment (dB)** | `0`. |
| **Connection paths for the live picture** | **IPv4 and local IPv6 (ULA) - recommended**. Change it only when the live picture does not connect ([choices](../reference.md#connection-paths-for-the-live-picture)). |
| **Talk through the Home Assistant camera view** | Off. |
| **Visitor Snapshot** | Keep the defaults. |
| **Additional device activations** | Leave empty. |
| **Alarmo** | Leave empty. |

The display pages come later, with one reboot:
[3. Station display](3-display.md).

## Check Media Readiness

Open the **Media readiness** sensor on the device page. Ready or Warning:
continue. Blocked or Unavailable: open **Settings > Repairs** and run the
offered fix.

## Add the Card

Run **Add the C100X Lovelace card** in Repairs, or add the **BTicino Doorbell
Call Card** to a dashboard yourself and select the station's camera entity.

## First Test

Do these steps in order and stop at the first failure.

| # | Do | Expected |
| --- | --- | --- |
| 1 | Check the device page. | Model Classe 100X, firmware 1.5.8. |
| 2 | Press **Stair light** once. | The light comes on. |
| 3 | Press **Door unlock** once, with someone at the door. | The door opens. |
| 4 | Press **Stream** in the card. | Picture and sound; the stream ends cleanly. |
| 5 | Set **Forwarding** to **Home Assistant**, ring, press **Answer**. | Picture, both directions of sound, **Hang Up** works. |
| 6 | Move the picture sliders in the card. | The picture changes. |

Also check that the station's own keys and the BTicino app still work.

Report each step as pass, fail or not tested in
[issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51), with the
integration, Home Assistant and agent versions and the integration's
**Download diagnostics** (remove addresses first). Never upload the backup
files, passwords or keys.

Testers who want to go further: [C100X device test](../dev/c100x-device-test.md).

To go back to the original station, see
[5. Update and removal](5-update-and-removal.md#go-back-to-the-original-station);
to remove the entry and the package from Home Assistant, see
[Remove the integration](../classe-300x/5-update-and-removal.md#remove-the-integration).

**Next: [2. Use](2-use.md)**
