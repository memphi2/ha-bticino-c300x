# Visitor Journal

Enable **Show visitor journal** in the doorstation card editor. It is off by
default and is not shown in Home Call mode. Open **Visitor journal** and select
a visit to view its saved image or video. Use the image/video icons when both
are available. Previous/next buttons, keyboard arrows and horizontal mobile
swipes on images browse visits; Escape or Close returns to the list. Gestures
on a video keep controlling that video, without changing visits. Video playback is
manual. The viewer shows the image capture/video file completion time; visits
without media show the ring's HA observation time. Opening or browsing the journal never starts a live stream, requests a
microphone, records a clip or asks the C300X for another image.

Only rings observed by Home Assistant after this feature is installed are
included. Existing images/recordings are reused when their acquisition can be
associated with that ring. There is no time-based backfill of older archives.
Visits without media are still listed; missing, expired or replaced files show
an unavailable state. Older unlinked archives remain in Home Assistant Media.

## Outcomes

**Answer confirmed** requires an existing native ring-owned event explicitly
reporting `ring_answered: true`, in source order after the ring. This confirms
the call was answered, not that a person answered: an existing capture automation
can also answer a Ring Call. Button clicks, preview playback, answer requests,
generic call events and media-close events are not sufficient evidence.
All other outcomes are **unknown**. There is no authoritative missed-call event,
so the journal never labels these calls missed. Restart/reload does not restore
an active call; lost close events stop being eligible for outcome/media association
after two minutes without changing the recorded outcome.

## Storage And Access

The journal stores bounded metadata in HA's private `.storage`, separately for
each config entry: at most 1,000 visits or 1 MiB, whichever is reached first.
It shares **Visitor Snapshot > Retention** (default 14 days, range 1–365 days).
Expiry is enforced on access, on startup and by the existing snapshot cleanup
timer, including when Save images is off. The card toggle controls visibility,
not collection. Removing the integration entry removes its journal metadata.

No image or clip is copied. Snapshot lifetime and quotas remain owned by the
existing snapshot store. Journal expiry removes links, not MP4 files; existing
recordings retain their existing management policy. Only successful default-path
ring captures are linked. On-demand recordings and user-supplied output paths
are not guessed into a visit. Clips above the existing 64 MiB media bound are
not linked. Clip file identity is checked again during playback so replacing a
file cannot silently change the media of an older visit.

Journal metadata and playback use the existing authenticated snapshot/camera
read-permission decision, with entry isolation and no public or token-bearing
media URLs. The viewer releases object URLs and stops video on transitions,
close, reconfiguration and detach. This does not change access rules of other
existing interfaces: the legacy ring-capture URL requires HA login, and HA's
local-media browser has its own access policy. Restrict those separately when
needed. No device state, event subscriptions, native agent or device files are
changed by this feature.
