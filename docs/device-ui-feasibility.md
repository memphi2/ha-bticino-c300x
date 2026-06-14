# Device UI Feasibility

## Result

A native C300X QML dashboard is feasible and integrated through local loopback calls to the native agent.

## Supported model

- QML page patch on the C300X GUI.
- Device QML pages are transformed on the device instead of copied
  into the repository.
- Dashboard payload/actions served by native agent `displayBridge`.
- Alarm panel flow through Home Assistant `alarm_control_panel` services.

## Constraints

- No Lovelace embedding on device.
- No HA token in QML files.
- QML should only talk to loopback.

## Deployment safety

- Back up original device-owned QML files before patching.
- Keep the patch reversible.
- Restart only the GUI process after patch verification.
