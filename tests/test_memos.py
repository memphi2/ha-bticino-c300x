from __future__ import annotations

import pytest

from custom_components.bticino_c300x.memos import (
    MAX_MEMO_STATE_LENGTH,
    latest_memo_attributes,
    latest_voice_memo_audio_id,
    memo_kind_counts,
    memo_kind_items,
    memo_kind_label,
    memo_state_text,
    memo_text_was_state_truncated,
    voice_memo_media_source_id,
    voice_memo_media_url,
    voice_memo_title,
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


def test_memo_kind_filters_counts_and_latest_ids() -> None:
    memos = {
        "memos": [
            {"id": "text/old", "kind": "text", "read": True, "unix_time": 1},
            {"id": "text/new", "kind": "text", "read": False, "unix_time": 3},
            {"id": "voice/new", "kind": "voice", "read": False, "unix_time": 2},
            "ignored",
            {"id": "ignored", "kind": "other", "read": False, "unix_time": 4},
        ]
    }

    assert [memo["id"] for memo in memo_kind_items(memos, "text")] == [
        "text/old",
        "text/new",
    ]
    assert memo_kind_counts(memos, "text") == (1, 1)


def test_memo_labels_are_localized() -> None:
    assert memo_kind_label("voice", "de") == "Sprach-Memo"
    assert memo_kind_label("voice", "it") == "Memo vocale"
    assert memo_kind_label("voice", "fr") == "Memo vocal"
    assert memo_kind_label("voice", "en") == "Voice memo"
    assert memo_kind_label("text", "de") == "Text-Memo"


def test_latest_memo_attributes_include_text_and_voice_metadata() -> None:
    memos = {
        "voice_total": 2,
        "text_total": 1,
        "memos": [
            {
                "id": "voice/new",
                "kind": "voice",
                "read": False,
                "has_audio": True,
                "audio_mime_type": "audio/wav",
                "audio_size": 42,
                "iso_time": "2026-06-13T12:00:00+00:00",
                "unix_time": 3,
            },
            {
                "id": "voice/old",
                "kind": "voice",
                "read": True,
                "has_audio": False,
                "unix_time": 1,
            },
            {
                "id": "text/1",
                "kind": "text",
                "read": True,
                "text": "x" * (MAX_MEMO_STATE_LENGTH + 1),
                "date": "2026-06-13",
                "unix_time": 2,
            },
        ],
    }

    voice_attrs = latest_memo_attributes(memos, "voice", entry_id="entry 1")
    assert voice_attrs == {
        "kind": "voice",
        "has_memo": True,
        "total": 2,
        "unread": 1,
        "read": 1,
        "latest_memo_id": "voice/new",
        "latest_memo_at": "2026-06-13T12:00:00+00:00",
        "latest_memo_read": False,
        "has_audio": True,
        "audio_mime_type": "audio/wav",
        "audio_size": 42,
        "media_content_id": "media-source://bticino_c300x/voice/entry%201/new",
        "media_url": "/api/bticino_c300x/voice-memos/entry%201/new/audio",
    }

    text_attrs = latest_memo_attributes(memos, "text", include_text=True)
    assert text_attrs["total"] == 1
    assert text_attrs["latest_text"] == "x" * (MAX_MEMO_STATE_LENGTH + 1)
    assert text_attrs["text_truncated"] is True


def test_voice_memo_titles_and_invalid_ids() -> None:
    assert voice_memo_title(
        {"id": "voice/1", "iso_time": "2026-06-13T12:00:00+00:00"},
        language="en",
    ) == "Voice memo 2026-06-13T12:00:00+00:00"
    assert voice_memo_title({"id": "voice/1"}, language="en") == "Voice memo voice/1"
    with pytest.raises(ValueError, match="voice memo id"):
        voice_memo_media_url("entry", "bad")


def test_memo_state_text_is_stable() -> None:
    assert memo_state_text(None) is None
    assert memo_state_text("") is None
    assert memo_state_text("short") == "short"
    long_text = "x" * (MAX_MEMO_STATE_LENGTH + 1)
    assert memo_state_text(long_text) == f"{'x' * (MAX_MEMO_STATE_LENGTH - 3)}..."
    assert memo_text_was_state_truncated(long_text) is True
    assert memo_text_was_state_truncated("short") is False
