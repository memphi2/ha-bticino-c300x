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
        self.values: dict[str, Any] = {"bitrate_kbps": 800, "fps": 15, "size": "688x480"}
        self.supported = supported
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.writes: list[dict[str, Any]] = []

    async def async_camera_quality(self, **changes: Any) -> dict[str, Any]:
        if changes:
            self.writes.append(changes)
            if self.fail_write:
                raise C300XAgentApiError("refused")
            self.values.update(changes)
        elif self.fail_read:
            raise C300XAgentApiError("offline")
        return {"ok": True, "supported": self.supported, **self.values,
                "running_bitrate_kbps": 800, "running_fps": 15, "running_size": "688x480",
                "bitrate_min": 300, "bitrate_max": 3000, "fps_min": 5, "fps_max": 24,
                "sizes": ["688x480", "720x576"]}


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
    assert form["data_schema"]({}) == {"size": "688x480", "bitrate_kbps": 800, "fps": 15}
    assert form["description_placeholders"] == {"running": "688x480, 800 kbit/s, 15 fps"}


def test_both_changed_values_are_saved_in_one_write() -> None:
    api = _QualityApi()
    result = _open(_entry(api), {"size": "720x576", "bitrate_kbps": 3000.0, "fps": 24.0})
    # One write: the device restarts once for all values.
    assert api.writes == [{"bitrate_kbps": 3000, "fps": 24, "size": "720x576"}]
    assert (result["type"], result["step_id"]) == ("menu", "init")


def test_only_a_changed_value_is_sent_and_no_change_writes_nothing() -> None:
    api = _QualityApi()
    _open(_entry(api), {"size": "688x480", "bitrate_kbps": 800.0, "fps": 20.0})
    assert api.writes == [{"fps": 20}]
    result = _open(_entry(api), {"size": "688x480", "bitrate_kbps": 800.0, "fps": 20.0})
    assert api.writes == [{"fps": 20}]
    assert (result["type"], result["step_id"]) == ("menu", "init")


def test_a_failed_write_keeps_the_form_with_what_was_typed() -> None:
    api = _QualityApi(fail_write=True)
    form = _open(_entry(api), {"size": "688x480", "bitrate_kbps": 3000.0, "fps": 15.0})
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


def test_firmware_3_offers_its_low_stream_and_keeps_a_size_not_offered() -> None:
    api = _QualityApi()
    api.values = {"bitrate_kbps": 180, "fps": 10, "size": "352x288"}
    real = api.async_camera_quality

    async def low(**changes: Any) -> dict[str, Any]:
        return {**await real(**changes), "stream": "low", "sizes": ["400x288"], "running_size": "352x288"}

    api.async_camera_quality = low  # type: ignore[method-assign]
    form = _open(_entry(api))
    sizes = form["data_schema"].schema["size"].config["options"]
    assert sizes == ["400x288", "352x288"]
    assert "camera_quality" in _options_menu_of(_entry(api))



def test_a_device_back_since_the_explanation_shows_the_values_instead() -> None:
    # The explanation had no fields; the device came back before it was sent.
    api = _QualityApi()
    form = _open(_entry(api), {})
    assert (form["step_id"], form["errors"]) == ("camera_quality", {})
    assert form["data_schema"]({}) == {"size": "688x480", "bitrate_kbps": 800, "fps": 15}
    assert api.writes == []


def test_a_value_in_the_file_outside_the_limits_can_stay_while_another_changes() -> None:
    # The agent keeps a saved value outside its limits; the form must let it through.
    api = _QualityApi()
    api.values = {"bitrate_kbps": 180, "fps": 30, "size": "688x480"}
    schema = _open(_entry(api))["data_schema"]
    assert schema({"size": "720x576"}) == {"size": "720x576", "bitrate_kbps": 180, "fps": 30}
    for wrong in ({"fps": 31}, {"fps": 4}, {"bitrate_kbps": 3050}, {"bitrate_kbps": 170}):
        try:
            schema(wrong)
        except Exception:  # noqa: BLE001 - any refusal of the selector
            continue
        raise AssertionError(f"{wrong} was taken")


def test_values_sent_while_the_device_is_away_are_not_dropped_silently() -> None:
    api = _QualityApi(fail_read=True)
    form = _open(_entry(api), {"size": "720x576", "bitrate_kbps": 3000.0, "fps": 24.0})
    assert (form["step_id"], form["errors"]) == ("camera_quality", {"base": "cannot_connect"})
    assert api.writes == []


def test_a_new_value_outside_the_limits_is_named_before_anything_is_sent() -> None:
    api = _QualityApi()
    api.values = {"bitrate_kbps": 180, "fps": 30, "size": "688x480"}
    form = _open(_entry(api), {"size": "688x480", "bitrate_kbps": 200.0, "fps": 27.0})
    assert form["errors"] == {"bitrate_kbps": "camera_quality_out_of_range", "fps": "camera_quality_out_of_range"}
    assert api.writes == []
    _open(_entry(api), {"size": "688x480", "bitrate_kbps": 180.0, "fps": 24.0})
    assert api.writes == [{"fps": 24}]
