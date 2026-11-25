"""Typed device-agent API contracts."""

from .base import AgentContract
from .calls import (
    Call,
    CallsPayload,
    HomeCallStatus,
    OutdoorUnit,
    OutdoorUnitsPayload,
    RingCallStatus,
)
from .capabilities import CapabilityPayload
from .diagnostics import AgentDiagnosticsStatus
from .forwarding import ForwardingStatus
from .maintenance import AuthConfigStatus, FirewallStatus
from .self_test import SelfTestCheck, SelfTestStatus
from .video import DoorbellVideoStatus

__all__ = [
    "AgentContract",
    "AgentDiagnosticsStatus",
    "Call",
    "CallsPayload",
    "AuthConfigStatus",
    "CapabilityPayload",
    "DoorbellVideoStatus",
    "FirewallStatus",
    "ForwardingStatus",
    "HomeCallStatus",
    "OutdoorUnit",
    "OutdoorUnitsPayload",
    "RingCallStatus",
    "SelfTestCheck",
    "SelfTestStatus",
]
