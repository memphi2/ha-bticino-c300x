# Classe 100X: Troubleshooting

**Step 4 of 5:** [1. Setup](1-setup.md) | [2. Use](2-use.md) | [3. Station display](3-display.md) |
**4. Troubleshooting** | [5. Update and removal](5-update-and-removal.md)

This page lists problems that only occur on a Classe 100X. For the card,
calls, sound, picture and network, use the
[Classe 300X troubleshooting](../classe-300x/4-troubleshooting.md); it
applies to the Classe 100X as well.

## Setup and Update

| Message | Meaning | Do this |
| --- | --- | --- |
| **This package does not support this station** | The package is not made for a Classe 100X, or the model could not be confirmed. Nothing was changed. | Install the current beta. |
| `unsupported_active_route` | The station's call routing was changed by another tool, for example BTicino Companion. Nothing was written. | Video and calls cannot be set up on this station. |

## Display Pages

| Problem | Do this |
| --- | --- |
| No display settings, **Ringer mute** or **Touch tone** | Expected until the pages are active. Press **Activate display pages** ([steps](3-display.md#activate-the-display-pages)). |
| The activation waits and does not reboot | The station reboots only when it has been idle for about two minutes, with no call, stream or sound. A call postpones it. |
| Repairs: **C100X display pages were rolled back** | The pages did not start after the reboot, so the station went back to its original display. Press **Activate display pages** again. If it rolls back again, report it with the diagnostics. |
| Repairs: **C100X display check failed at the station start** | The agent could not check the pending activation at start. Press **Restore original display**. If that fails, run the agent update Repair first. |
| A notification is refused | The Classe 100X plays no tone and has no speaker or message LED. Send `display` without `sound_duration`. |
| No **Reload device display** button | Expected on the Classe 100X. |

## Stop Testing When

- the station reboots unexpectedly (the activation's own reboots are
  expected);
- a door call, the BTicino app or a key on the station stops working;
- setup fails.

Do not repeat a failing installation, delete backups or restart the station's
own programs. Go back as described in
[5. Update and removal](5-update-and-removal.md#go-back-to-the-original-station)
and report in [issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51)
with a photo of the screen, the versions and the diagnostics.

**Next: [5. Update and removal](5-update-and-removal.md)**
