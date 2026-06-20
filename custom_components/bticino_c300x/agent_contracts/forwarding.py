"""Typed forwarding contracts for device-agent responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class ForwardingStatus(AgentContract):
    """Normalized smartphone-forwarding status."""

    mode: int | None
    state: str
    raw: Any
