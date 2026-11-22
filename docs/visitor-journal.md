# Media History

The doorstation card shows live video, saved HA snapshots and saved HA capture
videos in one media window. **Browse saved images and videos** is on by default
(`show_media_history: true`). Use the arrows on the picture to browse the available media
chronologically, starting with the newest item. The arrow tooltips are **Older
media** and **Newer media**; **Newer media** on the newest item leaves history
without starting a live stream. A label on the picture names what is shown:
**Snapshot**, **Recording** or **Live**. There is no separate visitor list to open.

Click the picture to open the card as a large window with the same controls,
including calls, door and light. Close it with the close button, Escape or a
click beside the window; a running stream or call continues. Full screen is
available inside this window.

Saved videos have play/pause, a seek timeline and volume/mute controls. Their recording timestamp appears
at the lower right. Snapshots already contain their date and time when
**Visitor Snapshot > Write date and time into the image** is enabled; the card
does not add a second stamp. Video playback starts with Play, not automatically,
and stops when you leave a saved video.

In HA's Sections layout, the doorstation card requires at least six rows for
the picture, media controls and call actions. Very narrow cards place name and
status above the action buttons. The dedicated Home Call card uses two rows.

Live video and incoming rings take precedence over archive playback. Browsing
or playing saved media never starts, answers or stops a device call, requests
the microphone, takes a new image or records a clip. Use the existing live and
call controls for those actions. Home Call, door/light buttons, card name,
status display and their existing options remain available. History is not
shown in the dedicated Home Call mode.

To hide history on one card, turn off **Browse saved images and videos** in its editor or
set `show_media_history: false` in that card's YAML. This is independent of
**Show media readiness**, **Open door** and **Staircase light**. It does not
disable live video, stop image saving or recording automations, or delete files.

## Automatic Images

The existing device-wide **Save images** switch must be on for automatic
snapshots. It is on by default and applies to doorbell rings and video streams
started through HA, not just rings. Under **Configure > Visitor Snapshot**,
choose the image size, capture delay, retention and date/time stamp. Defaults
are **800x480**, **3 seconds**, **14 days** and the stamp on. The image uses the
native display framebuffer, not the encoded stream resolution. Previously
saved image sizes remain unchanged; select 800x480 to use native proportions
for future captures. A call or stream
that ends before the configured delay may not produce an image.

Capture runs server-side without an open card. The agent reads the existing
camera picture; JPEG encoding and storage happen in HA, with no image files
written to the C300X. See [Visitor images](feature-reference.md#visitor-images)
for the capture and storage details.

Turning **Save images** off stops new automatic images and hides snapshots
from the card, including history. It does not turn off saved-video history
or clip automations. Existing images remain in HA Media until retention or
storage limits remove them; cleanup continues with the switch off.

## Recording Videos

**Browsing media history does not record clips.** Configure a capture automation
separately. Only HA snapshots and HA recordings made by
`bticino_c300x.capture_doorbell_call` belong here. The C300X's built-in
answering-machine recordings are separate and are not part of this history.

For automatic recordings on rings, use the existing bundled blueprint:

1. Check **Media readiness** and set **Forwarding** to **Home Assistant** for
   Ring Calls.
2. Open **Settings > Automations & scenes > Blueprints**, select **C300X Ring
   capture** (`bticino_c300x/ring_capture.yaml`) and create an automation.
3. Select the C300X device. The blueprint derives its readiness sensor and
   matches ring events to that device; no manual entry ID is needed. It runs
   only when readiness is `ready` or `warning`.
4. Choose the duration (**5 seconds** by default, **1-15 seconds** allowed) and
   whether to include audio. **Include audio is on by default and answers the
   active Ring Call before recording.** Turn it off for video-only capture
   without answering. Leave the capture file directory at `/config/c300x`
   unless you need a different location for the WAV/JPEG/metadata workspace;
   this setting is not the MP4 output path.

Ring capture refuses to take over an already answered call. Audio capture or
an announcement is also refused while a client watches the ring preview;
video-only capture can share that preview. An audio capture may hang up the
call it answered during cleanup. This is recording-automation behavior, not
archive playback. See [Blueprints](blueprints.md) and
[Capture modes](feature-reference.md#capture-modes) for prerequisites and
call-ownership limits.

For an explicitly requested recording without a ring, the same service offers
`capture_mode: on_demand`. It requires idle media with no other camera client,
starts a live view and records video with optional audio. It does not answer
or hang up a Ring Call. The ring blueprint uses the default `ring` mode;
`announcement_path` is supported only in that mode. Both modes allow **1-15
seconds**, and overlapping captures for one device are rejected.

## Storage And Access

Media stays in its existing Home Assistant locations; history does not copy it:

| Media | Default location |
| --- | --- |
| Snapshots | `<HA media root>/c300x/snapshots/<device-directory>/` |
| Capture MP4s | `<HA media root>/c300x/`, normally `/media/c300x/` |
| Capture WAV/JPEG/metadata | `/config/c300x/captures/<capture_id>/` |

Snapshots use a per-device directory. Completed captures are indexed against
the C300X entry that made them, so devices sharing the MP4 directory do not
share card histories. New successful `ring` and `on_demand` captures using the
default MP4 output path are indexed automatically, even with history hidden.
Leave the service's `output_path` unset to use that path. Custom output paths
are not indexed, and arbitrary historic MP4s are not automatically imported.
Older clips already linked to that device can remain available. Clips above
the existing **64 MiB** playback limit are not included.

History uses **Visitor Snapshot > Retention** (**14 days** by default) and is
bounded to **1,000 media items per device**. Expiring a history link does not
delete its MP4. Manage MP4 storage separately; the capture-workspace cleanup
also does not delete MP4s. Snapshot cleanup does remove expired images and
enforces **1,000 images or 128 MiB per device**, whichever is reached first.
The card's visibility option changes none of these storage policies.

Missing, expired or replaced media cannot be played as the original item.
History and its playback require an authenticated HA user with the existing
snapshot/camera read permission. Other interfaces retain their own access
rules: HA's local-media browser uses HA media permissions, and the separate
capture playback endpoint requires HA login. Restrict those separately when
needed; hiding history is not an access restriction.
