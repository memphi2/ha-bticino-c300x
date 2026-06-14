"""RTSP admission policy for C300X media consumers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class RtspConsumer(StrEnum):
    """Known HA-side RTSP consumers."""

    DOORBELL_CARD = "doorbell_card"
    RING_PREVIEW = "ring_preview"
    RING_ANSWERED = "ring_answered"
    CAPTURE = "capture"
    HOME_CALL = "home_call"
    UNKNOWN = "unknown"


class RtspSessionOwner(StrEnum):
    """Current factual owner of the RTSP/media resource."""

    IDLE = "idle"
    DOORBELL_CARD = "doorbell_card"
    RING_PREVIEW = "ring_preview"
    RING_ANSWERED = "ring_answered"
    CAPTURE = "capture"
    HOME_CALL = "home_call"
    EXTERNAL_MEDIA = "external_media"
    UNKNOWN = "unknown"


class RtspAdmissionKind(StrEnum):
    """Outcome of an RTSP admission decision."""

    ALLOW = "allow"
    ALLOW_SHARED = "allow_shared"
    REUSE_EXISTING = "reuse_existing"
    DENY_BUSY = "deny_busy"
    DENY_EXTERNAL_OWNER = "deny_external_owner"
    DENY_INCOMPATIBLE_MEDIA = "deny_incompatible_media"
    REFRESH_STATUS_REQUIRED = "refresh_status_required"
    UNKNOWN_SAFE_DENY = "unknown_safe_deny"


@dataclass(frozen=True)
class RtspResourceSnapshot:
    """Facts available before admitting a new RTSP consumer."""

    owner: RtspSessionOwner = RtspSessionOwner.UNKNOWN
    rtsp_clients: int | None = None
    local_sessions: int = 0
    max_clients: int = 1
    external_media_active: bool = False
    external_owner: str | None = None
    sharing_supported: bool = False


@dataclass(frozen=True)
class RtspAdmissionDecision:
    """Decision returned by the RTSP admission policy."""

    kind: RtspAdmissionKind
    reason: str

    @property
    def allowed(self) -> bool:
        return self.kind in {
            RtspAdmissionKind.ALLOW,
            RtspAdmissionKind.ALLOW_SHARED,
            RtspAdmissionKind.REUSE_EXISTING,
        }


def rtsp_session_owner_from_status(status: Mapping[str, object] | None) -> RtspSessionOwner:
    """Map normalized agent media status to a policy owner."""

    if not status:
        return RtspSessionOwner.UNKNOWN
    bridge = _mapping_or_empty(status.get("bridge"))
    raw_owner = str(status.get("media_owner") or bridge.get("media_owner") or "").lower()
    if raw_owner == "ring":
        if (
            bool(bridge.get("ring_audio_active"))
            or bool(bridge.get("ring_answer_requested"))
            or bool(bridge.get("ring_answered"))
        ):
            return RtspSessionOwner.RING_ANSWERED
        return RtspSessionOwner.RING_PREVIEW
    if raw_owner == "home_call":
        return RtspSessionOwner.HOME_CALL
    if raw_owner == "agent":
        return RtspSessionOwner.DOORBELL_CARD
    if raw_owner == "external_media":
        return RtspSessionOwner.EXTERNAL_MEDIA
    if raw_owner == "idle":
        return RtspSessionOwner.IDLE
    return RtspSessionOwner.UNKNOWN


def rtsp_resource_snapshot_from_status(
    status: Mapping[str, object] | None,
    *,
    local_sessions: int = 0,
) -> RtspResourceSnapshot:
    """Build an RTSP policy snapshot from normalized native-agent video status."""

    bridge = _mapping_or_empty(status.get("bridge") if status is not None else None)
    return RtspResourceSnapshot(
        owner=rtsp_session_owner_from_status(status),
        rtsp_clients=_optional_int(bridge.get("clients")),
        local_sessions=local_sessions,
        max_clients=_optional_int(bridge.get("max_clients")) or 1,
        external_media_active=bool(
            (status or {}).get("external_media_active")
            or bridge.get("external_media_active")
        ),
        external_owner=_optional_string(
            (status or {}).get("external_owner") or bridge.get("external_owner")
        ),
        sharing_supported=bool(bridge.get("ring_preview_sharing")),
    )


def decide_rtsp_admission(
    consumer: RtspConsumer,
    snapshot: RtspResourceSnapshot,
) -> RtspAdmissionDecision:
    """Return whether a new RTSP consumer may start."""

    if snapshot.external_media_active or snapshot.owner is RtspSessionOwner.EXTERNAL_MEDIA:
        return RtspAdmissionDecision(
            RtspAdmissionKind.DENY_EXTERNAL_OWNER,
            snapshot.external_owner or "external_media_active",
        )

    if snapshot.owner is RtspSessionOwner.HOME_CALL and consumer is not RtspConsumer.HOME_CALL:
        return RtspAdmissionDecision(
            RtspAdmissionKind.DENY_INCOMPATIBLE_MEDIA,
            "home_call_active",
        )

    if snapshot.owner is RtspSessionOwner.UNKNOWN:
        if snapshot.rtsp_clients is None:
            return RtspAdmissionDecision(
                RtspAdmissionKind.REFRESH_STATUS_REQUIRED,
                "owner_unknown",
            )
        if snapshot.rtsp_clients > 0 or snapshot.local_sessions > 0:
            return RtspAdmissionDecision(
                RtspAdmissionKind.UNKNOWN_SAFE_DENY,
                "unknown_owner_busy",
            )

    if consumer is RtspConsumer.RING_ANSWERED and snapshot.owner is RtspSessionOwner.RING_PREVIEW:
        return RtspAdmissionDecision(
            RtspAdmissionKind.REUSE_EXISTING,
            "ring_preview_to_answer",
        )

    active_clients = max(snapshot.rtsp_clients or 0, snapshot.local_sessions)
    if active_clients > 0:
        if (
            snapshot.sharing_supported
            and active_clients < max(1, snapshot.max_clients)
            and _is_shareable(consumer, snapshot.owner)
        ):
            return RtspAdmissionDecision(
                RtspAdmissionKind.ALLOW_SHARED,
                "sharing_supported",
            )
        return RtspAdmissionDecision(
            RtspAdmissionKind.DENY_BUSY,
            "rtsp_consumer_active",
        )

    if snapshot.owner is RtspSessionOwner.IDLE:
        return RtspAdmissionDecision(RtspAdmissionKind.ALLOW, "idle")

    if snapshot.owner in _compatible_existing_owners(consumer):
        return RtspAdmissionDecision(RtspAdmissionKind.REUSE_EXISTING, "compatible_owner")

    return RtspAdmissionDecision(RtspAdmissionKind.DENY_BUSY, "owner_active")


def _compatible_existing_owners(consumer: RtspConsumer) -> set[RtspSessionOwner]:
    if consumer is RtspConsumer.HOME_CALL:
        return {RtspSessionOwner.HOME_CALL}
    if consumer is RtspConsumer.RING_PREVIEW:
        return {RtspSessionOwner.RING_PREVIEW}
    if consumer is RtspConsumer.RING_ANSWERED:
        return {RtspSessionOwner.RING_ANSWERED, RtspSessionOwner.RING_PREVIEW}
    if consumer is RtspConsumer.DOORBELL_CARD:
        return {RtspSessionOwner.DOORBELL_CARD}
    if consumer is RtspConsumer.CAPTURE:
        return {
            RtspSessionOwner.CAPTURE,
            RtspSessionOwner.RING_PREVIEW,
            RtspSessionOwner.RING_ANSWERED,
        }
    return set()


def _is_shareable(consumer: RtspConsumer, owner: RtspSessionOwner) -> bool:
    if owner is RtspSessionOwner.RING_PREVIEW:
        return consumer in {RtspConsumer.CAPTURE, RtspConsumer.RING_PREVIEW}
    if owner is RtspSessionOwner.RING_ANSWERED:
        return consumer is RtspConsumer.RING_ANSWERED
    return False


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
