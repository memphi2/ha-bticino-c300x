"""Read or change the stock video-call picture through the authenticated agent."""

from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api_errors import C300XAgentApiError
from .schema_compat import vol

CONTROLS = ("brightness", "contrast", "saturation")


def picture_value(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in range(0, 101, 10):
        raise vol.Invalid("Expected 0 to 100 in steps of 10")
    return int(value)


PICTURE_SCHEMA = vol.Schema({
    vol.Inclusive("control", "setting"): vol.In(CONTROLS),
    vol.Inclusive("value", "setting"): picture_value,
})


async def camera_picture(api: Any, data: Any) -> dict[str, int]:
    try:
        result = await api.async_camera_picture(data.get("control"), data.get("value"))
    except C300XAgentApiError as err:
        raise HomeAssistantError(f"C300X picture controls: {err}") from err
    if not isinstance(result, dict) or result.get("ok") is not True or not all(
        type(result.get(key)) is int and 0 <= result[key] <= 100 for key in CONTROLS
    ):
        raise HomeAssistantError("C300X did not confirm the video-call picture settings")
    return {key: result[key] for key in CONTROLS}
