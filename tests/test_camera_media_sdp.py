from __future__ import annotations

from custom_components.bticino_c300x.camera_media.sdp import (
    offer_accepts_incoming_audio,
    offer_audio_directions,
    offer_audio_section,
    offer_can_send_microphone,
    offer_has_audio,
    offer_should_use_audio_stream,
)


def test_offer_detects_audio_and_microphone_directions() -> None:
    assert offer_has_audio("v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n")
    assert offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert not offer_accepts_incoming_audio(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )
    assert not offer_has_audio("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n")

    assert offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert not offer_can_send_microphone(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )


def test_offer_uses_audio_whenever_offer_accepts_incoming_audio() -> None:
    assert offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=recvonly\r\n"
    )
    assert offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendrecv\r\n"
    )
    assert offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    )
    assert not offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=sendonly\r\n"
    )
    assert not offer_should_use_audio_stream(
        "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=inactive\r\n"
    )


def test_offer_audio_section_handles_audio_after_video_and_no_audio() -> None:
    offer = (
        "v=0\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n"
        "a=sendrecv\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        " a=sendrecv \r\n"
    )

    section = offer_audio_section(offer)

    assert section is not None
    assert section.startswith("m=audio ")
    assert offer_audio_directions(section) == {"a=sendrecv"}
    assert offer_audio_section("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n") is None
    assert not offer_accepts_incoming_audio("v=0\r\n")
    assert not offer_can_send_microphone("v=0\r\n")
