from __future__ import annotations

from custom_components.bticino_c300x.memos import (
    latest_voice_memo_audio_id,
    voice_memo_media_source_id,
    voice_memo_media_url,
)


def test_latest_voice_memo_prefers_newest_playable_entry() -> None:
    assert (
        latest_voice_memo_audio_id(
            {
                "memos": [
                    {
                        "id": "voice/memo_old",
                        "kind": "voice",
                        "has_audio": True,
                        "unix_time": 1709990000,
                    },
                    {
                        "id": "voice/memo_empty",
                        "kind": "voice",
                        "has_audio": False,
                        "unix_time": 1710009999,
                    },
                    {
                        "id": "voice/memo_new",
                        "kind": "voice",
                        "has_audio": True,
                        "unix_time": 1710000000,
                    },
                ]
            }
        )
        == "voice/memo_new"
    )


def test_voice_memo_media_ids_are_ha_local() -> None:
    assert voice_memo_media_source_id("entry 1", "voice/memo_1") == (
        "media-source://bticino_c300x/voice/entry%201/memo_1"
    )
    assert voice_memo_media_url("entry 1", "voice/memo_1") == (
        "/api/bticino_c300x/voice-memos/entry%201/memo_1/audio"
    )
