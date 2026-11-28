"""A refused hang-up sends nothing and leaves the live call's media open."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from test_api import _CALLS, _PENDING_RING, _QueuedSession
from test_camera import (
    C300XDoorbellCamera,
    _FakeEntry,
    _FakeWebRTCProvider,
    _stub_rtsp_ready,
    camera_ha_boundary,  # noqa: F401
    camera_module,
)

from custom_components.bticino_c300x import _api_media
from custom_components.bticino_c300x.api import C300XAgentApi
from custom_components.bticino_c300x.use_cases.ring_call import RingCallUseCase

# What the agent answers to a hang-up it refuses, had one been sent.
_NOT_CURRENT = (409, '{"ok": false, "error": "call_not_current", "current_call_id": "0badc0de-2"}')


async def _card_in_unit_21s_call(monkeypatch: pytest.MonkeyPatch, calls: list[tuple[int, str]]) -> Any:
    """The card shows the ring of unit 21; the agent answers ``calls`` in turn."""

    entry = _FakeEntry(data={"agent_host": "192.0.2.1", "video_enabled": True})
    entry.runtime_data.capabilities = {
        "doorbell_video": {"supported": True}, "doorbell_call": {"supported": True},
    }
    camera = C300XDoorbellCamera(entry)
    camera.hass = SimpleNamespace(async_create_task=asyncio.create_task)
    _stub_rtsp_ready(camera)
    provider = _FakeWebRTCProvider()
    monkeypatch.setattr(camera_module, "_async_get_supported_webrtc_provider", AsyncMock(return_value=provider))
    messages: list[Any] = []
    await camera.async_handle_async_webrtc_offer("v=0", "card", messages.append)
    assert "card" in camera._webrtc_sessions.active
    entry.runtime_data.resources.prepare_doorbell_video_stop = camera.async_prepare_doorbell_video_stop
    media = entry.runtime_data.api
    session = _QueuedSession(calls)
    agent = C300XAgentApi(session, "http://agent.local:8080", "agent-token")  # type: ignore[arg-type]
    # The media status stays the camera's; calls and call actions go to the agent.
    agent.async_doorbell_video_status = media.async_doorbell_video_status  # type: ignore[method-assign]
    entry.runtime_data.api = agent
    return SimpleNamespace(entry=entry, camera=camera, provider=provider, messages=messages,
                           session=session, media=media)


def _types(messages: list[Any]) -> list[Any]:
    return [message.get("type") for message in messages]


@pytest.mark.parametrize(("call_id", "unit", "calls"), [
    # A per-unit automation hangs up unit 20 while the card talks to unit 21.
    (None, "20", [(200, _CALLS), _NOT_CURRENT]),
    (None, "20", [(200, _PENDING_RING), (200, _CALLS), _NOT_CURRENT]),
    # A call id of an earlier ring.
    ("0badc0de-1", None, [(200, _CALLS), _NOT_CURRENT]),
    ("0badc0de-1", "21", [(200, _CALLS), _NOT_CURRENT]),
])
def test_a_refused_hangup_closes_nothing_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, call_id: str | None, unit: str | None, calls: list[tuple[int, str]],
) -> None:
    monkeypatch.setattr(_api_media, "_UNIT_PENDING_POLL_SECONDS", 0)

    async def run() -> None:
        card = await _card_in_unit_21s_call(monkeypatch, calls)
        try:
            with pytest.raises(ServiceValidationError) as raised:
                await RingCallUseCase(card.entry).hangup(call_id, unit)
            assert raised.value.translation_key == "call_not_current"
            assert [request["args"][0] for request in card.session.requests] == ["GET"] * (len(calls) - 1)
            assert "card" in card.camera._webrtc_sessions.active
            assert "closed" not in _types(card.messages)
            assert card.provider.closed == []
            assert not card.entry.runtime_data.resources.media_stop_counts
        finally:
            card.entry.runtime_data.api = card.media
            await card.camera.async_will_remove_from_hass()

    asyncio.run(run())


def _held_call(state: str, answered_by: str | None) -> str:
    """Unit 21's call as the agent lists it while it holds no leg of it."""

    answered = f'"{answered_by}"' if answered_by else "null"
    return (
        '{"ok": true, "boot_id": "0badc0de", "current_call_id": "0badc0de-2", "calls": ['
        f'{{"call_id": "0badc0de-2", "kind": "ring", "state": "{state}", "unit": "21",'
        f' "attribution": "caller_frame", "answered_by": {answered}, "end_reason": null,'
        ' "can_hangup": false}]}'
    )


@pytest.mark.parametrize(("call_id", "unit"), [(None, None), (None, "21"), ("0badc0de-2", None)])
@pytest.mark.parametrize(("calls", "key"), [
    # Only the bus rang (smartphone forwarding): the agent has no ring leg.
    (_held_call("ringing", None), "ring_call_not_active"),
    # The display, the app or the answering machine answered: the station holds it.
    (_held_call("answered", "station"), "station_busy"),
    (_held_call("answered", "answering_machine"), "station_busy"),
])
def test_the_hangup_of_a_call_the_agent_holds_no_leg_of_closes_nothing_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, call_id: str | None, unit: str | None, calls: str, key: str,
) -> None:
    async def run() -> None:
        card = await _card_in_unit_21s_call(monkeypatch, [(200, calls)])
        try:
            with pytest.raises(HomeAssistantError) as raised:
                await RingCallUseCase(card.entry).hangup(call_id, unit)
            assert raised.value.translation_key == key
            assert [request["args"][0] for request in card.session.requests] == ["GET"]
            assert "card" in card.camera._webrtc_sessions.active
            assert "closed" not in _types(card.messages)
            assert card.provider.closed == []
            assert not card.entry.runtime_data.resources.media_stop_counts
        finally:
            card.entry.runtime_data.api = card.media
            await card.camera.async_will_remove_from_hass()

    asyncio.run(run())


def test_the_agents_ring_call_not_active_answer_is_its_translated_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # The agent's own refusal, here of an answer: only the station rings.
    async def run() -> None:
        card = await _card_in_unit_21s_call(monkeypatch, [
            (200, _CALLS), (409, '{"ok": false, "error": "ring_call_not_active", "ring_call_active": false}'),
        ])
        card.entry.runtime_data.api.async_doorbell_video_status = AsyncMock(return_value={})  # type: ignore[method-assign]
        try:
            with pytest.raises(HomeAssistantError) as raised:
                await RingCallUseCase(card.entry).answer(None, "21")
            assert raised.value.translation_key == "ring_call_not_active"
        finally:
            card.entry.runtime_data.api = card.media
            await card.camera.async_will_remove_from_hass()

    asyncio.run(run())


def test_the_hangup_of_the_live_call_closes_its_media_then_sends_it(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        card = await _card_in_unit_21s_call(monkeypatch, [(200, _CALLS), (200, '{"ok": true}')])
        sent_after_close: list[bool] = []
        request = card.session.request

        def record(*args: Any, **kwargs: Any) -> Any:
            if args[0] == "POST":
                sent_after_close.append("card" not in card.camera._webrtc_sessions.active)
            return request(*args, **kwargs)

        card.session.request = record
        try:
            await RingCallUseCase(card.entry).hangup(None, "21")
            assert card.session.requests[-1]["args"] == (
                "POST", "http://agent.local:8080/api/v1/calls/0badc0de-2/actions/hangup",
            )
            assert sent_after_close == [True]
            assert "closed" in _types(card.messages)
        finally:
            card.entry.runtime_data.api = card.media
            await card.camera.async_will_remove_from_hass()

    asyncio.run(run())
