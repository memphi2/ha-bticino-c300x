from __future__ import annotations

import sys
import types

if "homeassistant.components.http" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    http = types.ModuleType("homeassistant.components.http")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistantView:  # pragma: no cover - import-time stub only
        extra_urls: list[str] = []

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    http.HomeAssistantView = HomeAssistantView
    components.http = http
    homeassistant.components = components
    sys.modules["homeassistant.components.http"] = http

from custom_components.bticino_c300x.const import DOMAIN
from custom_components.bticino_c300x.media import (
    C300XVideoMessageMediaView,
    _should_transcode_video_message,
)


def test_video_message_view_exposes_playable_mp4_route() -> None:
    assert C300XVideoMessageMediaView.url == (
        f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video"
    )
    assert C300XVideoMessageMediaView.extra_urls == [
        f"/api/{DOMAIN}/video-messages/{{entry_id}}/{{message_id}}/video.mp4"
    ]


def test_video_message_transcode_decision_targets_non_browser_containers() -> None:
    assert _should_transcode_video_message("video/x-msvideo")
    assert _should_transcode_video_message("video/x-matroska; charset=binary")
    assert not _should_transcode_video_message("video/mp4")
