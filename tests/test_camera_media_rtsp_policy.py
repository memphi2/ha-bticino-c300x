from __future__ import annotations

from types import MappingProxyType

from custom_components.bticino_c300x.camera_media.rtsp_policy import (
    RtspAdmissionKind,
    RtspConsumer,
    RtspResourceSnapshot,
    RtspSessionOwner,
    decide_rtsp_admission,
    rtsp_resource_snapshot_from_status,
    rtsp_session_owner_from_status,
)


def test_idle_allows_first_consumer() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.DOORBELL_CARD,
        RtspResourceSnapshot(owner=RtspSessionOwner.IDLE),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.ALLOW


def test_external_owner_blocks_ha_consumer() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.DOORBELL_CARD,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.EXTERNAL_MEDIA,
            external_media_active=True,
            external_owner="smartphone",
        ),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_EXTERNAL_OWNER
    assert decision.reason == "smartphone"


def test_unknown_owner_requires_refresh_before_starting() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(owner=RtspSessionOwner.UNKNOWN, rtsp_clients=None),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.REFRESH_STATUS_REQUIRED


def test_unknown_busy_owner_uses_safe_deny() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(owner=RtspSessionOwner.UNKNOWN, rtsp_clients=1),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.UNKNOWN_SAFE_DENY


def test_ring_preview_can_transition_to_answered_flow() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.RING_ANSWERED,
        RtspResourceSnapshot(owner=RtspSessionOwner.RING_PREVIEW, rtsp_clients=0),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.REUSE_EXISTING


def test_capture_can_reuse_ring_preview_when_no_rtsp_client_is_attached() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(owner=RtspSessionOwner.RING_PREVIEW, rtsp_clients=0),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.REUSE_EXISTING


def test_capture_can_reuse_answered_ring_when_no_rtsp_client_is_attached() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(owner=RtspSessionOwner.RING_ANSWERED, rtsp_clients=0),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.REUSE_EXISTING


def test_capture_is_blocked_when_rtsp_client_is_active() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(owner=RtspSessionOwner.DOORBELL_CARD, rtsp_clients=1),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_BUSY


def test_second_browser_is_not_shared_without_explicit_support() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.DOORBELL_CARD,
        RtspResourceSnapshot(owner=RtspSessionOwner.DOORBELL_CARD, rtsp_clients=1),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_BUSY


def test_on_demand_browser_is_not_shared_even_with_support_flag() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.DOORBELL_CARD,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.DOORBELL_CARD,
            rtsp_clients=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_BUSY


def test_ring_preview_capture_can_share_when_agent_reports_capacity() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_PREVIEW,
            rtsp_clients=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.ALLOW_SHARED


def test_ring_preview_second_browser_can_share_when_agent_reports_capacity() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.RING_PREVIEW,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_PREVIEW,
            rtsp_clients=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.ALLOW_SHARED


def test_answered_ring_stream_can_share_preview_transition_capacity() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.RING_ANSWERED,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_ANSWERED,
            rtsp_clients=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.ALLOW_SHARED


def test_ring_preview_sharing_stops_at_reported_capacity() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_PREVIEW,
            rtsp_clients=2,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_BUSY


def test_agent_client_count_and_local_sessions_are_not_double_counted() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.RING_PREVIEW,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_PREVIEW,
            rtsp_clients=1,
            local_sessions=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is True
    assert decision.kind is RtspAdmissionKind.ALLOW_SHARED


def test_ring_answered_does_not_share_even_when_capacity_is_reported() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.CAPTURE,
        RtspResourceSnapshot(
            owner=RtspSessionOwner.RING_ANSWERED,
            rtsp_clients=1,
            max_clients=2,
            sharing_supported=True,
        ),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_BUSY


def test_home_call_does_not_steal_doorbell_media() -> None:
    decision = decide_rtsp_admission(
        RtspConsumer.DOORBELL_CARD,
        RtspResourceSnapshot(owner=RtspSessionOwner.HOME_CALL, rtsp_clients=0),
    )

    assert decision.allowed is False
    assert decision.kind is RtspAdmissionKind.DENY_INCOMPATIBLE_MEDIA


def test_owner_mapping_uses_agent_status_facts() -> None:
    assert rtsp_session_owner_from_status(None) is RtspSessionOwner.UNKNOWN
    assert (
        rtsp_session_owner_from_status({"media_owner": "idle", "bridge": {}})
        is RtspSessionOwner.IDLE
    )
    assert (
        rtsp_session_owner_from_status({"media_owner": "external_media"})
        is RtspSessionOwner.EXTERNAL_MEDIA
    )
    assert (
        rtsp_session_owner_from_status(
            {"media_owner": "ring", "bridge": {"ring_media_active": False}}
        )
        is RtspSessionOwner.RING_PREVIEW
    )
    assert (
        rtsp_session_owner_from_status(
            {"media_owner": "ring", "bridge": {"ring_media_active": True}}
        )
        is RtspSessionOwner.RING_PREVIEW
    )
    assert (
        rtsp_session_owner_from_status(
            {"media_owner": "ring", "bridge": {"ring_audio_active": True}}
        )
        is RtspSessionOwner.RING_ANSWERED
    )
    assert (
        rtsp_session_owner_from_status(
            {"media_owner": "ring", "bridge": {"ring_answer_requested": True}}
        )
        is RtspSessionOwner.RING_ANSWERED
    )
    assert (
        rtsp_session_owner_from_status(
            {"media_owner": "ring", "bridge": {"ring_answered": True}}
        )
        is RtspSessionOwner.RING_ANSWERED
    )
    assert (
        rtsp_session_owner_from_status({"bridge": {"media_owner": "home_call"}})
        is RtspSessionOwner.HOME_CALL
    )


def test_snapshot_mapping_uses_agent_status_facts() -> None:
    snapshot = rtsp_resource_snapshot_from_status(
        {
            "external_media_active": False,
            "bridge": {
                "media_owner": "ring",
                "ring_media_active": True,
                "clients": "1",
                "max_clients": "2",
                "ring_preview_sharing": True,
            },
        },
        local_sessions=1,
    )

    assert snapshot.owner is RtspSessionOwner.RING_PREVIEW
    assert snapshot.rtsp_clients == 1
    assert snapshot.local_sessions == 1
    assert snapshot.max_clients == 2
    assert snapshot.external_media_active is False
    assert snapshot.sharing_supported is True


def test_snapshot_accepts_typed_mapping_agent_status() -> None:
    snapshot = rtsp_resource_snapshot_from_status(
        MappingProxyType(
            {
                "external_media_active": False,
                "bridge": MappingProxyType(
                    {
                        "media_owner": "ring",
                        "ring_media_active": True,
                        "clients": "1",
                        "max_clients": "1",
                        "ring_preview_sharing": True,
                    }
                ),
            }
        )
    )

    assert snapshot.owner is RtspSessionOwner.RING_PREVIEW
    assert snapshot.rtsp_clients == 1
    assert snapshot.max_clients == 1
    assert snapshot.sharing_supported is True
    assert (
        decide_rtsp_admission(RtspConsumer.CAPTURE, snapshot).kind
        is RtspAdmissionKind.DENY_BUSY
    )


def test_snapshot_discards_invalid_agent_count_and_blank_owner_values() -> None:
    snapshot = rtsp_resource_snapshot_from_status(
        {
            "external_owner": "   ",
            "bridge": {
                "clients": object(),
                "max_clients": "not-a-number",
            },
        }
    )

    assert snapshot.rtsp_clients is None
    assert snapshot.max_clients == 1
    assert snapshot.external_owner is None


def test_compatible_owners_reuse_existing_idle_clientless_resources() -> None:
    assert (
        decide_rtsp_admission(
            RtspConsumer.RING_ANSWERED,
            RtspResourceSnapshot(owner=RtspSessionOwner.RING_ANSWERED, rtsp_clients=0),
        ).kind
        is RtspAdmissionKind.REUSE_EXISTING
    )
    assert (
        decide_rtsp_admission(
            RtspConsumer.DOORBELL_CARD,
            RtspResourceSnapshot(owner=RtspSessionOwner.DOORBELL_CARD, rtsp_clients=0),
        ).kind
        is RtspAdmissionKind.REUSE_EXISTING
    )
    assert (
        decide_rtsp_admission(
            RtspConsumer.UNKNOWN,
            RtspResourceSnapshot(owner=RtspSessionOwner.CAPTURE, rtsp_clients=0),
        ).kind
        is RtspAdmissionKind.DENY_BUSY
    )


def test_ring_preview_dual_client_policy_matrix() -> None:
    """Only unanswered Ring preview is shareable, and only within reported capacity."""

    shareable = RtspResourceSnapshot(
        owner=RtspSessionOwner.RING_PREVIEW,
        rtsp_clients=1,
        max_clients=2,
        sharing_supported=True,
    )
    full = RtspResourceSnapshot(
        owner=RtspSessionOwner.RING_PREVIEW,
        rtsp_clients=2,
        max_clients=2,
        sharing_supported=True,
    )
    answered = RtspResourceSnapshot(
        owner=RtspSessionOwner.RING_ANSWERED,
        rtsp_clients=1,
        max_clients=2,
        sharing_supported=True,
    )

    assert (
        decide_rtsp_admission(RtspConsumer.RING_PREVIEW, shareable).kind
        is RtspAdmissionKind.ALLOW_SHARED
    )
    assert (
        decide_rtsp_admission(RtspConsumer.CAPTURE, shareable).kind
        is RtspAdmissionKind.ALLOW_SHARED
    )
    assert (
        decide_rtsp_admission(RtspConsumer.CAPTURE, full).kind
        is RtspAdmissionKind.DENY_BUSY
    )
    assert (
        decide_rtsp_admission(RtspConsumer.CAPTURE, answered).kind
        is RtspAdmissionKind.DENY_BUSY
    )
