from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.camera_media.webrtc_session import (
    NativeWebRTCSession,
    NativeWebRTCSessionRegistry,
    async_flush_pending_webrtc_candidates,
    async_wait_for_ice_gathering,
    candidate_is_link_local,
    filter_link_local_sdp_candidates,
    patch_aioice_turn_transport_sendto,
    prefer_webrtc_codecs,
    rtc_candidate_from_message,
    webrtc_server_configuration,
)


def test_session_registry_reports_media_and_owner_groups() -> None:
    closed_peer = SimpleNamespace(
        connectionState="closed",
        iceConnectionState="closed",
        signalingState="closed",
    )
    sessions: dict[str, NativeWebRTCSession] = {
        "door": NativeWebRTCSession(SimpleNamespace()),
        "home": NativeWebRTCSession(SimpleNamespace(), owner="home_call"),
        "ring": NativeWebRTCSession(SimpleNamespace()),
        "closed": NativeWebRTCSession(closed_peer),
    }
    sessions["door"].player = object()
    sessions["closed"].player = object()
    sessions["ring"].ring_call = True
    registry = NativeWebRTCSessionRegistry(sessions)

    assert registry.active_media_sessions() == 1
    assert registry.has_sessions() is True
    assert registry.session_ids_by_owner("home_call") == ["home"]
    assert registry.session_ids_for_ring_call() == ["ring"]
    assert registry.session_ids() == ["door", "home", "ring", "closed"]


def test_session_registry_closes_resources_and_notifies_client() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _Player:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    async def _never() -> None:
        await asyncio.Event().wait()

    async def _run() -> None:
        peer = _Peer()
        player = _Player()
        messages: list[Any] = []
        session = NativeWebRTCSession(peer, send_message=messages.append)
        session.player = player
        session.renew_task = asyncio.create_task(_never())
        session.ice_flush_task = asyncio.create_task(_never())
        session.talkback_task = asyncio.create_task(_never())
        tasks = [session.renew_task, session.ice_flush_task, session.talkback_task]
        registry = NativeWebRTCSessionRegistry({"session-1": session})

        closed_session = await registry.async_close_session_resources(
            "session-1",
            notify_client=True,
            reason="media_closed",
        )
        await asyncio.sleep(0)

        assert closed_session is session
        assert registry.has_sessions() is False
        assert player.stopped is True
        assert peer.closed is True
        assert messages == [{"type": "closed", "reason": "media_closed"}]
        assert session.renew_task is None
        assert session.ice_flush_task is None
        assert session.talkback_task is None
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(_run())


def test_session_registry_cancels_pending_ice_checks_before_peer_close() -> None:
    close_order: list[str] = []

    class _Peer:
        def __init__(self, task: asyncio.Task[None]) -> None:
            self.closed = False
            self._RTCPeerConnection__iceTransports = (  # noqa: SLF001
                SimpleNamespace(
                    _connection=SimpleNamespace(
                        _check_list=(SimpleNamespace(task=task),)
                    )
                ),
            )

        async def close(self) -> None:
            close_order.append("peer_close")
            self.closed = True

    async def _pending_ice_check() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            close_order.append("ice_cancelled")

    async def _run() -> None:
        ice_task = asyncio.create_task(_pending_ice_check())
        await asyncio.sleep(0)
        peer = _Peer(ice_task)
        session = NativeWebRTCSession(peer)
        registry = NativeWebRTCSessionRegistry({"session-1": session})

        await registry.async_close_session_resources("session-1")

        assert ice_task.cancelled() is True
        assert peer.closed is True
        assert close_order == ["ice_cancelled", "peer_close"]

    asyncio.run(_run())


def test_session_registry_close_missing_session_is_noop() -> None:
    registry = NativeWebRTCSessionRegistry({})

    assert asyncio.run(registry.async_close_session_resources("missing")) is None


def test_rtc_candidate_from_message_normalizes_candidate_prefix() -> None:
    aiortc_modules = SimpleNamespace(
        candidate_from_sdp=lambda sdp: SimpleNamespace(sdp=sdp)
    )

    candidate = rtc_candidate_from_message(
        aiortc_modules,
        SimpleNamespace(
            candidate="candidate:1 1 udp 2122260223 192.0.2.10 5000 typ host",
            sdpMid="0",
            sdpMLineIndex=0,
        ),
    )

    assert candidate.sdp == "1 1 udp 2122260223 192.0.2.10 5000 typ host"
    assert candidate.sdpMid == "0"
    assert candidate.sdpMLineIndex == 0


def test_rtc_candidate_from_message_accepts_end_of_candidates() -> None:
    assert rtc_candidate_from_message(SimpleNamespace(), SimpleNamespace()) is None


def test_flush_pending_candidates_waits_for_remote_description() -> None:
    class _Peer:
        remoteDescription = None

        def __init__(self) -> None:
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:  # noqa: N802
            self.candidates.append(candidate)

    peer = _Peer()
    session = NativeWebRTCSession(peer)
    session.pending_ice_candidates.append(SimpleNamespace(sdp="candidate-1"))

    asyncio.run(async_flush_pending_webrtc_candidates(session))

    assert peer.candidates == []
    assert len(session.pending_ice_candidates) == 1


def test_flush_pending_candidates_replays_after_remote_description() -> None:
    class _Peer:
        remoteDescription = object()

        def __init__(self) -> None:
            self.candidates: list[Any] = []

        async def addIceCandidate(self, candidate: Any) -> None:  # noqa: N802
            self.candidates.append(candidate)

    peer = _Peer()
    session = NativeWebRTCSession(peer)
    session.pending_ice_candidates.append(SimpleNamespace(sdp="candidate-1"))

    asyncio.run(async_flush_pending_webrtc_candidates(session))

    assert len(peer.candidates) == 1
    assert peer.candidates[0].sdp == "candidate-1"
    assert session.pending_ice_candidates == []


def test_webrtc_server_configuration_mirrors_ha_ice_servers() -> None:
    class _AiortcIceServer:
        def __init__(
            self,
            urls: str | list[str],
            username: str | None = None,
            credential: str | None = None,
        ) -> None:
            self.urls = urls
            self.username = username
            self.credential = credential

    class _AiortcConfiguration:
        def __init__(self, iceServers: list[_AiortcIceServer]) -> None:
            self.iceServers = iceServers

    config = webrtc_server_configuration(
        SimpleNamespace(
            RTCConfiguration=_AiortcConfiguration,
            RTCIceServer=_AiortcIceServer,
        ),
        lambda: SimpleNamespace(
            configuration=SimpleNamespace(
                ice_servers=[
                    SimpleNamespace(
                        urls=["turn:relay.example:3478"],
                        username="cloud-user",
                        credential="cloud-credential",
                    ),
                    SimpleNamespace(urls=["stun:stun.home-assistant.io:3478"]),
                ]
            )
        ),
    )

    assert [server.urls for server in config.iceServers] == [
        ["turn:relay.example:3478"],
        ["stun:stun.home-assistant.io:3478"],
    ]
    assert config.iceServers[0].username == "cloud-user"
    assert config.iceServers[0].credential == "cloud-credential"


def test_aioice_turn_sendto_guard_consumes_transaction_failures() -> None:
    handled: list[dict[str, Any]] = []

    class TransactionFailed(Exception):
        pass

    TransactionFailed.__module__ = "aioice.stun"

    class _InnerProtocol:
        async def send_data(self, _data: bytes, _addr: tuple[str, int]) -> None:
            raise TransactionFailed("401")

    class _TurnTransport:
        def __init__(self) -> None:
            self.__inner_protocol = _InnerProtocol()

        def sendto(self, _data: bytes, _addr: tuple[str, int]) -> None:
            raise AssertionError("original sendto should be guarded")

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: handled.append(context))
        patch_aioice_turn_transport_sendto(
            SimpleNamespace(TurnTransport=_TurnTransport)
        )

        _TurnTransport().sendto(b"packet", ("192.0.2.10", 3478))
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert handled == []


def test_aioice_turn_sendto_guard_reports_unexpected_failures() -> None:
    handled: list[dict[str, Any]] = []

    class _InnerProtocol:
        async def send_data(self, _data: bytes, _addr: tuple[str, int]) -> None:
            raise RuntimeError("unexpected")

    class _TurnTransport:
        def __init__(self) -> None:
            self.__inner_protocol = _InnerProtocol()

        def sendto(self, _data: bytes, _addr: tuple[str, int]) -> None:
            raise AssertionError("original sendto should be guarded")

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: handled.append(context))
        patch_aioice_turn_transport_sendto(
            SimpleNamespace(TurnTransport=_TurnTransport)
        )

        _TurnTransport().sendto(b"packet", ("192.0.2.10", 3478))
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert len(handled) == 1
    assert handled[0]["message"] == "Unhandled aioice TURN send task exception"
    assert isinstance(handled[0]["exception"], RuntimeError)


def test_webrtc_server_configuration_ignores_bad_or_empty_ice_servers() -> None:
    class _AiortcIceServer:
        def __init__(
            self,
            urls: str | list[str],
            username: str | None = None,
            credential: str | None = None,
        ) -> None:
            self.urls = urls
            self.username = username
            self.credential = credential

    class _AiortcConfiguration:
        def __init__(self, iceServers: list[_AiortcIceServer]) -> None:
            self.iceServers = iceServers

    aiortc_modules = SimpleNamespace(
        RTCConfiguration=_AiortcConfiguration,
        RTCIceServer=_AiortcIceServer,
    )

    empty_config = webrtc_server_configuration(
        aiortc_modules,
        lambda: SimpleNamespace(
            configuration=SimpleNamespace(ice_servers=[SimpleNamespace(urls=[])])
        ),
    )

    assert empty_config.iceServers == []
    assert webrtc_server_configuration(aiortc_modules, None).iceServers == []

    def _broken_config() -> None:
        raise RuntimeError("relay unavailable")

    assert webrtc_server_configuration(aiortc_modules, _broken_config).iceServers == []


def test_wait_for_ice_gathering_completes_after_state_change() -> None:
    class _Peer:
        def __init__(self) -> None:
            self.iceGatheringState = "gathering"
            self.callback = None

        def on(self, event_name: str):  # noqa: ANN201
            assert event_name == "icegatheringstatechange"

            def _register(callback):  # noqa: ANN001,ANN202
                self.callback = callback
                return callback

            return _register

    async def _run() -> None:
        peer = _Peer()
        task = asyncio.create_task(async_wait_for_ice_gathering(peer, wait_seconds=1.0))
        await asyncio.sleep(0)
        peer.iceGatheringState = "complete"
        assert peer.callback is not None
        peer.callback()
        await task

    asyncio.run(_run())


def test_wait_for_ice_gathering_returns_immediately_when_complete() -> None:
    peer = SimpleNamespace(iceGatheringState="complete")

    asyncio.run(async_wait_for_ice_gathering(peer, wait_seconds=0.01))


def test_prefer_webrtc_codecs_prefers_h264_and_browser_audio() -> None:
    class _Codec:
        def __init__(self, mime_type: str) -> None:
            self.mimeType = mime_type

    class _Sender:
        @staticmethod
        def getCapabilities(kind: str) -> SimpleNamespace:  # noqa: N802
            if kind == "video":
                return SimpleNamespace(
                    codecs=[_Codec("video/VP8"), _Codec("video/H264")]
                )
            return SimpleNamespace(
                codecs=[
                    _Codec("audio/G722"),
                    _Codec("audio/opus"),
                    _Codec("audio/PCMU"),
                ]
            )

    class _Transceiver:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.preferences: list[str] = []

        def setCodecPreferences(self, codecs: list[_Codec]) -> None:  # noqa: N802
            self.preferences = [codec.mimeType for codec in codecs]

    video = _Transceiver("video")
    audio = _Transceiver("audio")
    peer = SimpleNamespace(getTransceivers=lambda: [video, audio])

    prefer_webrtc_codecs(peer, SimpleNamespace(RTCRtpSender=_Sender))

    assert video.preferences == ["video/H264", "video/VP8"]
    assert audio.preferences == ["audio/opus", "audio/PCMU", "audio/G722"]


def test_filter_link_local_candidates_when_relay_exists() -> None:
    sdp = (
        "v=0\r\n"
        "a=candidate:1 1 udp 2130706431 fe80::1 5000 typ host\r\n"
        "a=candidate:2 1 udp 2130706431 ha-local.local 5001 typ host\r\n"
        "a=candidate:3 1 udp 1677729535 192.0.2.10 5002 typ relay\r\n"
        "a=end-of-candidates\r\n"
    )

    filtered = filter_link_local_sdp_candidates(sdp)

    assert "fe80::1" not in filtered
    assert "ha-local.local" not in filtered
    assert "192.0.2.10" in filtered
    assert filtered.endswith("\r\n")


def test_keep_link_local_candidates_when_no_alternative_exists() -> None:
    sdp = "v=0\r\na=candidate:1 1 udp 2130706431 fe80::1 5000 typ host\r\n"

    assert filter_link_local_sdp_candidates(sdp) == sdp


def test_candidate_link_local_parser_handles_short_and_invalid_candidates() -> None:
    assert candidate_is_link_local("a=candidate:too-short") is False
    assert (
        candidate_is_link_local(
            "a=candidate:1 1 udp 2130706431 not-an-ip 5000 typ host"
        )
        is False
    )
