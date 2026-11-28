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
| `*8*100#<kind>#<mode>*<where>##` | At most the end of the ringing or announcement phase: it follows an answer or a view start by 100-500 ms, and an unanswered ring has none. Not the end of a call; the agent ignores it. |
| `*8*1#5#4#<where>*11##` | On-demand view of unit `<where>`. |
| `*8*2#1#4*<n>##` | The ring was answered (on the station, in the app, or by Home Assistant's answer). |
| `*8*3#1#4*<n>##`, `*8*3#5#4*<n>##` | Media closed (no unit). |
| `*8*19*<where>##` / `*8*20*<where>##` | Door lock pressed / released. |

On the multicast path every frame arrives up to three times within ~0.3 s.
`bt_vct` of 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8 all contain the CALLING_ADDR
logic; on 2.0.2, 3.0.6 and the C100X the frame was not yet captured.

A unit behind an apartment interface (BTicino 346850) reports `20#2` in the
caller frame, but its lock uses the plain `20` (`*8*19*20##`). On-demand video
of such a unit, when it is not the default unit, sends its full address
(`a=DEVADDR:20#2`, see Video); whether the station shows that unit for it is
not verified on a station yet.

## Identity

| Object | Identity |
| --- | --- |
| Station | `station_id` = the agent's `device.id` (`c300x-<mac>`), the config entry's `unique_id`. |
| Outdoor unit | `unit_id` = the full `where` with `#` replaced by `_`: `20#2` -> `20_2`, `21` -> `21`. The default unit's id is its default address's (`20`), also when `archive.xml` names it `20#2`. |
| Call | `call_id` = `<boot_id>-<seq>`: `boot_id` is 8 hex characters drawn at agent start, `seq` counts from 1. Never reused within a boot; a new boot never repeats an old `boot_id` in practice. |

- `where` is a string, never a number: `20#2` and `20` are different units.
- `action_where` is the address the unit's lock is found by: `where` up to
  the first `#` (`20#2` -> `20`). On-demand video of a unit other than the
  default one uses the full `where` (see Video).
- Home Assistant devices:
  - station: identifiers `{(bticino_c300x, <station_id>)}`, connections
    `{(mac, <mac>)}` when `station_id` carries the MAC (`c300x-` and twelve
    hex digits, as the agent builds it from the network interface);
  - outdoor unit: identifiers `{(bticino_c300x, "<station_id>:unit:<unit_id>")}`,
    `via_device` the station, model `Outdoor unit`.
- Entity unique ids: station `"<station_id>_<key>"`, unit
  `"<station_id>_unit_<unit_id>_<key>"`. One helper builds them; no module
  formats its own. The media camera is a station entity
  (`"<station_id>_doorbell_camera"`) on the default unit's device: when the
  station's default unit changes it stays the same entity, and the entry
  reloads so that it moves to the new default unit's device. Before the
  platforms load, setup removes the new default unit's still camera
  (`"<station_id>_unit_<unit_id>_camera"`) from the registry.
- Deleting and re-adding the config entry gives the same identifiers, so Home
  Assistant restores the devices' names, areas and the entities' ids.

## Outdoor units (topology)

Sources, in this order:

1. `archive.xml` (`/home/bticino/cfg/extra/0/archive.xml`): only the
   outdoor-unit object `<obj cid="10050">` names outdoor units: every `<ist>`
   in it without `cid`. Its `<ist cid="10060">` are locks; other objects
   (cameras 10051, intercoms 10052/10053, actuators 3008, the stair light
   2009, TVCC 10061, unknown ones) name no unit. The bus address is `dev`
   (default `2`) followed by `where` (`0#2` -> `20#2`, `1` -> `21`), the name
   is `descr`; an attribute the `<ist>` lacks is its `<obj>`'s, as the
   station's display reads it. A unit's lock is the lock with the same
   `action_where`; without one the unit's own `action_where` is its lock.
2. The default unit from `conf.xml` (`/var/tmp/conf.xml`,
   `setup/vdes/communication/p_default`: `dev` + `address`, `2` + `0` -> `20`).
   Without `conf.xml` the agent's `video.sip.devaddr` (default `20`) is used.
   The archive unit with that `where`, else the first one with that
   `action_where` (`20#2` for `20`, a unit behind an apartment interface), is
   the default unit: one unit with the archive's name and `where` and the id
   of the default address (`20`), the same id it has without an archive, so
   Home Assistant keeps one device for that door. If no archive unit matches,
   a unit with that `where` is added (source `default`). The default unit's lock is the agent's
   configured lock address (`lock.address`, default `20`).
3. Units first named by a caller or view frame (source `seen`). The agent
   keeps them in `outdoor-units-seen` next to its configuration, so they
   survive a restart. A unit known only by its plain address (the `default`
   unit, a `seen` unit) adopts the full `where` of the first caller frame
   with its `action_where` (its `unit_id` stays), instead of creating a
   second unit.

A frame names a unit by its full address (`20#2`, caller frames) or by its
plain one (`20`, view frames). The plain address is the unit with that
`action_where`, the default unit first: it never creates a second unit, and
unit ids stay unique.

The topology is read with the first bus frame or request that needs it and
again on every `GET /api/v1/outdoor-units`. At most 16 units.

## Calls

A call has `call_id`, `kind` (`ring` or `view`), `state`, `unit`
(`unit_id` or `null` while not yet known), `attribution` and timestamps.

| `state` | Meaning |
| --- | --- |
| `ringing` | A ring is in progress. |
| `answered` | Answered by Home Assistant (`answered_by: "ha"`), on the station (`"station"`: display or app) or by the station's answering machine (`"answering_machine"`). |
| `viewing` | On-demand view of a unit (`kind: "view"`). |
| `ended` | Over; kept for 60 s for late requests, then dropped. |

| `attribution` | Meaning |
| --- | --- |
| `pending` | Unit not yet known. |
| `caller_frame` | Unit taken from the caller frame of this call. |
| `default_fallback` | No caller frame within 1 s; the default unit was assumed. |

### Ring timing

A call mirrors the agent's ring session of 3.0.0 and the station's own call
state (see Station call state).

1. A ring frame or the ring's SIP INVITE that the 3.0.0 duplicate filter lets
   through (the first ring, then none for 1000 ms) is `doorbell.pressed`, as
   in 3.0.0. With no live ring call it opens one; while the ring call is live
   (ringing or answered) it belongs to that call: the event carries its
   `call_id`, and nothing else changes. Trailing ring copies never open a
   second call.
2. The caller frame (`kind` 1) names the unit of the live ring call, ringing
   or answered, and sends `call.caller_identified`; a frame for another unit
   names that unit instead. A caller frame with no live ring call is counted
   (`caller_frames_ignored` in `GET /api/v1/calls`) and dropped.
3. If the ring call has no unit 1000 ms after it opened, the default unit
   stands in (`attribution: "default_fallback"`, `call.caller_identified`);
   a later caller frame still names the real unit.

The station has one ring session at a time: two units pressed in the same
session are one call, named by the last caller frame.

### Station call state

bt_answering_machine sends `*#8**35*<code>*<x>*<y>##` to the station's
monitor channel (the multicast the agent reads) on every change of its call
state, and answers the query `*#8**35##` with it. The frame and its sender
are the same on C300X 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8. `x` and `y` are
two fields of the answering machine's call record; they were `0` in every
capture and live log and the agent does not use them. The meanings come from
the captures and from the vendor functions that send each value:

| `code` | `state` | Seen |
| --- | --- | --- |
| `0` | `idle` | after the end frame of every call |
| `1` | `setup` | with the ring frame, and when a view is set up |
| `2` | `ringing` | with the caller frame, while the ringtone plays |
| `3` | `viewing` | a view without a ring |
| `4` | `waiting` | about 2.5 s after `2` with the ringtone's end (`*7*59#8…`), or when the ringer is muted; the call still waits |
| `6` | `conversation` | the display, the app or Home Assistant answered (`*8*2#…`) |
| `7` | `answering_machine` | it took the unanswered call (`*8*67*<unit>##`) |
| `8` | `greeting` | it plays the greeting (`*7*58#…` audio path) |
| `9` | `recording` | it records the visitor; a saved message follows the end (`*8*96#1#0*##`) |

Other codes (the vendor code also sends `10`, `11` and `12`) have no proven
meaning: `state: null`, they change no call.

Home Assistant shows it as the station's `sensor` `station_call_state`
(enum of the nine states, attribute `code`): seeded from `station_state` of
`GET /api/v1/calls`, then `station.call_state`. A code without a state, an
agent restart (until the next answer or event) and a station that has not
reported one read as unknown.

### Current call

Only the current call can be answered or hung up: the live ring call, else
the live on-demand view (`state: "viewing"`). Hanging up a view stops it, as
the stop button does; a view the display or the app holds, not the agent,
only they can end (`409 station_busy`, the view call goes on).

### End of a call

Start comes from the agent's ring events, as in 3.0.0. Answer and end come
from the agent's media events and from the station's call state; the other
bus frames only name the unit (caller frame) or open a view (view frame).
The display's own channel (`*8*80#6#2*…`, `*8*3#6#2*…` at wake and off) is
not a call.

| Event | Call |
| --- | --- |
| `doorbell.pressed` | Opens the ring call, or belongs to the live one (see Ring timing). |
| `doorbell.view_requested` of the ring (`*8*2#1#…`, or the agent's answer of its ring leg) | The ring call is `answered`: `answered_by: "ha"` for the agent's answer, which it gives Home Assistant only, else `"station"` (display or app). In which order the display's frames and the ring leg's close come does not matter. The `doorbell.view_requested` of the agent's on-demand view answers nothing. |
| `doorbell.media.closed` of the ring whose payload still reports the station's own media | The ringing call is `answered` by the station. |
| Station state `6` (conversation) | The ringing call is `answered`: `"ha"` while Home Assistant answered the ring leg, else `"station"`. |
| Station state `7` (answering machine) | The ringing call is `answered` (`"answering_machine"`). |
| View frame `*8*1#5#4#<where>*…##` | Opens a `viewing` call of that unit; a view of another unit ends the one before (`reason: "superseded"`). |

A media close belongs to the ring or to a view, never to both: the ring's
is the close of the agent's ring leg or the bus end frame `*8*3#1#…`, a
view's the close of the agent's on-demand view, the bus end frame
`*8*3#5#…` or the video off `*7*0*##` that follows either end frame.

| Source | Ends |
| --- | --- |
| `doorbell.media.closed` of the ring while ringing | The ring call, 1.5 s later, unless the display's or the app's answer frame comes in between (the app's end frame of the ring can come before its answer frame). |
| `doorbell.media.closed` of the ring while answered by Home Assistant | That call. |
| `doorbell.media.closed` of a view | That view; a ring call goes on. |
| The bus end frame of a call answered on the station | That call. The close of the agent's own leg does not end it: the display call goes on. |
| Hang-up through the API | That call (`reason: "hangup"`, also when the hang-up's own media close comes first). |
| Station state `0` (idle) | A call that was live then and that nothing else ended within 1.5 s (`reason: "station_idle"`, or the reason of a media close that was waiting): a lost end frame keeps no call. |
| The agent's media state, checked 66 s after the answer and every 5 s after that (a view: every 5 s) | An answered call whose leg is gone, or that the station holds while neither its media nor a non-idle station state is seen, ends with `reason: "media_closed"`. |
| No change for 90 s while `ringing` | That call (`reason: "timeout"`). |

The timer exists only while a call is live or ended less than 60 s ago; an
idle agent has no extra wakeup.

## Agent API

Capabilities report `api_version: "2"` and `capabilities.outdoor_units: true`,
`capabilities.calls: true`; the unused `capabilities.call_events` is gone.

### `GET /api/v1/outdoor-units`

```json
{
  "ok": true,
  "default_unit": "20",
  "archive": "ok",
  "units": [
    {"id": "20", "where": "20#2", "action_where": "20", "lock_where": "20",
     "name": "Gate", "source": "archive", "default": true,
     "door": {"state": "closed", "age_ms": 5300}},
    {"id": "21", "where": "21", "action_where": "21", "lock_where": "21",
     "name": "", "source": "seen", "default": false, "door": null}
  ]
}
```

`archive`: `ok`, `empty`, `missing` or `unreadable`. `name` is empty when the
station has none.

`door`: `null` for a unit without a door contact, else its state (`open`,
`closed`, `null` while no door frame came since the agent started) and
`age_ms` since its last change (`null` with it). bt_vct sends
`*8*66*<where>##` when a unit's door opens and `*8*65*<where>##` when it
closes, only from a unit wired with a contact; `<where>` is the plain
address, built like the caller frame's (`20`, `21`). A frame maps to its unit
like a caller frame: the default unit by its plain or its qualified address,
an unknown address adds a `seen` unit. Once a door frame of a unit was seen
the unit has a contact, kept across agent restarts in `outdoor-units-doors`
next to the agent's configuration; the station has no query for the state,
so it is unknown after a restart until the next frame. Same frame and sender
(bt_vct) on 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8.

### `GET /api/v1/calls`

```json
{
  "ok": true,
  "boot_id": "8f3a1c2e",
  "current_call_id": "8f3a1c2e-7",
  "caller_frames_ignored": 0,
  "station_state": {"code": 2, "state": "ringing", "age_ms": 1150},
  "calls": [
    {"call_id": "8f3a1c2e-7", "kind": "ring", "state": "ringing",
     "unit": "21", "attribution": "caller_frame", "answered_by": null,
     "end_reason": null, "age_ms": 1200}
  ]
}
```

Lists live calls and calls ended in the last 60 s, newest first, at most 8.
`station_state`: see Station call state; `null` until the station sent or
answered one.

### `POST /api/v1/calls/{call_id}/actions/answer`, `.../hangup`

Same work and success bodies as the 2.x unscoped routes, which are removed.
The `call_id` is checked before the media operation starts (not again when the
handler runs a second time for the same request). Answer marks the call
`answered` (`answered_by: "ha"`); hang-up ends it.

### `POST /api/v1/outdoor-units/{unit_id}/actions/unlock`

Body optional: `{"call_id": "8f3a1c2e-7"}`. `{unit_id}` may be `current`: the
unit of the current call, else the default unit; while the ring call's unit
is not known yet, none (`409 call_unit_pending`). Sends `*8*19*<lock_where>##`,
waits the configured release delay, sends `*8*20*<lock_where>##`.

```json
{"ok": true, "unit": "21", "lock_where": "21", "call_id": "8f3a1c2e-7"}
```

With `call_id`, the call must belong to that unit and be live or ended less
than 60 s ago. `POST /api/v1/locks/{id}/actions/unlock` stays for configured
locks that are not outdoor units.

### Video

`POST /api/v1/video/doorbell/actions/activate` takes an optional `unit`. Without
it the unit is the current call's, else the default unit (`409
call_unit_pending` while the ring call's unit is not known). A ring call always
shows the calling unit; the station switches the picture itself.

On demand, the request's `unit` selects the INVITE's `a=DEVADDR`: the default
unit keeps `video.sip.devaddr`; any other unit sends its full `where`
verbatim (`21`, `20#2`), which bt_answering_machine turns into
`*8*4#1<own>*<DEVADDR>##` when it starts with `2` and its number before `#`
is below 96 (else `409 unit_video_unsupported`). A running view of another
unit is stopped first (BYE, on-demand GOP cache dropped), then the parked
RTSP clients get the new unit's INVITE; the view frame
`*8*1#5#4#<where>*<own>##` attributes the view call to that unit. The
selection stays for later streams until the next activation.

### Errors

| Status | `error` | When |
| --- | --- | --- |
| `409` | `call_not_current` | The `call_id` is unknown (also from an earlier boot), ended, or not the current call; for unlock: not that unit's call or ended more than 60 s ago. The body carries `current_call_id` (or `null`). Nothing is sent to the station. |
| `404` | `unknown_unit` | No unit with that id. |
| `409` | `station_busy` | Hang-up of a view that the display or the app holds, not the agent: the agent cannot end it. Nothing is sent to the station; the view call goes on. |
| `409` | `call_unit_pending` | `current` (also a video request without `unit`) while the ring call's unit is not known yet: from the ring until its caller frame or the default fallback (1 s). The body carries the ring's `call_id` and `retry_after_ms` (1-1000), the time left until the fallback. Nothing is sent to the station. A video request that the ring's own video answers is not refused. |
| `409` | `unit_video_unsupported` | On-demand video of a unit whose address the station does not view (not `2…`, or 96 and above before `#`), also while a view runs, which goes on; only the ring's own video is shown whatever unit is asked. |
| `400` | `invalid_call_id` | Empty or longer than 32 characters. |

### Events

All carry the 2.x envelope (`event_id`, `type`, `occurred_at`, `data`).

| `type` | `data` |
| --- | --- |
| `doorbell.pressed` | the 3.0.0 data (`raw` for a ring frame) plus `call_id`, `unit` (`null` until a caller frame or the fallback names it) and `attribution` |
| `call.caller_identified` | `call_id`, `unit`, `where`, `action_where`, `attribution`, `raw` (`null` for the fallback). Again when a later caller frame names another unit or replaces the fallback. |
| `call.answered` | `call_id`, `unit`, `answered_by` |
| `call.view_started` | `call_id`, `unit` (a view frame `*8*1#5#4#<where>*…##` opened a view) |
| `call.ended` | `call_id`, `unit`, `kind`, `reason` |
| `station.call_state` | `code`, `state` (see Station call state; `null` for a code without a proven meaning), on every change |
| `door.opened`, `door.closed` | `unit`, `where`, `raw`; on a change of the unit's door state. The first door frame of a unit also sends `outdoor_units.changed`. |
| `doorbell.view_requested` | adds `call_id` and `unit` when the frame names the unit |
| `door_unlock.started`, `door_unlock.ended` | add `unit` when the address is a unit's lock, and `call_id` of its live call |
| `outdoor_units.changed` | `count`; Home Assistant reads `GET /api/v1/outdoor-units` again |

## Home Assistant

### Devices and entities

Station device: display, ringer, answering machine, memos, codec, camera
resolution, agent, maintenance, diagnostics, LED, announcements, stair light,
activations, Home Call, the `stair_light_event` event entity (event type
`activated` on `stair_light.activated`), and the station `ring` event entity (key `ring`,
event type `ring`, attributes `call_id` and `unit: null`): the indoor station
ringing. It fires at once on `doorbell.pressed`, on every station, also with
one unit.

Every outdoor unit, also the only one:

| Entity | Key | Notes |
| --- | --- | --- |
| `event` | `doorbell` | device class `doorbell`, event type `ring`; attributes `call_id`, `unit`, `unit_name`, `attribution`, `camera_entity_id` (the media camera). |
| `camera` | `camera` | The default unit's camera is the media camera (ring, answer, on-demand; key `doorbell_camera` of the station); like every unit camera it appears with its unit. Another unit's camera shows a still of the live picture while it has the current call (the station switches the picture to the caller), else its last visitor image. |
| `button` | `door` | Unlocks this unit (`outdoor-units/{unit_id}/actions/unlock`); attributes `lock_address` (the unit's `lock_where`) and `lock_name` (the name the agent reports for that address, else the unit's name), the same for every unit. |
| `event` | `door_event` | Event type `opened` on this unit's `door_unlock.started` (the agent names the unit of the lock address); attribute `call_id` while the unit has a call. |
| `sensor` | `call` | `idle`, `ringing`, `answered`, `viewing`; attribute `call_id`. |
| `binary_sensor` | `door_contact` | Only for a unit whose `door` is not `null`, added when `outdoor_units.changed` first reports its contact. Device class `door`, on while `open`; seeded from `GET /api/v1/outdoor-units`, then `door.opened` / `door.closed`. Unknown after `agent.restarted` until the next frame (the station has no query for it). |
| `image` | `last_visitor` | The latest retained image of a call of this unit. |

The unit event fires when the agent has named the call's unit, with the same
`call_id` as the station ring: on `call.caller_identified` (~0.3 s, at most
1 s), also with one unit, or at once for a `doorbell.pressed` that carries its
unit. It fires once per unit and press; a later identification that moves the
call to another unit fires that unit's event. A press during a live ring
session keeps its call (and state) and fires both events again. A unit the station had not
listed fires when its entities are added after the units are read again
(`call_sync`, `ring_unit_id` in the bus event). Everything that does not
depend on the unit (station ring event, card ring view, ring preview, image
capture) starts with `doorbell.pressed`. Blueprints default to the unit
event; the station ring is the trigger for the fastest notification, without
the unit's name.

Event delivery to Home Assistant no longer depends on which entities are
enabled. Only `agent.diagnostics_changed` stays tied to its sensor (large and
frequent while writing; the sensor is disabled by default).

The bus event `bticino_c300x_agent_event_received` keeps every event,
rings included: the card, the ring preview, captures and the event entities
listen to it. Its `event_type` is the stable key; `unit` and `call_id` are
`null` while not known (a door frame names its unit also outside a call),
`device_id` is the unit's device, else the station's, and `null` while the
entry waits for its station id (an entry from before 3.1.0 until the agent
update Repair): the event is fired all the same. Automations should
trigger on the event entities. There is no event for an action Home
Assistant ran (`run_action`, a display tile): automations react to the entity
that was switched; a door and the stair light fire the Door and Stair light
event entities, whatever opened the door.

The media camera's attributes tell the card about the current call:
`call_id`, `call_state`, `call_unit`, `call_unit_name` and `door_entity_id`
(the door button of the call's unit, else of the default unit; none while
the ring call's unit is not known yet, so the card's door button is disabled
until the caller frame or the default fallback names it).

### Card

The card follows the active call: it shows the calling unit's name next to
its title while the call rings or is answered, answers and hangs up with the
call's `call_id` (a `call_not_current` reply to a hang-up counts as done),
and its door button opens the calling unit (`door_entity_id`). Without a
live ring, a live on-demand view is the current call (`call_state:
"viewing"`): it cannot be answered, and the card ends it by its `call_id`
when the Stop doorbell video button is missing or disabled. It uses the
media camera as before. Station buttons are found through the camera's
device: the media camera sits on the default unit's device, whose
`via_device_id` is the station. Its services target that station device,
never the camera: the camera's unit target would refuse another unit's call,
while a station target leaves the check to the `call_id`, so a
`call_not_current` hang-up means the call has ended. It has no unit selector
and no per-unit video in 3.1.0 (that comes with phase D, later, needs a card
concept).

### Services

Services take a Home Assistant target (device or entity) instead of
`entry_id`. A unit target names the unit; a station target means the current
call's unit, else the default unit.

- `answer_call`, `hangup_call`: optional `call_id`; without it the target's
  current call. With a unit target the call must be that unit's, also with
  `call_id`. `409 call_not_current` becomes a translated error.
- An unlock or a video request for the current call's unit (a station target,
  the display's door tile) that the agent answers `409 call_unit_pending` is
  asked again every 0.15 s until the agent names the unit, at most
  `retry_after_ms` + 0.3 s; it is never sent to another unit. After that it
  becomes a translated error.
- `activate_doorbell_video` with a unit target; `capture_doorbell_call` and
  `evaluate_ring_analysis` act on the call's unit (`lock_id` is gone; the
  unlock opens the target unit, with a station target the calling unit).
- A target resolves to exactly one station: several devices, an unknown
  device or entity, or an entity of another integration is refused. A unit
  device is recognised by its `:unit:` identifier.
- Renamed: `answer_doorbell_call` -> `answer_call`, `hangup_doorbell_call`
  -> `hangup_call`.
- Removed (use the buttons): `unlock_door`, `stair_light`,
  `stop_doorbell_video`, `reboot`, `reload_gui`, `run_device_activation`,
  `delete_latest_video_message`, `delete_latest_text_memo`,
  `delete_latest_voice_memo`. The buttons exist only while the agent offers
  the action; the services' own capability checks went with them.
- The notify `mode` field is removed; the display switches decide.

### Migration (config entry version 2)

A new entry stores the station id from the config flow and needs no
migration. An entry from before 3.1.0 is migrated once, at the first setup
with a 3.1.0 agent, before the platforms load. Until then it builds no
entities: with the station offline it reloads when the station answers;
with an outdated agent the agent update Repair is open and reloads it.


| From | To |
| --- | --- |
| device `(bticino_c300x, <entry_id>)` | `(bticino_c300x, <station_id>)`, same HA device |
| `<entry_id>_<key>` | `<station_id>_<key>` |
| `<entry_id>_doorbell_camera` | `<station_id>_doorbell_camera`, on the default unit's device |
| `<entry_id>_doorbell_event` | `<station_id>_unit_<default>_doorbell`, on the default unit's device |
| `<entry_id>_door_unlock` | `<station_id>_unit_<default>_door`, on the default unit's device |
| `<entry_id>_doorbell_state`, `<entry_id>_agent_event` | removed from the registry |

At every setup with the station's units, before the platforms load, a unit
device whose id is a reported unit's full `where` (with `_` for `#`) but no
reported unit's id is removed with its entities: the default unit behind an
apartment interface (`20#2`) had the id `20_2` before the agent gave it the
default address's id (`20`), and `<station_id>:unit:20_2` had a door button
and ring event of its own (`identity_migration.async_remove_merged_unit_devices`).

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
