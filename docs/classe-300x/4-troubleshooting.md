# Classe 300X: Troubleshooting

This page helps when the card, calls, sound, picture or the station display
do not work.

Pages: [1. Setup](1-setup.md) | [2. Use](2-use.md) |
[3. Station display](3-display.md) |
[5. Update and removal](5-update-and-removal.md)

Start every check with the **Media readiness** sensor and **Settings >
Repairs**.

## Media Readiness

| State | Meaning | Do this |
| --- | --- | --- |
| Ready | Everything needed for video and calls works. | Use the card. |
| Warning | Works, but something is not confirmed. | Read the `warnings` attribute. A forwarding warning only means ring calls go to the phone. |
| Blocked | Something needed is missing. | Open **Settings > Repairs** and run the fix. |
| Unavailable | Home Assistant cannot reach the agent. | Check that the station is on and its address is right ([address changed](#the-station-has-a-new-address)). |

The `failed_checks` attribute names what is missing:

| Check | Fix |
| --- | --- |
| `agent_reachable` | Check the address, port and keys. Restart or update the agent. |
| `capabilities`, `rtsp`, `startup` | Run **C300X device agent update required** if Repairs offers it, else **C300X media setup checks failed**. |
| `firewall`, `talkback_rtp` | Run **C300X media setup checks failed** in Repairs. |
| `homeassistant_user`, `device_routing` | Run **C300X media user setup required** in Repairs. |
| `callback_url` | Fix the address of Home Assistant ([below](#events-or-display-pages-do-not-reach-home-assistant)). |

After a Repair that changes the station, wait until it is done and check
readiness again.

## Stream Shows No Picture

1. **Door station video and audio** is on under **Configure > Video and
   audio**.
2. Media readiness is Ready, or Warning about forwarding only.
3. No other viewer or recording uses the camera. Press **Stop doorbell
   video** on the device page, then try again.
4. Right after an agent update, reload the integration once.
5. On a network with VLANs or IPv6, try another
   [connection path](../reference.md#connection-paths-for-the-live-picture),
   then close the stream and open it again.

## The Card Shows Stream Instead of Answer

The card shows **Answer** only for a real ring call.

1. Set **Forwarding** to **Home Assistant**.
2. Ring again after changing it.
3. Media readiness shows no `homeassistant_user` or `device_routing` failure.

If the diagnostics show `unsupported_active_route`, another tool changed the
station's call routing. The integration leaves it alone; report it.

## Answer Fails

1. Close old browser windows with the card.
2. Make sure no ring recording runs at the same time.
3. Reload the integration if the card was open during an agent update.

## Talking Does Not Work

- Open Home Assistant over HTTPS or Home Assistant Cloud and allow the
  microphone in the browser.
- From a phone notification, open the card and answer there.
- Talking in Home Assistant's own camera view needs the option **Talk through
  the Home Assistant camera view** and **Two-way audio** in **Settings >
  System > Labs**. Answer in the card first.

## Sound Is Too Quiet or Too Loud

Change **Door level** and **Fine adjustment (dB)** under **Configure > Video
and audio** ([details](2-use.md#door-level-and-fine-adjustment)). For clearer
sound set **Audio codec** to **PCMU**.

If the station restarts during a PCMU stream, set **Audio codec** back to
**Speex** and report it.

## Picture Problems

| Problem | Try |
| --- | --- |
| Blurry or blocky | Raise the bit rate under **Configure > Camera quality**. |
| Grey blocks or stalls | Lower the bit rate. |
| Jerky | Raise the frame rate. |
| Top and bottom cut off | Choose 704x576. |
| 960x576 not offered | It needs the exact media program of `1.7.19` or `2.0.2`. Do not force it. |
| No change after saving | The station must restart first. Wait, then open a new stream. |
| Visitor image squeezed or with bars | Set **Visitor Snapshot** to 800 x 480 or 400 x 240. Old images stay as they are. |

## Home Call Looks Connected Too Early

Home Call is audio only. If the display rang but nobody answered, hang up in
Home Assistant once. If the next stream fails, stop it and check readiness.

## Recording Fails

- With **Include audio** a recording answers the ring call; without a ring it
  fails. Use `capture_mode: on_demand` for a recording without a ring.
- A recording without a ring needs the camera free: close your live view.
- Only one recording per station at a time.
- Files must go below `/media/c300x/`, `/config/c300x/` or
  `/config/www/c300x/`.

## The Station Has a New Address

When the station gets a new IPv4 address, Home Assistant finds it again by
itself. That can take about 15 minutes; meanwhile readiness shows
Unavailable.

Enter the new address yourself with **Reconfigure** on the integration when:

- you entered a host name or an IPv6 address;
- **Agent mDNS discovery** is off;
- the log says the station "did not prove the saved identity": check that it
  is your station and that the access key is right;
- you do not want to wait.

A DHCP reservation in your router avoids this.

## Events or Display Pages Do Not Reach Home Assistant

The station sends rings and display requests to the **Address of Home
Assistant for the C300X**. Empty is right for most homes.

If Repairs shows **C300X callback URL is not usable by the device agent**,
run it and accept the suggested address, or enter one yourself under
**Configure > Connection to the C300X**:

- Use an address the station can reach directly, for example
  `http://192.0.2.10:8123`.
- Do not use `homeassistant.local`, `localhost` or an internet-only address.
- `https://` needs a trusted certificate for that host name. Display picture
  tiles need `http://`.

HTTPS for your browser does not need HTTPS here.

## Display Problems

| Problem | Do this |
| --- | --- |
| Repairs: **C300X display pages still have to be applied after the update** | Run it. The display goes dark and restarts. |
| Repairs: **C300X display write left unfinished** | Check the display. Turn the **Display patch** switch off and on; this rebuilds every display file. If the message stays, reboot the station. A folder `.c300x-qml-transaction.*` from agent 2.9.0 or older is never restored: once the display works, delete it over SSH from `/home/bticino/bin/gui/skins/default`. |
| Repairs: **C300X display pages are not available on this station** | The agent does not know this display. The station keeps its original display; report it. |
| The house symbol has a yellow mark | The station cannot reach Home Assistant. Open the **Integration** tab for the reason ([list](3-display.md#integration-tab)). |
| A Settings page of an unknown layout | The Display patch stops instead of guessing. Report it. |

## The Station Keeps Restarting (Firmware 3.0.6)

If the station keeps restarting after an install, an update or saving the
display settings:

1. Between two restarts, log in over SSH and rename the display file:
   `mv /home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc /home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc.hang`.
   The next start uses the original display.
2. Remove the pages and the core hook:
   `/home/bticino/cfg/extra/c300x-native-agent/qml_patch.sh restore-all`.
   Its last line contains `"qt5_overlay":"off"`. If it answers `An unfinished
   GUI write is still in place`, wait a minute and run it again.
3. If the restarts began after an install from Home Assistant or after saving
   the display settings, also turn off **Home Assistant pages on the display**.
4. Until you have reported it, do not use the core hook Repair, the **Display
   patch** switch or an agent update: each writes the display file again.
   Keep `display-qt5.rcc.hang` and `/tmp/c300x-display-qt5.log` for the
   report.

## Update or Removal Reports an Error

Do not delete backup or recovery files and do not force the step. Run the
agent update Repair again; an update cut off by a power loss is finished or
undone by the next one. If removal fails, the agent starts again so you can
retry; follow the message.

## Reporting a Problem

Open an issue at <https://github.com/memphi2/ha-bticino-c300x/issues> with:

- Home Assistant version, integration version, agent version and firmware;
- the Media readiness state and its attributes;
- the **Forwarding** setting;
- the integration's **Download diagnostics** file;
- the relevant log lines.

Do not include keys, passwords, private addresses, recordings or network
captures.
