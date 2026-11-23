# Quickstart

Follow these steps for a first installation. No YAML or manual card setup is
required.

```text
Install integration -> add device -> install/update agent -> check Media readiness
-> add the C300X card
```

## Before You Start

You need:

- Home Assistant `2026.10.0` or newer.
- A BTicino Classe 300X / C300X on firmware `1.7.x` or `2.0.2`.
- Root or SSH access on the C300X for the first device-agent installation.
- A trusted local network between Home Assistant and the C300X.

This integration cannot root a stock device. If a separate rooting or
SSH-enablement workflow asks for a firmware target, use `1.7.19`. A device on
firmware `2.0.2` needs a rooting workflow made for that firmware.

## 1. Install Through Marketplace or HACS

### Marketplace: Home Assistant 2026.11+

[![Open your Home Assistant instance and open this repository in the Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=memphi2&repository=ha-bticino-c300x&category=integration)

1. Open the button above, or go to **Settings > Marketplace**.
2. Find **BTicino C300X**, install it and confirm the community-integration notice.
3. Follow any restart request before continuing.

### HACS: Home Assistant 2026.10

1. Open **HACS**.
2. Search for **BTicino C300X**.
3. Install it.
4. Restart Home Assistant.

No custom repository is needed. If the search finds nothing, refresh the HACS
catalog before retrying.

Both installation methods use the same repository and release archive. Existing
configuration entries and bundled cards remain unchanged when moving to Marketplace.

## 2. Add the Integration

In Home Assistant:

```text
Settings -> Devices & services -> Add integration -> BTicino C300X
```

Enter the C300X IP address and the device-agent API port. For normal installs
the API port is `8091`.

## 3. Install or Update the Device Agent

If the agent is not reachable yet, the setup flow offers an installer step.
Use it only on a rooted or SSH-enabled C300X.

If an older agent is reachable, Home Assistant may show an agent-update Repair.
Run that Repair before testing camera or call features.

Apply the core GUI hook when Repairs requests it, then reload the device GUI.
This hook is separate from the optional Home Assistant display pages. It is
needed for media state tracking and synchronized ringer mute/unmute.

The installer logs in with the C300X factory root login. It asks for an SSH
user and password only when the device refuses that login. Typed credentials
are one-time setup inputs. They are not stored in the Home Assistant config
entry, diagnostics or logs.

## 4. Choose the Standard Feature Set

Recommended first-run choices:

- Enable **Door station video and audio** when you want camera, Ring Call,
  Home Call or talkback.
- Keep **Set up video and audio access on the C300X** enabled for media
  features.
- Leave **Live audio level (dB)** at `0 dB` for the first test.
- Leave **Volume of ring recordings (dB)** at its default unless you use Ring
  Capture.
- With video enabled, the **Visitor Snapshot** step follows; its defaults
  (800x480, 3 seconds, 14 days, date and time in the image) are fine for a
  first test.
- Leave **Additional device activations** empty unless you already know the
  C300X activation addresses you want as Home Assistant buttons.
- Leave **Home Assistant pages on the display** off unless you want them on
  the C300X display.
- Select Alarmo and weather entities only if you use those display pages.
- Leave destructive maintenance controls disabled until needed.

Feature choices can be changed later from the integration options.

For **Connection paths for the live picture**, keep the default
**IPv4 and local IPv6 (ULA) - recommended** unless your network needs another
policy. See [all four ICE choices and their exceptions](media-troubleshooting.md#connection-paths-for-the-live-picture)
before changing it; this field does not configure device callbacks or a firewall.

## 5. Check Media Readiness

After setup, open the `Media readiness` diagnostic sensor.

- **ready**: continue with the Lovelace card.
- **warning**: basic media can work. Smartphone forwarding intentionally warns
  that Ring Calls are not answerable from Home Assistant; it does not block
  on-demand media.
- **blocked** or **unavailable**: open the Repair issue and press **Fix now**.

Do not debug the card before this entity is `ready` or shows only warnings you
understand.

Details: [Media readiness](media-readiness.md)

## 6. Add the Lovelace Card

After Media Readiness is ready or shows only understood warnings:

1. Open the dashboard where you want the C300X card.
2. Add a card.
3. Select **C300X Doorbell Call Card**.
4. Choose the C300X camera entity.

Use one normal card in **Doorstation + Home Call** mode (`mode: auto`) for Doorbell, On-demand and Home Call.
Use separate Doorbell/Home Call modes only for hand-built special dashboards.
The card shows the Media Readiness line by default. Disable that line in the
card editor only if you want a cleaner dashboard.

If Home Assistant shows a C300X Lovelace card Repair after an update, run it
once. It refreshes the generated C300X dashboard view and replaces old generated
split-card layouts with the current consolidated card.

After an update, hard-reload the browser or clear the Home Assistant frontend
cache if the card still looks old.

## 7. Test the Three Media Paths

Test in this order:

1. **On-demand**: press Stream in the card.
2. **Home Call**: start and stop a Home Call from the card in **Doorstation + Home Call**
   mode.
3. **Ring Call**: set **Forwarding** to **Home Assistant**, ring the doorbell,
   then press **Answer** in the card.

Talkback needs a secure Home Assistant frontend: HTTPS, Home Assistant Cloud or
another secure browser context with microphone permission.

## 8. Visitor Images and Automations

With video enabled and the matching agent installed, **Save images** is enabled
by default on the C300X device page. A ring or video session requests one image
after **3 seconds**, even with every dashboard closed. The agent only reads the
existing camera framebuffer; JPEG conversion and storage happen in HA.

- Open **Media > BTicino C300X Media** to browse saved images.
- Change image size, delay, retention and the date and time in the image
  under **Configure > Visitor Snapshot**. Retention defaults to **14 days**,
  the size to **800x480**, the native display framebuffer at **5:3**. Saved
  sizes, including the old 688x480 setting, are not migrated automatically.
  Select 800x480 explicitly to change future captures; existing images stay
  unchanged. A 960x576 live stream does not increase snapshot resolution.
- Turn **Save images** off to stop new captures and hide the shared card/camera
  preview. Existing archives remain until they expire.
- Images use the configured HA media directory, like recordings. Its normal
  media-access permissions also apply; camera permission alone does not hide
  images from HA's local-media browser.

See [Visitor images](feature-reference.md#visitor-images) for limits and behavior
when a call or stream ends before the capture delay.

Ready-made blueprints are available for doorbell notifications, Ring Call
notifications, capture, Wyoming transcription and strict phrase decisions. They
are installed into Home Assistant's blueprint folder when the integration loads.

Details: [Blueprints](blueprints.md)

## 9. Optional Native Display

These pages run on the C300X itself in its blue interface; they are not the
Lovelace card or an embedded HA dashboard.

1. Update the bundled agent, then turn on **Home Assistant pages on the display**
   under **Configure > Display > Display and Display patch** and save. After the
   integration has reloaded, the Display patch is applied, which restarts the
   device GUI; saving with the option off restores the original display. The
   **Display patch** switch on the device page does the same and saves the
   option with it.
2. Open **Display > Display pages** and pick a page from the list. Choose an optional weather entity, name your pages,
   set their order and select the entities for each. Five built-in pages
   (Status, Energy, Agenda, Leave home and Situations) and up to seven custom
   pages are available. Set all
   positions from 1 to 12; defaults are Energy 2, Agenda 10, Leave home 11 and
   Situations 12.
   Equal positions put those optional pages in that order before regular pages.
   Disabling an optional page keeps its selections and position.
   Drag entities to reorder their tiles.
   The **Energy** section adds the optional
   [energy page](feature-reference.md#energy-page), which shows Home
   Assistant's Energy setup. Choose its views independently. **Consumers** lists
   the top ten configured devices by current W without history queries.
   Distribution has been removed: enable Consumers explicitly after upgrading;
   the old selection is removed without enabling another view.
   The list follows the order of the display and shows each page's number. A
   page the display does not show (switched off, or without entities) has no
   number and follows the shown pages; **Add a page** adds a custom one. In the
   setup the pages are sections of one form instead, and free sections, titled
   **Page +**, come last. Optional **Agenda** and **Leave home** sections select calendars and departure
   checks explicitly; they are disabled until you enable them. Agenda shows up
   to five events in seven days, using a background HA cache. Leave home actions
   require a second **Confirm** tap and never run when the page opens. The status page
   links directly to every other visible page, below the optional weather card.
3. Open **Display tiles** to set each tile's width, height, name and secondary
   line. Full-height tiles expose supported common controls directly; tap a
   tile with a chevron for its detail controls.
4. For Alarmo, choose the alarm panel under **Alarm (Alarmo)**. Its separate
   subpage can have one optional quick action. Leave it empty to hide the action;
   select the stair-light button explicitly if that is the shortcut you want.

Lights, covers, climate, fans and media players have capability-based controls.
Locks, vacuums, valves, humidifiers and water heaters also have detail controls;
unlocking or opening a lock requires a second tap. Sensors and presence entities
are read-only. Only configured entities can be operated from the display.

After an integration update, update the agent and reapply the Display patch
when prompted so the display receives the matching files. Page and tile
settings themselves are stored in HA, not rewritten to the device on every change.
The display pages and [standard Notify service](feature-reference.md#standard-notify-service)
require the matching agent and display bundle. Notify defaults to 30 seconds of
wake and sound for all three severities: `info`, `warning` and `error`. Set
`sound_duration: 0` explicitly for a silent notification. Effects are limited to
safe Home/HA screens, never queued until the next wake, and are supplementary,
not fire-alarm functionality. A protected screen or call suppresses the effects
and leaves the notice in HA; a missing GUI connection reports a delivery error.
For an unread notice without a popup, screen wake, tone or speech, set
`mode: led` in the notification's nested `data` and omit effect settings.
This requires an agent that reports memo LED support. Success confirms the
notice was stored in HA, not that the device LED changed.
With `mode: speech` or `mode: both` the message is spoken over the device
loudspeaker instead of the tone; see
[Speaker and text-to-speech](feature-reference.md#speaker-and-text-to-speech).

Details: [Display controls](feature-reference.md#display-device-controls),
[pages and tiles](feature-reference.md#display-settings) and
[Alarmo](feature-reference.md#alarmo-display).

See [display examples](../README.md#c300x-display-pages) for status tiles, lights,
color/brightness and media-player controls. The stair-light shortcut in the
Alarmo example is configurable, not a required part of that page.

## After the First Test

For later updates, follow [Updates](advanced-maintenance.md#updates).

Use [Feature reference](feature-reference.md) to decide what to enable next:

- a different camera picture under **Configure > Camera quality**: the original
  688x480 and 704x576 choices remain available. Optional **960x576** retains
  576 lines and matches the LCD's 5:3 proportions, but only for the exact
  verified C300X firmware **1.7.19 or 2.0.2** media executables, each checked
  by its own full-file hashes (2.0.2 checked offline only). Applying or restoring
  this option requires a verified original backup and a normal device reboot;
  save only when no call or recording is active. Other firmware and the Qt5
  low stream are unchanged. See [Camera quality](feature-reference.md#camera-quality),
- clearer sound with the **Audio codec** select on **PCMU** (the device
  restarts once; firmware 3.0.6 runs PCMU already),
- additional C300X activation buttons,
- ringer mute and volume controls,
- video-message and memo workflows,
- display pages,
- Ring Capture and local Wyoming transcription,
- maintenance controls.

## Removing the Integration

For removal rather than an update, follow the
[HA entry and custom-integration removal guide](advanced-maintenance.md#remove-home-assistant-integration).
It explains retained media/configuration and backups. Removing the native device
agent is a separate, explicitly requested maintenance operation, not part of
ordinary HA-entry deletion.

## If Something Fails

Start with:

- [Feature reference](feature-reference.md)
- [Media readiness](media-readiness.md)
- [Media troubleshooting](media-troubleshooting.md)
- [Advanced maintenance](advanced-maintenance.md)
