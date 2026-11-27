# Classe 100X: Use

This page lists what works on a Classe 100X and where it differs from the
Classe 300X.

Pages: [1. Setup](1-setup.md) | [3. Station display](3-display.md) |
[4. Troubleshooting](4-troubleshooting.md) |
[5. Update and removal](5-update-and-removal.md) |
[Reference](../reference.md)

## What Works

Everything here is **in test** in
[issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51).

| Feature | Classe 100X | How to use it |
| --- | --- | --- |
| Card, live video, Ring Call, Home Call, talking | Yes | As on the Classe 300X: [card and calls](../classe-300x/2-use.md#doorbell-card) |
| Forwarding select | Yes | [Forwarding](../classe-300x/2-use.md#video-ring-calls-and-home-calls) |
| Door unlock, stair light, activations | Yes | [Activations](../classe-300x/2-use.md#door-stair-light-and-activations) |
| Visitor images, ring recordings | Yes | [Visitor images](../classe-300x/2-use.md#visitor-images), [Recording a ring](../classe-300x/2-use.md#recording-a-ring) |
| Picture controls | Yes | [below](#picture) |
| Camera quality | Low stream only | [below](#picture) |
| Door level, fine adjustment | Yes, in software | [below](#sound) |
| Ringer volume | Yes | **Ringer volume**, `0` to `10`. |
| Ringer mute, touch tone | After the display activation | [3. Station display](3-display.md) |
| Display pages and display notices | After the display activation | [3. Station display](3-display.md) |
| Blueprints | Yes, except speech | [Blueprints](../classe-300x/2-use.md#blueprints) |

## What Does Not Work

- **Speaker and announcements:** no `tts.speak`, no spoken notices. The
  station has no safe way to play sound that yields to a door call.
- **Answering machine, video messages, voice memos:** the firmware switches
  the answering machine off on this station.
- **Text memos:** not offered, neither in Home Assistant nor on the display.
- **Audio codec select:** the station's audio stays Speex. The agent converts
  it, so the browser still gets PCMU.
- **Camera resolution select and 960x576.**
- **Message LED**, **home page buttons**, **Reload device display**.

Home Assistant creates no entities for these.

## Picture

- The picture sliders change brightness, contrast and saturation of the live
  picture. The percentages are the station's day values. In the dark the
  station switches to its night values; the sliders then show the nearest
  10 % step.
- **Configure > Camera quality** sets the low stream. **Saving restarts the
  station.**

| Picture size | Bit rate | Frame rate |
| --- | --- | --- |
| 352x288 to 720x576 (factory 640x480) | 100-2000 kbit/s (factory 800) | 5-25 fps (factory 12) |

## Sound

**Door level** (Stock, +3, +6, +9, +12 dB) and **Fine adjustment (dB)**
(-10 to +10) under **Configure > Video and audio** set the door sound in the
live view, in calls and in recordings. On the Classe 100X the agent adds both
in software; calls in the BTicino app are not affected.

## Notifications

After the [display activation](3-display.md) the Notify action
(`notify.bticino_c300x`) works with `display` only. The notice wakes the
screen without a tone; a positive `sound_duration`, `tts` and `led` are
refused.
