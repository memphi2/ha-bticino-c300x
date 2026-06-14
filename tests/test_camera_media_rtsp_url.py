from __future__ import annotations

from custom_components.bticino_c300x.camera_media.rtsp_url import (
    agent_host_for_socket,
    agent_host_for_url,
    build_rtsp_url,
    normalize_rtsp_path,
)


def test_agent_host_for_socket_accepts_bracketed_ipv6_zone() -> None:
    assert agent_host_for_socket("[fe80::1%25wlan0]") == "fe80::1%wlan0"


def test_agent_host_for_url_brackets_ipv6_zone() -> None:
    assert agent_host_for_url("fe80::1%wlan0") == "[fe80::1%25wlan0]"


def test_normalize_rtsp_path_adds_leading_slash() -> None:
    assert normalize_rtsp_path("doorbell", default_path="/doorbell-video") == "/doorbell"


def test_build_rtsp_url_formats_ipv4_host() -> None:
    assert (
        build_rtsp_url(
            host="192.0.2.10",
            port=6554,
            path="doorbell-video",
            default_path="/doorbell-video",
        )
        == "rtsp://192.0.2.10:6554/doorbell-video"
    )


def test_build_rtsp_url_can_preserve_absolute_url_for_camera_status() -> None:
    assert (
        build_rtsp_url(
            host="192.0.2.10",
            port=6554,
            path="rtsp://agent.example/doorbell",
            default_path="/doorbell-video",
            allow_absolute_url=True,
        )
        == "rtsp://agent.example/doorbell"
    )


def test_build_rtsp_url_keeps_legacy_path_normalization_by_default() -> None:
    assert (
        build_rtsp_url(
            host="192.0.2.10",
            port=6554,
            path="rtsp://agent.example/doorbell",
            default_path="/doorbell-video",
        )
        == "rtsp://192.0.2.10:6554/rtsp://agent.example/doorbell"
    )
