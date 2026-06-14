from __future__ import annotations

from custom_components.bticino_c300x.video_messages import (
    latest_video_message_attributes,
    latest_video_message_id,
    video_message_media_source_id,
    video_message_media_url,
    video_message_original_media_url,
)


def test_latest_video_message_prefers_newest_video_entry() -> None:
    assert (
        latest_video_message_id(
            {
                "messages": [
                    {"id": "message_old", "has_video": True, "unix_time": 1709990000},
                    {"id": "message_text", "has_video": False, "unix_time": 1710009999},
                    {"id": "message_new", "has_video": True, "unix_time": 1710000000},
                ]
            }
        )
        == "message_new"
    )


def test_latest_video_message_returns_empty_metadata_without_video() -> None:
    messages = {"total": 0, "unread": 0, "read": 0, "messages": []}

    assert latest_video_message_id(messages) is None
    assert latest_video_message_attributes(messages, "entry 1") == {
        "has_message": False,
        "total": 0,
        "unread": 0,
        "read": 0,
        "latest_message_id": None,
        "latest_message_at": None,
        "media_mime_type": None,
        "media_size": None,
        "media_content_id": None,
        "media_url": None,
        "playback_mime_type": None,
        "original_media_url": None,
    }


def test_video_message_media_ids_are_ha_local() -> None:
    assert video_message_media_source_id("entry 1", "message_1") == (
        "media-source://bticino_c300x/entry%201/message_1"
    )
    assert video_message_media_url("entry 1", "message_1") == (
        "/api/bticino_c300x/video-messages/entry%201/message_1/video.mp4"
    )
    assert video_message_original_media_url("entry 1", "message_1") == (
        "/api/bticino_c300x/video-messages/entry%201/message_1/video"
    )


def test_latest_video_message_attributes_prefer_playable_mp4_url() -> None:
    attributes = latest_video_message_attributes(
        {
            "total": 1,
            "messages": [
                {
                    "id": "message_1",
                    "has_video": True,
                    "media_mime_type": "video/x-msvideo",
                }
            ],
        },
        "entry 1",
    )

    assert attributes["media_mime_type"] == "video/x-msvideo"
    assert attributes["playback_mime_type"] == "video/mp4"
    assert attributes["media_url"] == (
        "/api/bticino_c300x/video-messages/entry%201/message_1/video.mp4"
    )
    assert attributes["original_media_url"] == (
        "/api/bticino_c300x/video-messages/entry%201/message_1/video"
    )
