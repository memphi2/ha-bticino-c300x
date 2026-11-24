import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x._api_normalize import _http_error_text
from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
from custom_components.bticino_c300x.camera_picture import (
    PICTURE_SCHEMA,
    camera_picture,
)
from custom_components.bticino_c300x.schema_compat import vol


@pytest.mark.parametrize("fields", [
    {"control": "brightness"}, {"value": 10}, {"control": "volume", "value": 10},
    {"control": "brightness", "value": True}, {"control": "contrast", "value": 5},
])
def test_picture_rejects_partial_or_invalid_settings(fields):
    with pytest.raises(vol.Invalid):
        PICTURE_SCHEMA(fields)


@pytest.mark.parametrize("fields", [{}, {"control": "saturation", "value": 0}])
def test_picture_reports_gui_values_only(fields):
    api = AsyncMock()
    expected = {"brightness": 30, "contrast": 20, "saturation": 0}
    api.async_camera_picture.return_value = {"ok": True, **expected}
    assert asyncio.run(camera_picture(api, PICTURE_SCHEMA(fields))) == expected
    api.async_camera_picture.assert_awaited_once_with(fields.get("control"), fields.get("value"))
    api.async_camera_picture.return_value = {"ok": True, **expected, "brightness": False}
    with pytest.raises(HomeAssistantError):
        asyncio.run(camera_picture(api, fields))


@pytest.mark.parametrize("code", ["picture_not_applied", "media_busy", "picture_controls_unavailable"])
def test_picture_errors_keep_the_agent_code_the_card_reads(code):
    # The card tells the errors apart by this code in the service error message.
    api = AsyncMock()
    api.async_camera_picture.side_effect = C300XAgentApiConnectionError(
        _http_error_text(409, f'{{"error":"{code}"}}'))
    with pytest.raises(HomeAssistantError, match=rf"\b{code}\b"):
        asyncio.run(camera_picture(api, {"control": "brightness", "value": 60}))
