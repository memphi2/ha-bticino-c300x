from __future__ import annotations

from types import MappingProxyType

import pytest

from custom_components.bticino_c300x.camera_media.state_machine import (
    MediaPrimaryAction,
    MediaState,
    MediaStateInput,
    derive_media_state,
    media_state_input_from_video_status,
)


@pytest.mark.parametrize(
    ("facts", "expected_state", "expected_action"),
    [
        (MediaStateInput(video_owner="idle"), MediaState.IDLE, MediaPrimaryAction.START_STREAM),
        (
            MediaStateInput(video_owner="agent", video_window_available=False),
            MediaState.ON_DEMAND_STARTING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="agent", video_window_available=True),
            MediaState.ON_DEMAND_ACTIVE,
            MediaPrimaryAction.STOP_STREAM,
        ),
        (
            MediaStateInput(video_owner="ring", unanswered_ring_call=True),
            MediaState.RING_PENDING,
            MediaPrimaryAction.ANSWER_RING,
        ),
        (
            MediaStateInput(
                video_owner="ring",
                unanswered_ring_call=True,
                video_window_available=True,
            ),
            MediaState.RING_PENDING,
            MediaPrimaryAction.ANSWER_RING,
        ),
        (
            MediaStateInput(
                video_owner="ring",
                ring_media_active=True,
            ),
            MediaState.RING_PREVIEW_ACTIVE,
            MediaPrimaryAction.ANSWER_RING,
        ),
        (
            MediaStateInput(video_owner="ring", ring_answer_requested=True),
            MediaState.RING_ANSWERING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(
                video_owner="ring",
                ring_media_active=True,
                ring_audio_active=True,
            ),
            MediaState.RING_ACTIVE,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="ring", ring_answered=True),
            MediaState.RING_ACTIVE,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="ring", ring_hangup_requested=True),
            MediaState.RING_HANGING_UP,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="home_call"),
            MediaState.HOME_CALL_STARTING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_running=True),
            MediaState.HOME_CALL_RINGING,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_active=True),
            MediaState.HOME_CALL_RINGING,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_answered=True),
            MediaState.HOME_CALL_ACTIVE,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_stopping=True),
            MediaState.HOME_CALL_STOPPING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(rtsp_clients=1),
            MediaState.RTSP_BUSY,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(last_error="video_activate_failed"),
            MediaState.ERROR,
            MediaPrimaryAction.REFRESH,
        ),
        (
            MediaStateInput(cooldown_active=True),
            MediaState.COOLDOWN,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="unknown"),
            MediaState.UNKNOWN,
            MediaPrimaryAction.REFRESH,
        ),
    ],
)
def test_media_state_derivation(
    facts: MediaStateInput,
    expected_state: MediaState,
    expected_action: MediaPrimaryAction,
) -> None:
    result = derive_media_state(facts)

    assert result.state is expected_state
    assert result.primary_action is expected_action


def test_idle_allows_rtsp_start() -> None:
    result = derive_media_state(MediaStateInput(video_owner="idle"))

    assert result.rtsp_start_allowed is True
    assert result.capture_blocked is False


def test_external_owner_wins_over_local_session_state() -> None:
    result = derive_media_state(
        MediaStateInput(
            video_owner="external_media",
            external_media_active=True,
            local_sessions=1,
        )
    )

    assert result.state is MediaState.EXTERNAL_MEDIA_ACTIVE
    assert result.external_owner_blocks is True
    assert result.capture_blocked is True


def test_unknown_state_does_not_invent_available_media() -> None:
    result = derive_media_state(
        MediaStateInput(
            video_owner="unknown",
            video_window_available=True,
            local_sessions=0,
        )
    )

    assert result.state is MediaState.UNKNOWN
    assert result.refresh_status_required is True
    assert result.rtsp_start_allowed is False


def test_local_session_state_does_not_override_external_agent_state() -> None:
    result = derive_media_state(
        MediaStateInput(
            video_owner="external_media",
            external_media_active=True,
            local_sessions=2,
            ring_call_active=True,
        )
    )

    assert result.state is MediaState.EXTERNAL_MEDIA_ACTIVE
    assert result.primary_action is MediaPrimaryAction.NONE


def test_ring_preview_marks_local_owner_reusable() -> None:
    result = derive_media_state(
        MediaStateInput(
            video_owner="ring",
            unanswered_ring_call=True,
            ring_media_active=True,
        )
    )

    assert result.state is MediaState.RING_PREVIEW_ACTIVE
    assert result.local_owner_reusable is True


def test_ring_active_can_be_captured_when_rtsp_policy_admits_it() -> None:
    result = derive_media_state(
        MediaStateInput(
            video_owner="ring",
            ring_audio_active=True,
        )
    )

    assert result.state is MediaState.RING_ACTIVE
    assert result.capture_blocked is False


@pytest.mark.parametrize(
    "facts",
    [
        MediaStateInput(video_owner="ring"),
        MediaStateInput(
            video_owner="ring",
            unanswered_ring_call=True,
            video_window_available=True,
        ),
    ],
)
def test_ring_owner_without_media_stays_answerable_pending(
    facts: MediaStateInput,
) -> None:
    result = derive_media_state(facts)

    assert result.state is MediaState.RING_PENDING
    assert result.primary_action is MediaPrimaryAction.ANSWER_RING
    assert not result.rtsp_start_allowed


def test_non_ring_media_blocks_ring_capture() -> None:
    assert (
        derive_media_state(
            MediaStateInput(video_owner="agent", video_window_available=True)
        ).capture_blocked
        is True
    )
    assert (
        derive_media_state(MediaStateInput(video_owner="home_call", home_call_active=True)).capture_blocked
        is True
    )


def test_disabled_video_reports_unknown_and_blocks_capture() -> None:
    result = derive_media_state(
        MediaStateInput(video_owner="idle", entry_video_enabled=False)
    )

    assert result.state is MediaState.UNKNOWN
    assert result.capture_blocked is True


def test_video_status_mapping_contract_populates_state_facts() -> None:
    facts = media_state_input_from_video_status(
        MappingProxyType(
            {
                "media_owner": "ring",
                "window_available": True,
                "bridge": MappingProxyType(
                    {
                        "ring_call_active": True,
                        "ring_media_active": True,
                        "clients": "1",
                    }
                ),
            }
        )
    )

    assert facts.video_owner == "ring"
    assert facts.video_window_available is True
    assert facts.ring_call_active is True
    assert facts.ring_media_active is True
    assert facts.rtsp_clients == 1
    assert derive_media_state(facts).state is MediaState.RING_PREVIEW_ACTIVE


def test_video_status_missing_or_invalid_values_use_safe_defaults() -> None:
    missing = media_state_input_from_video_status(None)
    invalid_type = media_state_input_from_video_status(
        {"media_owner": "idle", "bridge": {"clients": object()}}
    )
    invalid_string = media_state_input_from_video_status(
        {"media_owner": "idle", "bridge": {"clients": "not-a-number"}}
    )

    assert missing.video_owner is None
    assert missing.rtsp_clients is None
    assert derive_media_state(missing).state is MediaState.IDLE
    assert invalid_type.rtsp_clients is None
    assert invalid_string.rtsp_clients is None


def test_doorbell_on_demand_lifecycle_sequence() -> None:
    """Doorbell stream transitions stay explicit and action-oriented."""

    sequence = [
        (MediaStateInput(video_owner="idle"), MediaState.IDLE, MediaPrimaryAction.START_STREAM),
        (
            MediaStateInput(video_owner="agent", video_window_available=False),
            MediaState.ON_DEMAND_STARTING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="agent", video_window_available=True),
            MediaState.ON_DEMAND_ACTIVE,
            MediaPrimaryAction.STOP_STREAM,
        ),
        (MediaStateInput(video_owner="idle"), MediaState.IDLE, MediaPrimaryAction.START_STREAM),
    ]

    for facts, state, action in sequence:
        result = derive_media_state(facts)
        assert result.state is state
        assert result.primary_action is action


def test_ring_call_lifecycle_sequence() -> None:
    """Ring Call states cover pending, preview, answer, active, and hangup."""

    sequence = [
        (
            MediaStateInput(video_owner="ring", unanswered_ring_call=True),
            MediaState.RING_PENDING,
            MediaPrimaryAction.ANSWER_RING,
        ),
        (
            MediaStateInput(
                video_owner="ring",
                unanswered_ring_call=True,
                ring_media_active=True,
            ),
            MediaState.RING_PREVIEW_ACTIVE,
            MediaPrimaryAction.ANSWER_RING,
        ),
        (
            MediaStateInput(video_owner="ring", ring_answer_requested=True),
            MediaState.RING_ANSWERING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="ring", ring_audio_active=True),
            MediaState.RING_ACTIVE,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="ring", ring_hangup_requested=True),
            MediaState.RING_HANGING_UP,
            MediaPrimaryAction.WAIT,
        ),
        (MediaStateInput(video_owner="idle"), MediaState.IDLE, MediaPrimaryAction.START_STREAM),
    ]

    for facts, state, action in sequence:
        result = derive_media_state(facts)
        assert result.state is state
        assert result.primary_action is action


def test_home_call_lifecycle_sequence() -> None:
    """Home Call transitions remain audio-call specific and block doorbell capture."""

    sequence = [
        (
            MediaStateInput(video_owner="home_call"),
            MediaState.HOME_CALL_STARTING,
            MediaPrimaryAction.WAIT,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_running=True),
            MediaState.HOME_CALL_RINGING,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_active=True),
            MediaState.HOME_CALL_RINGING,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_answered=True),
            MediaState.HOME_CALL_ACTIVE,
            MediaPrimaryAction.HANGUP,
        ),
        (
            MediaStateInput(video_owner="home_call", home_call_stopping=True),
            MediaState.HOME_CALL_STOPPING,
            MediaPrimaryAction.WAIT,
        ),
        (MediaStateInput(video_owner="idle"), MediaState.IDLE, MediaPrimaryAction.START_STREAM),
    ]

    for facts, state, action in sequence:
        result = derive_media_state(facts)
        assert result.state is state
        assert result.primary_action is action
        if state.name.startswith("HOME_CALL"):
            assert result.capture_blocked is True
