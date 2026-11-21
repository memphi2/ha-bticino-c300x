"""Sound for the device speaker: speech and other media from Home Assistant."""

from __future__ import annotations

import io
import wave
from urllib.parse import urlsplit

from homeassistant.exceptions import HomeAssistantError

from .ring_capture import _async_run_ffmpeg_command

# The agent takes about two minutes; a spoken message is far shorter.
ANNOUNCEMENT_MAX_SECONDS = 110
ANNOUNCEMENT_DEFAULT_VOLUME = 0.6
_RATE = 8000
# The speaker needs a moment after it is switched on, and the last syllable
# must not be cut. The small speaker carries no bass; an even loudness keeps
# quiet speech understandable.
_FILTER = "highpass=f=200,loudnorm=I=-16:TP=-1.5,adelay=300,apad=pad_dur=0.3"


async def async_sound_for_device(url: str) -> bytes:
    """Turn media into the one format the device plays: WAV, 8000 Hz, 16 bit, mono."""

    if urlsplit(url).scheme not in ("http", "https"):
        raise HomeAssistantError("C300X announcement media must be an http or https address")
    pcm = await _async_run_ffmpeg_command(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-protocol_whitelist", "http,https,tcp,tls,crypto",
            "-i", url, "-vn", "-t", str(ANNOUNCEMENT_MAX_SECONDS),
            "-af", _FILTER, "-ac", "1", "-ar", str(_RATE), "-f", "s16le", "-",
        ],
        command_timeout=60,
        error_prefix="C300X announcement could not be converted",
        capture_stdout=True,
    )
    if len(pcm) < 2:
        raise HomeAssistantError("C300X announcement media has no sound")
    sound = io.BytesIO()
    with wave.open(sound, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_RATE)
        out.writeframes(pcm[: len(pcm) - len(pcm) % 2])
    return sound.getvalue()


def announcement_seconds(sound: bytes) -> float:
    """Length of a sound made by async_sound_for_device."""

    return max(0, len(sound) - 44) / (_RATE * 2)


def announcement_volume(level: float) -> int:
    """The agent's volume, 1 to 100, for a Home Assistant volume level."""

    return max(1, min(100, round(level * 100)))
