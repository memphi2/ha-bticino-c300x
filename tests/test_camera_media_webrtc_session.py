from __future__ import annotations

from custom_components.bticino_c300x.camera_media.webrtc_session import (
    webrtc_message_is_error,
)


class _AsDictMessage:
    def __init__(self, data: object) -> None:
        self._data = data

    def as_dict(self) -> object:
        return self._data


class _BrokenAsDictMessage:
    def as_dict(self) -> object:
        raise RuntimeError("boom")


class WebRTCError:
    pass


def test_webrtc_message_error_detection_accepts_provider_message_shapes() -> None:
    assert webrtc_message_is_error({"type": "error"}) is True
    assert webrtc_message_is_error({"type": "answer"}) is False
    assert webrtc_message_is_error(_AsDictMessage({"type": "error"})) is True
    assert webrtc_message_is_error(_AsDictMessage({"type": "answer"})) is False
    assert webrtc_message_is_error(_AsDictMessage("not-a-dict")) is False
    assert webrtc_message_is_error(_BrokenAsDictMessage()) is False
    assert webrtc_message_is_error(WebRTCError()) is True
