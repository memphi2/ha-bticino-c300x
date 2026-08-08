from __future__ import annotations

from collections.abc import Mapping

from custom_components.bticino_c300x.agent_contracts import (
    AgentDiagnosticsStatus,
    AuthConfigStatus,
    CapabilityPayload,
    DoorbellVideoStatus,
    FirewallStatus,
    ForwardingStatus,
    HomeCallStatus,
    RingCallStatus,
    SelfTestStatus,
)
from custom_components.bticino_c300x.api import (
    normalize_agent_diagnostics,
    normalize_auth_config_status,
    normalize_doorbell_call,
    normalize_doorbell_video,
    normalize_firewall_status,
    normalize_home_call,
    normalize_self_test,
    normalize_smartphone_forwarding,
)


def test_agent_contracts_keep_dict_style_access() -> None:
    status = normalize_doorbell_video(
        {
            "available": True,
            "stream_path": "/doorbell-video",
            "bridge": {"media_owner": "ring"},
        }
    )

    assert isinstance(status, DoorbellVideoStatus)
    assert isinstance(status, Mapping)
    assert status.stream_path == "/doorbell-video"
    assert status["stream_path"] == "/doorbell-video"
    assert status.get("missing", "fallback") == "fallback"
    assert status.to_dict()["raw"]["available"] is True
    assert status != object()


def test_agent_contracts_compare_equal_to_normalized_dicts() -> None:
    payload = {
        "available": True,
        "running": True,
        "active": False,
        "answered": False,
        "rtp_proxy": True,
    }
    status = normalize_home_call(payload)

    assert status == {
        "raw": payload,
        "available": True,
        "running": True,
        "active": False,
        "answered": False,
        "rtp_proxy": True,
        "target_audio_port": None,
        "rtp_packets": 0,
        "rtcp_packets": 0,
        "max_duration_seconds": None,
        "last_error": None,
    }


def test_agent_status_normalizers_return_typed_contracts() -> None:
    assert isinstance(
        CapabilityPayload(
            raw={"api_version": "1"},
            version="1.2.0",
            agent={"version": "1.2.0"},
            implementation="native-c",
            api_version="1",
            device_id="device",
            model="C300X",
            firmware="1.7.19",
            capabilities={"doorbell_call": True},
        ),
        CapabilityPayload,
    )
    assert isinstance(
        normalize_doorbell_call({"supported": True}),
        RingCallStatus,
    )
    assert isinstance(
        normalize_home_call({"available": True}),
        HomeCallStatus,
    )
    assert isinstance(
        normalize_agent_diagnostics({"agent_write_count": 1}),
        AgentDiagnosticsStatus,
    )
    assert isinstance(
        normalize_auth_config_status({"noAuth": False}),
        AuthConfigStatus,
    )
    assert isinstance(
        normalize_firewall_status({"state": "patched"}),
        FirewallStatus,
    )
    assert isinstance(
        normalize_self_test({"ok": True, "checks": {}}),
        SelfTestStatus,
    )
    assert isinstance(
        normalize_smartphone_forwarding({"mode": "homeassistant"}),
        ForwardingStatus,
    )


def test_forwarding_contract_keeps_raw_reply_and_mapping_access() -> None:
    status = normalize_smartphone_forwarding({"mode": "homeassistant", "raw": "reply"})

    assert isinstance(status, ForwardingStatus)
    assert status.mode == 1
    assert status.state == "homeassistant"
    assert status.raw == "reply"
    assert status["state"] == "homeassistant"
    assert status == {"mode": 1, "state": "homeassistant", "raw": "reply"}


def test_agent_json_status_contracts_preserve_mapping_fields() -> None:
    """Agent JSON normalizers return typed objects without losing dict semantics."""

    video_status = normalize_doorbell_video(
        {
            "available": True,
            "window_available": True,
            "stream_path": "/doorbell-video",
            "audio_stream_path": "/doorbell",
            "recorder_stream_path": "/doorbell-recorder",
            "bridge": {
                "media_owner": "ring",
                "external_media_active": False,
                "clients": "1",
                "max_clients": "2",
                "ring_preview_sharing": True,
            },
        }
    )
    ring_status = normalize_doorbell_call(
        {
            "supported": True,
            "active": True,
            "early_media_active": True,
            "audio_active": False,
            "answer_requested": False,
            "answered": False,
            "hangup_requested": True,
            "can_answer": True,
            "can_hangup": True,
            "media_owner": "ring",
            "ring_receiver_running": True,
            "ring_registered": True,
            "capture_supported": True,
            "open_fds": "2",
            "active_threads": "1",
        }
    )
    assert ring_status.hangup_requested is True
    home_status = normalize_home_call(
        {
            "available": True,
            "running": True,
            "active": True,
            "answered": True,
            "rtp_proxy": True,
            "target_audio_port": "40004",
            "rtp_packets": "12",
            "rtcp_packets": "3",
            "max_duration_seconds": "120",
        }
    )

    assert video_status.media_owner == "ring"
    assert video_status["bridge"]["clients"] == "1"
    assert video_status.to_dict()["recorder_stream_path"] == "/doorbell-recorder"
    assert ring_status.can_answer is True
    assert ring_status["open_fds"] == 2
    assert ring_status.to_dict()["capture_supported"] is True
    assert home_status.target_audio_port == 40004
    assert home_status["rtp_packets"] == 12
    assert home_status.to_dict()["answered"] is True


def test_self_test_contract_normalizes_nested_checks() -> None:
    status = normalize_self_test(
        {
            "api_version": "1.1",
            "agent_version": "1.2.0",
            "firmware_family": "1.7.x",
            "ok": False,
            "checks": {
                "firewall": {
                    "ok": False,
                    "reason": "ipv4_media_ports_missing",
                    "ipv4_state": "original",
                },
                "rtsp": {"ok": True, "reason": "rtsp_ready", "clients": 0},
            },
        }
    )

    assert status.ok is False
    assert status.api_version == "1.1"
    assert status.checks["firewall"].ok is False
    assert status.checks["firewall"].reason == "ipv4_media_ports_missing"
    assert status.checks["firewall"].details == {"ipv4_state": "original"}
    assert status["checks"]["rtsp"]["details"]["clients"] == 0


def test_self_test_contract_handles_bool_strings_and_ignores_bad_checks() -> None:
    status = normalize_self_test(
        {
            "api_version": 1.1,
            "agent_version": "",
            "firmware_family": None,
            "ok": "yes",
            "checks": {
                "startup": {
                    "ok": "0",
                    "reason": 42,
                    "agent_init_script_present": False,
                },
                "capabilities": {"ok": None, "reason": None},
                "skip_non_object": [],
                7: {"ok": True},
                "talkback_rtp": {"ok": "enabled", "reason": ""},
                "firewall": {"ok": "definitely"},
            },
        }
    )

    assert status.ok is True
    assert status.api_version == "1.1"
    assert status.agent_version is None
    assert status.firmware_family is None
    assert set(status.checks) == {
        "startup",
        "capabilities",
        "talkback_rtp",
        "firewall",
    }
    assert status.checks["startup"].ok is False
    assert status.checks["startup"].reason == "42"
    assert status.checks["startup"].details == {"agent_init_script_present": False}
    assert status.checks["capabilities"].ok is None
    assert status.checks["capabilities"].reason is None
    assert status.checks["talkback_rtp"].ok is True
    assert status.checks["talkback_rtp"].reason is None
    assert status.checks["firewall"].ok is None


def test_self_test_contract_preserves_unknown_check_state() -> None:
    status = normalize_self_test(
        {
            "ok": True,
            "checks": {
                "homeassistant_user": {
                    "ok": None,
                    "reason": "device_user_status_unavailable",
                },
                "device_routing": {
                    "reason": "not_checked_device_user_status_unavailable",
                },
            },
        }
    )

    assert status.ok is True
    assert status.checks["homeassistant_user"].ok is None
    assert (
        status.checks["homeassistant_user"].reason
        == "device_user_status_unavailable"
    )
    assert status.checks["device_routing"].ok is None
