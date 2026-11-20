"""The camera quality area of the settings: both values in one write, one restart."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_VIDEO_ENABLED,
)
from tests.test_config_flow_helpers import _options_flow, _options_menu_of


class _QualityApi:
    def __init__(self, *, supported: bool = True, fail_read: bool = False, fail_write: bool = False) -> None:
        self.values = {"bitrate_kbps": 800, "fps": 15}
        self.supported = supported
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.writes: list[dict[str, int]] = []

    async def async_camera_quality(self, **changes: int) -> dict[str, Any]:
        if changes:
            self.writes.append(changes)
            if self.fail_write:
                raise C300XAgentApiError("refused")
            self.values.update(changes)
        elif self.fail_read:
            raise C300XAgentApiError("offline")
        return {"ok": True, "supported": self.supported, **self.values,
                "running_bitrate_kbps": 800, "running_fps": 15, "bitrate_min": 300,
                "bitrate_max": 3000, "fps_min": 5, "fps_max": 25}


def _entry(api: _QualityApi | None, *, offered: bool = True, video: bool = True) -> SimpleNamespace:
    maintenance = {"supported": True, "camera_quality": offered}
    return SimpleNamespace(
        entry_id="entry-1",
        data={CONF_AGENT_HOST: "agent.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "token",
              CONF_VIDEO_ENABLED: video},
        options={},
        runtime_data=SimpleNamespace(capabilities={"maintenance": maintenance}, api=api),
    )


def _open(entry: SimpleNamespace, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
    flow = _options_flow(entry)
    flow.async_show_menu = lambda **kwargs: {"type": "menu", **kwargs}  # type: ignore[method-assign]
    return asyncio.run(flow.async_step_camera_quality(user_input))


def test_the_area_is_offered_only_with_video_where_the_agent_offers_it() -> None:
    assert "camera_quality" in _options_menu_of(_entry(_QualityApi()))
    assert "camera_quality" not in _options_menu_of(_entry(_QualityApi(), offered=False))
    assert "camera_quality" not in _options_menu_of(_entry(_QualityApi(), video=False))


def test_the_form_starts_from_the_values_on_the_device() -> None:
    form = _open(_entry(_QualityApi()))
    assert form["step_id"] == "camera_quality" and form["errors"] == {}
    assert form["data_schema"]({}) == {"bitrate_kbps": 800, "fps": 15}
    assert form["description_placeholders"] == {"running": "800 kbit/s, 15 fps"}


def test_both_changed_values_are_saved_in_one_write() -> None:
    api = _QualityApi()
    result = _open(_entry(api), {"bitrate_kbps": 3000.0, "fps": 25.0})
    # One write: the device restarts once for both values.
    assert api.writes == [{"bitrate_kbps": 3000, "fps": 25}]
    assert (result["type"], result["step_id"]) == ("menu", "init")


def test_only_a_changed_value_is_sent_and_no_change_writes_nothing() -> None:
    api = _QualityApi()
    _open(_entry(api), {"bitrate_kbps": 800.0, "fps": 20.0})
    assert api.writes == [{"fps": 20}]
    result = _open(_entry(api), {"bitrate_kbps": 800.0, "fps": 20.0})
    assert api.writes == [{"fps": 20}]
    assert (result["type"], result["step_id"]) == ("menu", "init")


def test_a_failed_write_keeps_the_form_with_what_was_typed() -> None:
    api = _QualityApi(fail_write=True)
    form = _open(_entry(api), {"bitrate_kbps": 3000.0, "fps": 15.0})
    assert form["step_id"] == "camera_quality"
    assert form["errors"] == {"base": "camera_quality_failed"}
    assert form["data_schema"]({})["bitrate_kbps"] == 3000


def test_an_unreachable_or_unsupported_device_explains_and_goes_back_to_the_menu() -> None:
    for entry, error in ((_entry(_QualityApi(fail_read=True)), "cannot_connect"),
                         (_entry(None), "cannot_connect"),
                         (_entry(_QualityApi(supported=False)), "camera_quality_unsupported")):
        form = _open(entry)
        assert form["errors"] == {"base": error}
        assert form["data_schema"]({}) == {}
        result = _open(entry, {})
        assert (result["type"], result["step_id"]) == ("menu", "init")
