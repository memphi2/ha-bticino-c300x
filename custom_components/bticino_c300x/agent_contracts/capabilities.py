"""Typed `/api/v1/capabilities` contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class CapabilityPayload(AgentContract):
    """Normalized device-agent capability payload."""

    version: str | None
    agent: dict[str, Any]
    implementation: str | None
    api_version: str | None
    device_id: str | None
    model: str | None
    firmware: str | None
    capabilities: dict[str, Any]
