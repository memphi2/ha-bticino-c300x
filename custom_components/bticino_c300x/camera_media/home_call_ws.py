"""Home Call WebRTC websocket registration for C300X media."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol

from ..const import MAX_HOME_CALL_DURATION_SECONDS

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_WsCommand = Callable[..., Any]
_WsCommandDecorator = Callable[[_WsCommand], _WsCommand]
_WsCommandFactory = Callable[[dict[Any, Any]], _WsCommandDecorator]


def parse_home_call_candidate(value: Any) -> SimpleNamespace:
    """Parse a frontend ICE candidate object for Home Call WebRTC."""

    if not isinstance(value, dict):
        raise vol.Invalid("candidate must be an object")
    return SimpleNamespace(
        candidate=str(value.get("candidate") or ""),
        sdpMid=value.get("sdpMid"),
        sdpMLineIndex=value.get("sdpMLineIndex"),
    )


def async_register_home_call_ws(hass: HomeAssistant, camera_type: type[Any]) -> None:
    """Register Home Call audio WebRTC websocket commands."""

    from homeassistant.components import camera as camera_component
    from homeassistant.components import websocket_api
    from homeassistant.components.camera.helper import get_camera_from_entity_id
    from homeassistant.components.camera.webrtc import WebRTCSession
    from homeassistant.core import callback
    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers import config_validation as cv
    from homeassistant.util.ulid import ulid

    async_register_command = cast(
        Callable[[Any, _WsCommand], None],
        websocket_api.async_register_command,
    )
    async_response = cast(
        _WsCommandDecorator,
        websocket_api.async_response,  # type: ignore[attr-defined]
    )
    event_message = cast(
        Callable[[Any, Any], dict[str, Any]],
        websocket_api.event_message,  # type: ignore[attr-defined]
    )
    result_message = cast(
        Callable[[Any], dict[str, Any]],
        websocket_api.result_message,  # type: ignore[attr-defined]
    )
    websocket_command = cast(
        _WsCommandFactory,
        websocket_api.websocket_command,  # type: ignore[attr-defined]
    )
    WebRTCError = cast(
        type[Any],
        camera_component.WebRTCError,  # type: ignore[attr-defined]
    )

    def _home_call_camera(entity_id: str) -> Any | None:
        camera = get_camera_from_entity_id(hass, entity_id)
        return camera if isinstance(camera, camera_type) else None

    @websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/get_client_config",
            vol.Required("entity_id"): cv.entity_id,
        }
    )
    @async_response
    async def ws_home_call_get_client_config(
        _hass: HomeAssistant,
        connection: Any,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return
        connection.send_result(
            msg["id"],
            camera.async_get_webrtc_client_configuration().to_frontend_dict(),
        )

    @websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/offer",
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("offer"): str,
            vol.Optional("duration_seconds"): vol.All(
                vol.Coerce(int),
                vol.Range(min=0, max=MAX_HOME_CALL_DURATION_SECONDS),
            ),
        }
    )
    @async_response
    async def ws_home_call_webrtc_offer(
        _hass: HomeAssistant,
        connection: Any,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return

        session_id = ulid()
        connection.subscriptions[msg["id"]] = partial(
            camera.close_webrtc_session,
            session_id,
        )
        connection.send_message(result_message(msg["id"]))

        @callback
        def send_message(message: Any) -> None:
            connection.send_message(
                event_message(
                    msg["id"],
                    message.as_dict() if hasattr(message, "as_dict") else message,
                )
            )

        send_message(WebRTCSession(session_id))
        try:
            await camera.async_handle_home_call_webrtc_offer(
                msg["offer"],
                session_id,
                send_message,
                duration_seconds=msg.get("duration_seconds"),
            )
        except HomeAssistantError as err:
            send_message(WebRTCError("home_call_webrtc_offer_failed", str(err)))

    @websocket_command(
        {
            vol.Required("type"): "bticino_c300x/home_call/webrtc/candidate",
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("session_id"): str,
            vol.Required("candidate"): parse_home_call_candidate,
        }
    )
    @async_response
    async def ws_home_call_candidate(
        _hass: HomeAssistant,
        connection: Any,
        msg: dict[str, Any],
    ) -> None:
        camera = _home_call_camera(msg["entity_id"])
        if camera is None:
            connection.send_error(
                msg["id"],
                "home_call_webrtc_not_found",
                "C300X doorbell camera entity not found",
            )
            return
        await camera.async_on_webrtc_candidate(msg["session_id"], msg["candidate"])
        connection.send_message(result_message(msg["id"]))

    async_register_command(hass, ws_home_call_get_client_config)
    async_register_command(hass, ws_home_call_webrtc_offer)
    async_register_command(hass, ws_home_call_candidate)
