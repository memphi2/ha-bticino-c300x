"""Video-message and voice-memo services fail fast on a C100X entry, before any agent request."""

import asyncio
from types import SimpleNamespace

import pytest
from c100x_answering_capabilities import C100X, C300X
from homeassistant.exceptions import ServiceValidationError

from custom_components.bticino_c300x.capabilities import (
    stored_media_offered,
    voice_memos_supported,
)
from custom_components.bticino_c300x.use_cases.memos import MemosUseCase
from custom_components.bticino_c300x.use_cases.messages import MessagesUseCase


class _Api:
    def __getattr__(self, name):
        raise AssertionError(f"no agent request expected: {name}")


def _entry(capabilities):
    return SimpleNamespace(entry_id="e", runtime_data=SimpleNamespace(capabilities=dict(capabilities), api=_Api()))


@pytest.mark.parametrize(("call", "key"), [
    (lambda entry: MemosUseCase(None, entry).play_latest_voice_memo("media_player.x"), "voice_memo_not_available"),
    (lambda entry: MemosUseCase(None, entry).delete_latest_voice_memo(), "voice_memo_not_available"),
    (lambda entry: MessagesUseCase(None, entry).play_latest_video_message("media_player.x"),
     "video_message_not_available"),
    (lambda entry: MessagesUseCase(None, entry).delete_latest_video_message(), "video_message_not_available"),
])
def test_c100x_entry_refuses_before_any_request(call, key) -> None:
    with pytest.raises(ServiceValidationError) as raised:
        asyncio.run(call(_entry(C100X)))
    assert raised.value.translation_key == key


def test_voice_memos_follow_the_agent_and_older_agents_keep_them() -> None:
    assert not voice_memos_supported(C100X)
    assert voice_memos_supported(C300X)
    assert voice_memos_supported({"memos": {"supported": True}})
    assert not voice_memos_supported({"memos": {"supported": False, "voice": True}})


def test_only_a_reported_capability_hides_stored_media() -> None:
    assert not stored_media_offered(C100X, "video") and not stored_media_offered(C100X, "voice")
    assert stored_media_offered(C300X, "video") and stored_media_offered(C300X, "voice")
    assert stored_media_offered({}, "video") and stored_media_offered({}, "voice")
