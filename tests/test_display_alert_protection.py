"""Explicit native protection is not confused with failed notification delivery."""

import asyncio
import logging

import pytest
from homeassistant.exceptions import HomeAssistantError
from test_notify import notify_context, send

from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
from custom_components.bticino_c300x.display_notifications import notification_payload


def test_protected_display_keeps_notice_and_reports_suppression(tmp_path, monkeypatch, caplog):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            api = entry.runtime_data.api.async_send_display_alert
            api.return_value = {"ok": True, "accepted": False, "suppressed": True, "reason": "display_protected"}
            with caplog.at_level(logging.INFO, logger="custom_components.bticino_c300x.display_alerts"):
                await send(hass, entry, title="Private title", message="Private message")
            api.assert_awaited_once()
            assert len(notification_payload(entry)) == 1
            assert "without popup, wake or sound" in caplog.text
            assert "No effects are queued" in caplog.text
            assert "Private title" not in caplog.text and "Private message" not in caplog.text
    asyncio.run(run())


@pytest.mark.parametrize("error", ["display_alerts_gui_unavailable", "Server disconnected", "display_alerts_delivery_failed"])
def test_missing_or_failed_gui_is_still_an_error(tmp_path, monkeypatch, error):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            api = entry.runtime_data.api.async_send_display_alert
            api.side_effect = C300XAgentApiConnectionError(error)
            with pytest.raises(HomeAssistantError, match="wake and sound are not confirmed"):
                await send(hass, entry)
            api.assert_awaited_once()
            assert len(notification_payload(entry)) == 1
    asyncio.run(run())
