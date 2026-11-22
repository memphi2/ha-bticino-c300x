# C100X Display Parity

Scope: **all** additional native C300X pages, not a reduced dashboard. The
original C100X 1.5.8 `main.qml` specifies 800x480, QtQuick 2.7 and Controls 2.0.
Its wrapper selects EGLFS/fb1 and event0/event1. This is not a touchscreen
contract. No device/HA access is authorized by this offline work.

## Page and Input Matrix

| Existing source | Required C100X parity | Physical input |
| --- | --- | --- |
| `HomeAssistant.qml` | Status, badges, weather/forecast, images, configured pages and navigation | Up/Down focus and scroll, Return activate, explicit Back |
| `C300XDetailControl.qml` | All supplied light, cover, climate, fan, media, sensor and other entity controls | Discrete actions, choices and numeric adjustment; no drag-only controls |
| `C300XPageNavigation.qml` | Same page enable/order, favourites and More | Every enabled page reachable |
| `C300XEnergy.qml` | Now, Today, Power, Consumers, Balance; only enabled views | Tabs and exact supplied history buckets selectable with keys |
| `C300XEnergyConsumers.qml` | All configured consumer readings, independent column scaling | Read-only, no new polling |
| `C300XEnergyReadout.qml`, `C300XEnergySums.qml` | Exact selected interval and sums, dismissal | Return/dismiss and back |
| `Alarm.qml` | Blue Alarmo page, conditional PIN, modes, readiness, blockers, bypass, configured quick action | Full keypad and actions reachable; PIN cleared on exit/preemption |
| `C300XAgenda.qml` | All supplied events and error/empty states | Scroll every event |
| `C300XLeaveHome.qml` | Contacts, lights, Alarmo link and allowlisted actions with confirmation | Confirm/cancel within existing deadline |
| `C300XSituations.qml`, `C300XChecks.qml` | Configured situations, contacts, tasks and states | Scroll all rows |
| `C300XAlerts.qml` | Notify display, bounded wake/sound, acknowledge | Call/protected-page preemption, no deferred effects |
| `C300XRingerControl.qml` | Confirmed mute/unmute through stock AudioState | Core hook independent of dashboard visibility |
| Patched General settings | Vendor beep setting plus HA feedback preference | Keep stock InstallerPage beep control; additional settings keyed |
| Patched MemoPage and `c300x_memos.js` | Existing additional memo/message UI where backend supports it | C100X has no stock MemoPage; needs a separate verified adapter, never a fake vendor page |

Shared JS retains the existing HA snapshot, allowlisted command, confirmation,
timeout and sleeping-event-request contracts. No display refresh polling is
introduced. TTS remains separate and unavailable without a verified path.

## Original Firmware Anchors

| File | SHA256 |
| --- | --- |
| `main.qml` | `ff1740e9742951f5cda2225d605eae06141f43ee26d900ca21d7fdf14960e6fb` |
| `MainPage.qml` | `ba3edae9b9e670dad86894f93747f510f07c2389f498697e5d20dd95b4cb8e80` |
| `EventManager.qml` | `3ca4b5e8c27c8c8b283d533106091072e25632bb090d414ee4c1d93f3a06b181` |
| `BtClass100_qws` | `ad6d23db69795afb712751b3d92afbca3356d524b40bdb441de096b3d12c3612` |

`MainPage.qml` handles Up/Down/Return. `EventManager.qml` owns Call/Hangup
and keys 1-8, including door and stair actions. Those handlers must remain
unchanged. The adapter must yield to calls, commissioning and vendor pages.
`Components/RingtoneItem.qml` uses `AudioState.RingtoneMute`,
`isRingtoneMute` and `getVolume/setVolume`; `InstallerPage.qml` uses
`global.beepEnabled`. The original supervisor config names `BtClass100_qws`.
Never replace its framebuffer, input configuration or watchdog with guesses.

## Acceptance Boundaries

Implemented locally: separate QtQuick 2.7 conversion of all 13 page/display
modules, C100X-owned frame/text/switch/skin components, physical-key focus,
scroll reveal, numeric edit/confirm/cancel and history-bucket selection. The
shared HA JS and original Qt4 pages are unchanged. Focused host Qt5 tests load
every converted module and exercise offscreen actions and edit cancellation.
The generated entity slider is also tested with the real page helpers: edit
starts at the current value, one key advances one configured step, fractional
and unaligned bounds are respected, and cancellation submits no command.
This build is not yet an installed or advertised display adapter.

This matrix is a target, not a declaration that every row works. Capability
flags must stay false until the matching hook, command acknowledgement,
state readback, transactional installation and rollback are implemented and
tested together. Host Qt5 5.15 tests are useful but are not firmware Qt5 5.10.1
or hardware proof. Vendor imports, restart supervision, wake/sound and memo
runtime behavior require explicit evidence; missing evidence stays documented.
