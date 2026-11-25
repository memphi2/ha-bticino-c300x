# Outdoor Units and Calls (3.1.0 contract)

Interface contract for several outdoor units (entrance panels, "PE") on one
indoor station, issue #53. It fixes identities, the unit and call model, the
agent API, event timing, error codes and the Home Assistant migration. The
agent and the integration are released together; the agent update Repair
installs the matching agent, so nothing here keeps an older agent working
beyond what that Repair needs.

## Bus facts this design rests on

Verified in the owner's captures (1.7.19, one unit) and in a three-unit
installation (1.7.19, units `20#2`, `21`, `22`):

| Frame | Meaning |
| --- | --- |
| `*8*1#1#4#21*11##` | Ring. The `21` is a literal of `bt_vct`, not the caller: every unit rings with the same frame. |
| `*8*9#<kind>#<mode>*<where>##` | Caller (CALLING_ADDR), ~300 ms after the ring (`kind` 1) or after an on-demand view (`kind` 5). `<where>` is the calling unit, for example `20`, `21`, `20#2`. |
| `*8*100#<kind>#<mode>*<where>##` | End of the call or view of that unit. |
| `*8*1#5#4#<where>*11##` | On-demand view of unit `<where>`. |
| `*8*2#1#4*<n>##` | The ring was answered on the station. |
| `*8*3#1#4*<n>##`, `*8*3#5#4*<n>##` | Media closed (no unit). |
| `*8*19*<where>##` / `*8*20*<where>##` | Door lock pressed / released. |

On the multicast path every frame arrives up to three times within ~0.3 s.
`bt_vct` of 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8 all contain the CALLING_ADDR
logic; on 2.0.2, 3.0.6 and the C100X the frame was not yet captured.

A unit behind an apartment interface (BTicino 346850) reports `20#2` in the
caller frame, but its lock and video use the plain `20`
(`*8*19*20##`, `a=DEVADDR:20`).

## Identity

| Object | Identity |
| --- | --- |
| Station | `station_id` = the agent's `device.id` (`c300x-<mac>`), the config entry's `unique_id`. |
| Outdoor unit | `unit_id` = the full `where` with `#` replaced by `_`: `20#2` -> `20_2`, `21` -> `21`. |
| Call | `call_id` = `<boot_id>-<seq>`: `boot_id` is 8 hex characters drawn at agent start, `seq` counts from 1. Never reused within a boot; a new boot never repeats an old `boot_id` in practice. |

- `where` is a string, never a number: `20#2` and `20` are different units.
- `action_where` is the address used for unlock and video: `where` up to the
  first `#` (`20#2` -> `20`).
- Home Assistant devices:
  - station: identifiers `{(bticino_c300x, <station_id>)}`, connections
    `{(mac, <device.mac>)}` when the agent reports it;
  - outdoor unit: identifiers `{(bticino_c300x, "<station_id>:unit:<unit_id>")}`,
    `via_device` the station, model `Outdoor unit`.
- Entity unique ids: station `"<station_id>_<key>"`, unit
  `"<station_id>_unit_<unit_id>_<key>"`. One helper builds them; no module
  formats its own.
- Deleting and re-adding the config entry gives the same identifiers, so Home
  Assistant restores the devices' names, areas and the entities' ids.

## Outdoor units (topology)

Sources, in this order:

1. `archive.xml` (`/home/bticino/cfg/extra/0/archive.xml`): inside an `<obj>`,
   every `<ist>` without `cid` is an outdoor unit, every `<ist cid="10060">`
   is a lock. The bus address is the `<obj>`'s `dev` (default `2`) followed by
   the `where` of the `<ist>` (`0#2` -> `20#2`, `1` -> `21`). The name is
   `descr`. A unit's lock is the lock with the same `action_where`; without
   one the unit's own `action_where` is its lock.
2. The default unit from `conf.xml` (`/var/tmp/conf.xml`,
   `setup/vdes/communication/p_default`: `dev` + `address`, `2` + `0` -> `20`).
   Without `conf.xml` the agent's `video.sip.devaddr` (default `20`) is used.
   If no archive unit has that `action_where`, a unit with that `where` is
   added (source `default`). The default unit's lock is the agent's
   configured lock address (`lock.address`, default `20`).
3. Units first named by a caller frame (source `seen`). They live in agent RAM
   until the next restart; Home Assistant keeps their devices. A `default`
   unit that is not in the archive adopts the full `where` of the first caller
   frame with its `action_where` (its `unit_id` stays), instead of creating a
   second unit.

The topology is read at agent start and whenever `GET /api/v1/outdoor-units`
finds the archive's modification time changed. At most 16 units.

## Calls

A call has `call_id`, `kind` (`ring` or `view`), `state`, `unit`
(`unit_id` or `null` while not yet known), `attribution` and timestamps.

| `state` | Meaning |
| --- | --- |
| `ringing` | A ring is in progress. |
| `answered` | Answered by Home Assistant (`answered_by: "ha"`) or on the station (`"station"`). |
| `viewing` | On-demand view of a unit (`kind: "view"`). |
| `ended` | Over; kept for 60 s for late requests, then dropped. |

| `attribution` | Meaning |
| --- | --- |
| `pending` | Unit not yet known. |
| `caller_frame` | Unit taken from the caller frame of this call. |
| `default_fallback` | No caller frame within 1 s; the default unit was assumed. |

### Ring timing

1. A ring frame (or the ring's SIP INVITE, whichever comes first) that is not
   a repeat opens a call and the ring event `doorbell.pressed` goes out at
   once, with `call_id` and `unit: null`.
2. A repeat is a ring frame within 1000 ms of the last ring frame of a call
   that is still `ringing`. It changes nothing and sends nothing. (This
   replaces the 2.x global one-second filter, which would also have dropped a
   second unit.)
3. A caller frame (`kind` 1) binds its unit to the newest `ringing` call that
   has no unit yet and whose ring started at most 1500 ms earlier, and sends
   `call.caller_identified`.
4. If no caller frame arrives within 1000 ms, the agent binds the default unit
   with `attribution: "default_fallback"` and sends `call.caller_identified`.
5. A unit, once bound, is final. A caller frame never moves to another call:
   - for a unit that already has a live call: a repeat, ignored;
   - for another unit, when a ring frame was taken as a repeat after the
     newest call got its unit, and at most 1000 ms ago: a second unit is
     ringing. A new call opens with that unit already bound; `doorbell.pressed`
     (with `unit`) and `call.caller_identified` go out;
   - otherwise it is counted (`caller_frames_ignored` in diagnostics) and
     dropped. This covers a late frame after the fallback.
6. If the bound unit already had a live `ringing` call, that older call ends
   with `reason: "superseded"`: the same visitor pressed again.

Two units pressed within the caller-frame delay (~0.3 s) of each other are
reported as one call of the first unit identified; the bus does not separate
them.

### Current call

Only the current call can be answered or hung up: the `answered` call if
there is one, else the newest `ringing` call. A ring of a second unit during an
answered call opens its own `ringing` call, but the answered one stays current
until it ends.

### End of a call

| Source | Ends |
| --- | --- |
| `*8*100#1#…*<where>##` | The live ring call of that unit. |
| `*8*100#5#…*<where>##` | The view of that unit. |
| `doorbell.media.closed` as the agent sends it (after its answer and on-demand start filters) | Every live call (`reason: "media_closed"`). |
| Hang-up through the API | That call (`reason: "hangup"`). |
| No change for 90 s while `ringing`, 15 min while `answered` or `viewing` | That call (`reason: "timeout"`). |

The timer exists only while a call is live; an idle agent has no extra wakeup.

## Agent API

Capabilities add `api_version: "2"`, `device.mac` (`aa:bb:cc:dd:ee:ff` or
absent), `capabilities.outdoor_units: true` and `capabilities.calls: true`.

### `GET /api/v1/outdoor-units`

```json
{
  "ok": true,
  "default_unit": "20_2",
  "archive": "ok",
  "units": [
    {"id": "20_2", "where": "20#2", "action_where": "20", "lock_where": "20",
     "name": "Gate", "source": "archive", "default": true},
    {"id": "21", "where": "21", "action_where": "21", "lock_where": "21",
     "name": "", "source": "seen", "default": false}
  ]
}
```

`archive`: `ok`, `empty`, `missing` or `unreadable`. `name` is empty when the
station has none.

### `GET /api/v1/calls`

```json
{
  "ok": true,
  "boot_id": "8f3a1c2e",
  "current_call_id": "8f3a1c2e-7",
  "calls": [
    {"call_id": "8f3a1c2e-7", "kind": "ring", "state": "ringing",
     "unit": "21", "attribution": "caller_frame", "answered_by": null,
     "end_reason": null, "age_ms": 1200}
  ]
}
```

Lists live calls and calls ended in the last 60 s, newest first, at most 8.

### `POST /api/v1/calls/{call_id}/actions/answer`, `.../hangup`

Same work and success bodies as the 2.x unscoped routes, which are removed.
The `call_id` is checked before the media operation starts (not again when the
handler runs a second time for the same request). Answer marks the call
`answered` (`answered_by: "ha"`); hang-up ends it.

### `POST /api/v1/outdoor-units/{unit_id}/actions/unlock`

Body optional: `{"call_id": "8f3a1c2e-7"}`. `{unit_id}` may be `current`: the
unit of the current call, else the default unit. Sends `*8*19*<lock_where>##`,
waits the configured release delay, sends `*8*20*<lock_where>##`.

```json
{"ok": true, "unit": "21", "lock_where": "21", "call_id": "8f3a1c2e-7"}
```

With `call_id`, the call must belong to that unit and be live or ended less
than 60 s ago. `POST /api/v1/locks/{id}/actions/unlock` stays for configured
locks that are not outdoor units.

### Video

`POST /api/v1/video/doorbell/actions/activate` takes an optional `unit`. Without
it the unit is the current call's, else the default unit. A ring call always
shows the calling unit; the station switches the picture itself.

On-demand video of a unit other than the default one (phase D) is **not yet
supported**: it answers `409 unit_video_unsupported`. Later, with its own
concept that includes how the card handles several units' video. Design note: the
request's `unit` (and an RTSP `?unit=<unit_id>` for a stream started by
`PLAY`) selects the SDP `a=DEVADDR:<action_where>` of that one session instead
of `video.sip.devaddr`; a running view of another unit is stopped first.

### Errors

| Status | `error` | When |
| --- | --- | --- |
| `409` | `call_not_current` | The `call_id` is unknown (also from an earlier boot), ended, or not the current call; for unlock: not that unit's call or ended more than 60 s ago. The body carries `current_call_id` (or `null`). Nothing is sent to the station. |
| `404` | `unknown_unit` | No unit with that id. |
| `409` | `unit_video_unsupported` | On-demand video of a non-default unit. |
| `400` | `invalid_call_id` | Empty or longer than 32 characters. |

### Events

All carry the 2.x envelope (`event_id`, `type`, `occurred_at`, `data`).

| `type` | `data` |
| --- | --- |
| `doorbell.pressed` | `call_id`, `unit` (`null` unless a second unit opened the call), `attribution`, `raw` |
| `call.caller_identified` | `call_id`, `unit`, `where`, `action_where`, `attribution`, `raw` (`null` for the fallback) |
| `call.answered` | `call_id`, `unit`, `answered_by` |
| `call.view_started` | `call_id`, `unit` (a view frame `*8*1#5#4#<where>*…##` opened a view) |
| `call.ended` | `call_id`, `unit`, `kind`, `reason` |
| `doorbell.view_requested` | adds `call_id` and `unit` when the frame names the unit |
| `door_unlock.started`, `door_unlock.ended` | add `unit` when the address is a unit's lock, and `call_id` of its live call |
| `outdoor_units.changed` | `count`; Home Assistant reads `GET /api/v1/outdoor-units` again |

## Home Assistant

### Devices and entities

Station device: display, ringer, answering machine, memos, codec, camera
resolution, agent, maintenance, diagnostics, LED, announcements, stair light,
activations, Home Call, and the station `ring` event entity (key `ring`,
event type `ring`, attributes `call_id` and `unit: null`): the indoor station
ringing. It fires at once on `doorbell.pressed`, on every station, also with
one unit.

Every outdoor unit, also the only one:

| Entity | Key | Notes |
| --- | --- | --- |
| `event` | `doorbell` | device class `doorbell`, event type `ring`; attributes `call_id`, `attribution`. |
| `camera` | `camera` | The default unit's camera is the media camera (ring, answer, on-demand). Another unit's camera shows live video while it has the current call, else its last visitor image. |
| `button` | `door` | Unlocks this unit (`outdoor-units/{unit_id}/actions/unlock`). |
| `sensor` | `call` | `idle`, `ringing`, `answered`, `viewing`; attribute `call_id`. |
| `image` | `last_visitor` | The latest retained image of a call of this unit. |

The unit event fires when the call's unit is known, with the same `call_id`
as the station ring: at once when the station has exactly one unit, else on
`call.caller_identified` (~0.3 s, at most 1 s). Everything that does not
depend on the unit (station ring event, card ring view, ring preview, image
capture) starts with `doorbell.pressed`. Blueprints default to the unit
event; the station ring is the trigger for the fastest notification, without
the unit's name.

Event delivery to Home Assistant no longer depends on which entities are
enabled. Only `system.metrics_changed` and `agent.diagnostics_changed` stay
tied to their sensors.

The bus event `bticino_c300x_agent_event_received` no longer carries rings;
the unit event entities replace it. Its other events gain `device_id` (the HA
station device), and for unit events `unit_id`, `outdoor_unit_device_id` and
`call_id`.

### Card

The card follows the active call: it shows the calling unit's name and uses
the media camera as before. It has no unit selector and no per-unit video in
3.1.0 (that comes with phase D).

### Services

Services take a Home Assistant target (device or entity) instead of
`entry_id`. A unit target names the unit; a station target means the current
call's unit, else the default unit.

- `answer_call`, `hangup_call`: optional `call_id`; without it the target's
  current call. `409 call_not_current` becomes a translated error.
- `activate_doorbell_video` with a unit target; `capture_doorbell_call` and
  `evaluate_ring_analysis` act on the call's unit.
- Removed (use the buttons): `unlock_door`, `stair_light`,
  `stop_doorbell_video`, `reboot`, `reload_gui`, `run_device_activation`,
  `delete_latest_video_message`, `delete_latest_text_memo`,
  `delete_latest_voice_memo`.
- The notify `mode` field is removed; the display switches decide.

### Migration (config entry version 2)

Runs once, at the first setup with a 3.1.0 agent, before the platforms load:

| From | To |
| --- | --- |
| device `(bticino_c300x, <entry_id>)` | `(bticino_c300x, <station_id>)`, same HA device |
| `<entry_id>_<key>` | `<station_id>_<key>` |
| `<entry_id>_doorbell_camera` | `<station_id>_unit_<default>_camera`, on the default unit's device |
| `<entry_id>_doorbell_event` | `<station_id>_unit_<default>_doorbell`, on the default unit's device |
| `<entry_id>_door_unlock` | `<station_id>_unit_<default>_door`, on the default unit's device |
| `<entry_id>_doorbell_state`, `<entry_id>_agent_event` | removed from the registry |

Entity ids and history stay. One Repair issue lists what users must redo:
re-select the outdoor unit in blueprint automations, replace the removed
services by buttons, replace the notify `mode` by the display switches.

Old notify `mode` to switches:

| `mode` | Switches in `data` |
| --- | --- |
| `display` | `display: true` |
| `speech` | `tts: true` |
| `both` | `display: true`, `tts: true` |
| `led` | `led: true` |
