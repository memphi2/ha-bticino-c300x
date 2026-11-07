"""Guard against old status readback re-enabling the GUI's mute state."""

from __future__ import annotations

import socket
import time

import pytest
from test_native_agent_ringer import (
    PATH,
    TOKEN,
    Lab,
    api_get,
    api_post,
    response,
    send_udp_event,
)
from test_native_agent_ringer import (
    lab as lab,
)
from test_native_agent_ringer import (
    ringer_binary as ringer_binary,
)


@pytest.mark.parametrize("queued_delay", [0.01, 0.08, 0.3])
def test_old_readback_cannot_reenable_gui_mute(lab: Lab, queued_delay: float) -> None:
    lab.device.muted = True
    feedback: list[bool] = []

    def firmware_receive_status() -> None:
        # AudioState::valueReceived enables RingtoneMute on a true mute value.
        if lab.device.muted:
            feedback.append(True)

    lab.device.ringer_read_hook = firmware_receive_status
    gui = lab.next()
    post = lab.post({"muted": False})
    command = response(gui)
    lab.next(command["id"], False)
    time.sleep(queued_delay)
    assert feedback == [], "The agent fed the old mute state back into the GUI"
    assert lab.device.frames == []
    lab.device.muted = False
    send_udp_event(lab.udp_port, "*#8**33*1##")
    assert response(post)["muted"] is False
    assert lab.device.frames == ["*#8**33##"]
    assert feedback == []


def test_get_cannot_read_hardware_during_gui_transition(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    result = response(lab.request(lab.api_port, PATH,
                                 headers={"Authorization": "Bearer " + TOKEN}), 409)
    assert result["error"] == "ringer_gui_busy"
    assert lab.device.frames == []
    lab.next(command["id"], True)
    result = response(lab.request(lab.api_port, PATH,
                                 headers={"Authorization": "Bearer " + TOKEN}), 409)
    assert result["error"] == "ringer_gui_busy"
    assert lab.device.frames == []
    lab.device.muted = True
    send_udp_event(lab.udp_port, "*#8**33*0##")
    assert response(post)["muted"] is True
    assert api_get(lab.api_port, PATH)["muted"] is True


@pytest.mark.parametrize("before_ack", [True, False])
def test_write_echo_is_not_hardware_confirmation(lab: Lab, before_ack: bool) -> None:
    lab.device.muted = True
    gui = lab.next()
    post = lab.post({"muted": False})
    command = response(gui)
    if not before_ack:
        lab.next(command["id"], False)
    send_udp_event(lab.udp_port, "*#8**#33*1##")
    time.sleep(0.1)
    if before_ack:
        lab.next(command["id"], False)
    assert lab.device.frames == []
    assert api_get(lab.api_port, "/api/v1/diagnostics")["ringer_command_pending"] is True
    assert api_get(lab.api_port, "/api/v1/events/recent")["events"] == []
    lab.device.muted = False
    send_udp_event(lab.udp_port, "*#8**33*1##")
    assert response(post)["muted"] is False


def test_missing_udp_gets_one_final_readback_without_retrying_gui(lab: Lab) -> None:
    lab.device.muted = True
    gui = lab.next()
    post = lab.post({"muted": False})
    command = response(gui)
    lab.next(command["id"], False)
    time.sleep(0.1)
    assert lab.device.frames == []
    lab.device.muted = False
    assert response(post)["muted"] is False
    assert lab.device.frames == ["*#8**33##"]
    assert api_get(lab.api_port, "/api/v1/diagnostics")["ringer_command_pending"] is False


@pytest.mark.parametrize("muted", [True, False])
def test_idempotent_command_is_verified_even_without_device_event(lab: Lab, muted: bool) -> None:
    lab.device.muted = muted
    gui = lab.next()
    post = lab.post({"muted": muted})
    command = response(gui)
    lab.next(command["id"], muted)
    assert lab.device.frames == []
    assert response(post)["muted"] is muted
    assert lab.device.frames == ["*#8**33##"]


def test_opposite_event_before_gui_ack_invalidates_matching_event(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    send_udp_event(lab.udp_port, "*#8**33*0##")
    send_udp_event(lab.udp_port, "*#8**33*1##")
    time.sleep(0.1)
    lab.next(command["id"], True)
    assert lab.device.frames == []
    lab.device.muted = True
    send_udp_event(lab.udp_port, "*#8**33*0##")
    assert response(post)["muted"] is True
    assert lab.device.frames == ["*#8**33##"]


def test_matching_event_before_request_is_not_reused(lab: Lab) -> None:
    send_udp_event(lab.udp_port, "*#8**33*1##")
    time.sleep(0.1)
    lab.device.muted = True
    gui = lab.next()
    post = lab.post({"muted": False})
    command = response(gui)
    lab.next(command["id"], False)
    assert lab.device.frames == []
    lab.device.muted = False
    send_udp_event(lab.udp_port, "*#8**33*1##")
    assert response(post)["muted"] is False


def test_duplicate_stale_events_do_not_create_a_readback_storm(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    lab.next(command["id"], True)
    for _ in range(32):
        send_udp_event(lab.udp_port, "*#8**33*0##")
    deadline = time.monotonic() + 2
    while not lab.device.frames and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    assert lab.device.frames == ["*#8**33##"]
    assert api_get(lab.api_port, "/api/v1/diagnostics")["ringer_command_pending"] is True
    assert api_get(lab.api_port, "/api/v1/events/recent")["events"] == []
    lab.device.muted = True
    assert response(post)["muted"] is True
    assert lab.device.frames == ["*#8**33##", "*#8**33##"]


def test_client_disconnect_cancels_final_readback(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    lab.next(command["id"], True)
    assert post.sock is not None
    post.sock.shutdown(socket.SHUT_RDWR)
    post.close()
    api_get(lab.ui_port, "/ui/events/status", authorized=False)
    time.sleep(5.1)
    assert api_get(lab.api_port, "/api/v1/diagnostics")["ringer_command_pending"] is False
    assert lab.device.frames == []


def test_volume_write_cannot_overtake_pending_gui_command(lab: Lab) -> None:
    gui = lab.next()
    post = lab.post({"muted": True})
    command = response(gui)
    assert api_post(lab.api_port, PATH, {"volume": 4}, expected_status=409)["error"] == "ringer_gui_busy"
    assert lab.device.frames == []
    lab.device.muted = True
    lab.next(command["id"], True)
    send_udp_event(lab.udp_port, "*#8**33*0##")
    assert response(post)["muted"] is True
    assert api_post(lab.api_port, PATH, {"volume": 4})["volume"] == 4
