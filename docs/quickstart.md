# Quickstart

This is the recommended 10-minute path for a normal C300X install.

## Before You Start

You need:

- Home Assistant `2025.5.0` or newer.
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
Run that Repair before testing media features.

The SSH credentials used during installation are one-time setup inputs. They
are not stored in the Home Assistant config entry, diagnostics or logs.

## 4. Choose the Standard Feature Set

Recommended first-run choices:

- Enable **Doorbell camera/video** when you want camera, Ring Call, Home Call or
  talkback.
- Keep **Create Home Assistant media user** enabled for media features.
- Leave the Display patch disabled unless you want C300X display pages.
- Select Alarmo and weather entities only if you use those display pages.
- Leave destructive maintenance controls disabled until needed.

Feature choices can be changed later from the integration options.

## 5. Check Media Readiness

After setup, open the `Media readiness` diagnostic sensor.

- **ready**: continue with the Lovelace card.
- **warning**: basic media can work, but review the listed warnings.
- **blocked** or **unavailable**: open the Repair issue and press **Fix now**.

Details: [Media readiness](media-readiness.md)

## 6. Add the Lovelace Card

After Media Readiness is ready:

1. Open the dashboard where you want the C300X card.
2. Add a card.
3. Select **C300X Doorbell Call Card**.
4. Choose the C300X camera entity.

Use one normal card for Doorbell/On-demand. Add a second card in **Home Call**
mode when you want Home Call.

## 7. Optional Blueprints

Ready-made blueprints are available for doorbell notifications, Ring Call
notifications, capture, Wyoming transcription and strict phrase decisions.

Details: [Blueprints](blueprints.md)

## 8. Test the Three Media Paths

Test in this order:

1. **On-demand**: press Stream in the card.
2. **Home Call**: start and stop a Home Call from the Home Call card.
3. **Ring Call**: set **Forwarding** to **Home Assistant**, ring the doorbell,
   then press **Answer** in the card.

Talkback needs a secure Home Assistant frontend: HTTPS, Home Assistant Cloud or
another secure browser context with microphone permission.

## If Something Fails

Start with:

- [Media readiness](media-readiness.md)
- [Media troubleshooting](media-troubleshooting.md)
- [Advanced maintenance](advanced-maintenance.md)
