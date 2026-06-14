"""SDP helpers for C300X WebRTC media negotiation."""

from __future__ import annotations

SDP_DIRECTIONS = {"a=sendonly", "a=recvonly", "a=sendrecv", "a=inactive"}


def offer_audio_section(offer_sdp: str) -> str | None:
    """Return the SDP audio media section from a WebRTC offer."""

    normalized = offer_sdp.replace("\r\n", "\n")
    sections = normalized.split("\nm=")
    for index, section in enumerate(sections):
        if index > 0:
            section = "m=" + section
        if section.startswith("m=audio "):
            return section
    return None


def offer_audio_directions(audio_section: str) -> set[str]:
    """Return SDP direction attributes from an audio media section."""

    return {line.strip() for line in audio_section.splitlines() if line.strip() in SDP_DIRECTIONS}


def offer_has_audio(offer_sdp: str) -> bool:
    """Return whether the WebRTC offer contains an audio media section."""

    return offer_audio_section(offer_sdp) is not None


def offer_accepts_incoming_audio(offer_sdp: str) -> bool:
    """Return whether HA should add a device audio track to the answer."""

    section = offer_audio_section(offer_sdp)
    if section is None:
        return False
    directions = offer_audio_directions(section)
    return "a=inactive" not in directions and "a=sendonly" not in directions


def offer_should_use_audio_stream(offer_sdp: str) -> bool:
    """Return whether HA should request device audio for this offer."""

    return offer_accepts_incoming_audio(offer_sdp)


def offer_can_send_microphone(offer_sdp: str) -> bool:
    """Return whether the browser offer can send microphone audio to HA."""

    section = offer_audio_section(offer_sdp)
    if section is None:
        return False
    directions = offer_audio_directions(section)
    return "a=inactive" not in directions and "a=recvonly" not in directions
