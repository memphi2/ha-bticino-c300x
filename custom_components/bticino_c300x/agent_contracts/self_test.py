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


def _legacy_device_user_result(details: Mapping[str, Any]) -> tuple[bool, str]:
    """Re-evaluate the overstrict 1.9.5 check using its reported setup facts."""

    required = (
        ("homeassistant_user_present", "homeassistant_user_missing"),
        ("media_identity_available", "media_identity_missing"),
        ("routes_consistent", "homeassistant_routes_inconsistent"),
    )
    for field, reason in required:
        if details.get(field) is False:
            return False, reason
    if all(details.get(field) is True for field, _ in required):
        return True, "homeassistant_user_ok"
    return False, "device_user_status_unavailable"


def normalize_self_test_contract(
    data: Any,
    error_cls: type[Exception] = ValueError,
) -> SelfTestStatus:
    """Normalize device-agent self-test status."""

    if not isinstance(data, dict):
        raise error_cls("self-test returned non-object JSON")
    checks: dict[str, SelfTestCheck] = {}
    corrected_device_user = False
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
            ok = _optional_bool(raw_check.get("ok"))
            reason = _optional_string(raw_check.get("reason"))
            if name == "homeassistant_user" and ok is False and reason == "device_sip_user_missing":
                ok, reason = _legacy_device_user_result(details)
                corrected_device_user = True
            checks[name] = SelfTestCheck(
                raw=dict(raw_check),
                ok=ok,
                reason=reason,
                details=details,
            )
    return SelfTestStatus(
        raw=data,
        api_version=_optional_string(data.get("api_version")),
        agent_version=_optional_string(data.get("agent_version")),
        firmware_family=_optional_string(data.get("firmware_family")),
        ok=(
            all(check.ok is True for check in checks.values())
            if corrected_device_user
            else _optional_bool(data.get("ok")) is True
        ),
        checks=checks,
    )
