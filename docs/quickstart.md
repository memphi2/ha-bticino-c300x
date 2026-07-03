# Quickstart

This is the recommended first setup path. Follow it in order and do not start
with YAML, manual card configuration or advanced display pages.

Goal:

```text
HACS install -> add integration -> install/update agent -> Media readiness ready
-> add the C300X card
```

## Before You Start

You need:

- Home Assistant `2026.5.0` or newer.
- A BTicino Classe 300X / C300X on firmware `1.7.x`.
- Root or SSH access on the C300X for the first device-agent installation.
- A trusted local network between Home Assistant and the C300X.

This integration cannot root a stock device. If a separate rooting or
SSH-enablement workflow asks for a firmware target, use `1.7.19`.

## 1. Install Through HACS

1. Open **HACS**.
2. Go to **Integrations**.
3. Open **Custom repositories**.
4. Add:

   ```text
   https://github.com/memphi2/ha-bticino-c300x
   ```

5. Category: **Integration**.
6. Install **BTicino C300X**.
7. Restart Home Assistant.

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

The SSH credentials used during installation are one-time setup inputs. They
are not stored in the Home Assistant config entry, diagnostics or logs.

## 4. Choose the Standard Feature Set

Recommended first-run choices:

- Enable **Doorbell camera/video** when you want camera, Ring Call, Home Call or
  talkback.
- Keep **Create Home Assistant media user** enabled for media features.
- Leave display pages disabled unless you want Home Assistant pages on the
  C300X display.
- Select Alarmo and weather entities only if you use those display pages.
- Leave destructive maintenance controls disabled until needed.

Feature choices can be changed later from the integration options.

## 5. Check Media Readiness

After setup, open the `Media readiness` diagnostic sensor.

- **ready**: continue with the Lovelace card.
- **warning**: basic media can work, but review the listed warnings.
- **blocked** or **unavailable**: open the Repair issue and press **Fix now**.

Do not debug the card before this entity is `ready` or shows only warnings you
understand.

Details: [Media readiness](media-readiness.md)

## 6. Add the Lovelace Card

After Media Readiness is ready:

1. Open the dashboard where you want the C300X card.
2. Add a card.
3. Select **C300X Doorbell Call Card**.
4. Choose the C300X camera entity.

Use one normal card in **Auto** mode for Doorbell, On-demand and Home Call.
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
2. **Home Call**: start and stop a Home Call from the Home Call card.
3. **Ring Call**: set **Forwarding** to **Home Assistant**, ring the doorbell,
   then press **Answer** in the card.

Talkback needs a secure Home Assistant frontend: HTTPS, Home Assistant Cloud or
another secure browser context with microphone permission.

## 8. Optional Blueprints

Ready-made blueprints are available for doorbell notifications, Ring Call
notifications, capture, Wyoming transcription and strict phrase decisions. They
are installed into Home Assistant's blueprint folder when the integration loads.

Details: [Blueprints](blueprints.md)

## If Something Fails

Start with:

- [Media readiness](media-readiness.md)
- [Media troubleshooting](media-troubleshooting.md)
- [Advanced maintenance](advanced-maintenance.md)
