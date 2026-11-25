# Device QML UI

Native Qt/QML pages for the C300X display (Qt 4, firmware 1.7.x and 2.0.2; on
firmware 3.0.6 through the
[Qt 5 resource overlay](../docs/dev/native-agent.md#supported-firmware-versions)).
No Lovelace is embedded: the pages talk to the agent's loopback display bridge
on `127.0.0.1`, port `listen.uiPort` (installer default 8090). What users see
and configure is in [Station Display Pages](../docs/display.md).

## Files

| File | Purpose |
| --- | --- |
| `Alarm.qml` | Alarmo subpage: state, readiness, PIN input, guarded arm/disarm, optional quick entity. |
| `HomeAssistant.qml` | Dynamic Home Assistant board: tiles, detail pages, badges, picture tiles, command feedback. No refresh timer. |
| `C300XPageNavigation.qml` | Page buttons of the status page, the favourites bar (`bar: true`) and its More list, from the existing snapshot without new requests. |
| `C300XOptionalPages.qml` | Loads whichever of Energy, Agenda, Leave home or Situations is current and unloads the others. |
| `C300XAgenda.qml` | Calendar page; HA prepares at most five events in seven days in a bounded background cache. |
| `C300XLeaveHome.qml` | Departure page: contacts, lights, allowlisted actions with second-tap Confirm (eight seconds). |
| `C300XSituations.qml` | Read-only list of selected contacts, garage doors, lights and task lists that need attention. |
| `C300XChecks.qml` | Row list (name, coloured state) shared by Leave home and Situations. |
| `C300XDetailControl.qml` | Shared touch controls of entity detail pages. |
| `C300XEnergy.qml` | Energy page (Now, Today, Power, Consumers, Balance); loaded by `C300XOptionalPages.qml` only while shown. Draws HA's computed values: no timer, animation or own request. |
| `C300XEnergyReadout.qml` | Selected-interval readout of the energy charts (exact supplied interval and values, no invented points). |
| `C300XEnergySums.qml` | Two-column sums grid used by the energy page and its readout. |
| `C300XEnergyConsumers.qml` | Consumers view: up to ten current power readings in two independently scaled columns of five. |
| `C300XAlerts.qml` | Notify popups with bounded wake and stock short-beep effects, only on safe Home/HA screens. |
| `C300XRingerControl.qml` | Core, page-independent ringer command receiver using the stock `AudioState` calls. Installed with the core `EventManager.qml` patch. |
| `C300XSettings.qml` | **Settings > Integration** tab: status block (Home Assistant reachable, address, last contact, versions), Status messages, Keep page open in standby, page change, SSH, reboot, agent removal. |
| `js/c300x_ha.js` | Local HTTP helper of the HA pages. |
| `js/c300x_i18n.js` | Display texts in the supported languages. |
| `js/c300x_energy.js` | Energy chart formatting (HA wall time, not device timezone). |
| `js/c300x_energy_consumers.js` | Consumers scaling, stable colours per sensor. |
| `js/c300x_alerts.js` | Alert request and effect handling. |
| `js/c300x_memos.js` | Loopback memo/message metadata helper for the patched memo pages. |
| `js/c300x_maintenance.js` | Per-tab request state of the settings tab; late replies never update a reopened tab. |
| `js/c300x_ringer.js` | Ringer request handling; deliberately not a shared library, each control owns its request. |

The stock `HomePage.qml`, `MemoPage.qml`, `MainApp.qml`, `Settings.qml`,
`EventManager.qml`, `Components/Settings/GeneralsChoice.qml` and
`Components/Settings/CallBlockPopup.qml` are not stored here. `native_agent/scripts/qml_patch.sh` transforms the originals on the device
and keeps a one-time original backup there.

## Implementation Notes

- **Request serialisation:** the agent forwards display requests to HA one at a
  time and refuses a second while the first is open, so pages queue instead of
  colliding (waking from standby while the home page refreshes its buttons
  shows no transport error). Pages asking for the same state at the same time
  share one request; commands always keep their own.
- **Response budget:** the display reads the whole dashboard in one response
  inside the agent's 32 KiB buffer; HA keeps the body within 30 KiB of compact
  UTF-8 (`dashboard_response.py`).
- **Option byte budget** (`dashboard_controls.py`): a choice list (select
  options, player sources, sound modes) sends at most 50 options and at most
  2048 bytes, measured as escaped JSON (a non-ASCII character counts six bytes,
  an emoji twelve). The response goes out as unescaped UTF-8, so this is an
  upper bound. An option over 1024 bytes is left out. If the dashboard is still too
  large, the longest choice lists are shortened one after another; short lists
  such as thermostat modes are cut last. Too large even then: HA logs the size
  and returns `dashboard_too_large`, and the display stays offline/stale. Check
  states, actions and history values are never dropped to fit.
- **Updates:** selected-entity changes use the existing event bridge; bursts are
  combined, and changes that alter no displayed value, availability or control
  do not notify the device. Unchanged GUI items are reused, keeping the overview
  position and active input. Timeout and reconnect handling runs only while a
  page is active.
- **Waiting connections:** alerts, ringer control and touch tone each hold one
  sleeping loopback request instead of polling. The alerts request also reports
  screen protection for its lifetime; protected screens never receive alert
  payloads and nothing is replayed later. The ringer receiver reconnects on a
  timer only after a connection or protocol failure. Commands and replies stay
  in RAM.
- **Settings preference:** a GUI-owned preference object in the patched
  `MainApp.qml` reads the local agent once and saves only on user input, with a
  declarative request deadline instead of a polling timer or dynamically
  created objects. The tab uses the configured `listen.uiPort`.
- **Picture tiles:** HA scales the still to the tile before the display loads it
  over a URL signed with the entry secret; the display can only open `http://`.

## Packaging

These sources are not written to the device as they stand. Packaging
(`scripts/stage_device_agent_bundle.py`) and the development installer
(`scripts/install_c300x_device.sh`) pass every `.qml` and `.js` file through
`scripts/device_file_strip.py`, which drops comment-only lines, blank lines and
indentation (about 30 % smaller on the device), so comments here cost nothing
there. The staged `qml_patch.sh` also embeds the stripped `C300XSettings.qml`
and `js/c300x_maintenance.js`, so an installed updater needs no new upload paths
for them.

The strip is line based on purpose. Keep it valid: no `/* */` block comments
and no string literal continued over a line break with a backslash; packaging
fails on either. A `//` comment after code on the same line is kept, so put
comments on their own line. Device log line numbers refer to the stripped file;
`scripts/device_file_strip.py --out <dir>` writes the same files locally.

## Safety

- Apply the device UI only through the agent's QML maintenance API. It installs
  the generated project files, transforms original device pages and backs up
  the originals first, under
  `/home/bticino/cfg/extra/c300x-device-file-backups/original/`, mirroring the
  GUI path.
- The Settings menu and preserved General page take part in the same staged
  apply, transactional rollback and restore-all paths as the other original
  pages. Reapplying uses the preserved original; unsupported layouts and missing
  required backups fail before any active GUI file changes.
- Never create on-device backups of generated project code (agent, display
  bridge, their configs).
- A patch needs a GUI restart, which `qml_patch.sh` performs. Device commands
  run only through the agent and the installers: `device_installer.py` (first
  installation) and `scripts/install_c300x_device.sh` (development, optional
  `--apply-qml`) run them over SSH.
- PINs go only to the loopback agent API and are never logged.

## Related Documentation

- [Architecture](../docs/dev/architecture.md)
- [Native agent](../docs/dev/native-agent.md#display-patch)
- [Loopback UI API](../native_agent/API.md#loopback-ui-api)
