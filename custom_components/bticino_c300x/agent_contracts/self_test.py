"""Typed `/api/v1/self-test` contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..value_parsing import (
    optional_bool as _optional_bool,
)
from ..value_parsing import (
    optional_string as _optional_string,
)
from .base import AgentContract


@dataclass(frozen=True, slots=True, eq=False)
class SelfTestCheck(AgentContract):
    """One normalized device-agent self-test check."""

    ok: bool | None
    reason: str | None
    details: dict[str, Any]


@dataclass(frozen=True, slots=True, eq=False)
class SelfTestStatus(AgentContract):
    """Normalized device-agent self-test payload."""

    api_version: str | None
    agent_version: str | None
    firmware_family: str | None
    ok: bool
    checks: dict[str, SelfTestCheck]


def normalize_self_test_contract(
    data: Any,
    error_cls: type[Exception] = ValueError,
) -> SelfTestStatus:
    """Normalize device-agent self-test status."""

    if not isinstance(data, dict):
        raise error_cls("self-test returned non-object JSON")
    checks: dict[str, SelfTestCheck] = {}
    raw_checks = data.get("checks")
    if isinstance(raw_checks, Mapping):
        for name, raw_check in raw_checks.items():
            if not isinstance(name, str) or not isinstance(raw_check, Mapping):
                continue
            details = {
                str(key): value
                for key, value in raw_check.items()
                if key not in {"ok", "reason"}
            }
            checks[name] = SelfTestCheck(
                raw=dict(raw_check),
                ok=_optional_bool(raw_check.get("ok")),
                reason=_optional_string(raw_check.get("reason")),
                details=details,
            )
    return SelfTestStatus(
        raw=data,
        api_version=_optional_string(data.get("api_version")),
        agent_version=_optional_string(data.get("agent_version")),
        firmware_family=_optional_string(data.get("firmware_family")),
        ok=_optional_bool(data.get("ok")) is True,
        checks=checks,
    )
