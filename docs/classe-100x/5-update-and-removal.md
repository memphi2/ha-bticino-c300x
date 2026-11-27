# Classe 100X: Update and Removal

**Step 5 of 5:** [1. Setup](1-setup.md) | [2. Use](2-use.md) | [3. Station display](3-display.md) |
[4. Troubleshooting](4-troubleshooting.md) | **5. Update and removal**

This page explains how to update a Classe 100X and how to bring the station
back to its original state.

## Update

1. Install the update offered by Marketplace or HACS. Restart Home Assistant
   if it asks you to.
2. Open **Settings > Repairs** and run **C100X device agent update
   required**.
3. Check **Media readiness**.

If the display pages are active and the update brings newer pages, the
station reboots once after about two minutes of idle time, never during a
call. A station with its original display is not rebooted.

Only packages made for the Classe 100X update it; Home Assistant and the agent
refuse any other. Never go back to a release older than the joint Classe
300X/100X package (`3.0.0b1`), and never use the SSH installer of such a
release on a Classe 100X.

Keys, maintenance switches and the integration removal work as on the Classe
300X: [Classe 300X update and removal](../classe-300x/5-update-and-removal.md).

## Go Back to the Original Station

Do these steps in order:

1. If the display pages are active, press **Restore original display** and
   wait for the reboot.
2. Turn off **Home Assistant media user**. The original call routing program
   comes back from its backup; the added user lines stay.
3. Enable **Remove device agent** on the device page and press it.

Removal first checks that the display files and the call routing program are
the originals, or restores them from their backups. If that fails, it stops
before deleting anything and does not reboot. Removal is not a factory reset
and does not unroot the station. Removal on a Classe 100X is in test.

If removal fails and you have to put files back by hand, follow
[Manual recovery](../dev/c100x-device-test.md#manual-recovery) in the C100X
device test.

To remove the entry and the package from Home Assistant, follow
[Remove the integration](../classe-300x/5-update-and-removal.md#remove-the-integration).

**Back to the [overview](../../README.md#start-here)**
