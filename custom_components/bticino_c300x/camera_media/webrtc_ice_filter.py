"""ICE candidate filtering for the C300X WebRTC provider path.

Home Assistant's WebRTC provider (go2rtc) sends its local ICE candidates to the
browser through this integration. On multi-VLAN / dual-stack networks a rotating
global/SLAAC IPv6 address or a cross-subnet link-local provider candidate can
win ICE and then stall (consent timeout), which shows up as a stream that
freezes a few seconds after start.

These helpers classify provider-side candidates by address scope and decide,
per policy, whether to forward them. TURN ``relay`` candidates are never
dropped so a cloud connection always keeps its fallback path, and anything that
cannot be parsed is passed through unchanged (fail open -- never break
connectivity). Browser-to-provider candidates are intentionally not filtered in
``camera.py`` because dropping the browser's remote candidates can prevent the
provider from ever establishing the session.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import is_dataclass, replace
from typing import Any

from ..const import (
    CONF_WEBRTC_ICE_POLICY,
    DEFAULT_WEBRTC_ICE_POLICY,
    WEBRTC_ICE_POLICY_ALL,
    WEBRTC_ICE_POLICY_DROP_LINK_LOCAL,
    WEBRTC_ICE_POLICY_IPV4_ONLY,
    WEBRTC_ICE_POLICY_PREFER_IPV4_ULA,
)
from ..entry_config import entry_config_value

# Address scope categories a candidate can fall into.
CATEGORY_IPV4 = "ipv4"
CATEGORY_IPV4_LINK_LOCAL = "ipv4_link_local"
CATEGORY_IPV6_GLOBAL = "ipv6_global"
CATEGORY_IPV6_ULA = "ipv6_ula"
CATEGORY_IPV6_LINK_LOCAL = "ipv6_link_local"
CATEGORY_MDNS = "mdns"
CATEGORY_UNKNOWN = "unknown"

_ULA_NETWORK = ipaddress.ip_network("fc00::/7")

# Which address categories each policy drops. "all" (and any unknown policy)
# maps to an empty set -> nothing is dropped. mDNS/unknown are never dropped.
_DROP_CATEGORIES: dict[str, frozenset[str]] = {
    WEBRTC_ICE_POLICY_ALL: frozenset(),
    WEBRTC_ICE_POLICY_DROP_LINK_LOCAL: frozenset(
        {CATEGORY_IPV4_LINK_LOCAL, CATEGORY_IPV6_LINK_LOCAL}
    ),
    WEBRTC_ICE_POLICY_PREFER_IPV4_ULA: frozenset(
        {CATEGORY_IPV4_LINK_LOCAL, CATEGORY_IPV6_LINK_LOCAL, CATEGORY_IPV6_GLOBAL}
    ),
    WEBRTC_ICE_POLICY_IPV4_ONLY: frozenset(
        {
            CATEGORY_IPV4_LINK_LOCAL,
            CATEGORY_IPV6_LINK_LOCAL,
            CATEGORY_IPV6_GLOBAL,
            CATEGORY_IPV6_ULA,
        }
    ),
}


def classify_ice_address(address: str | None) -> str:
    """Return the scope category for an ICE candidate connection address."""

    if not address:
        return CATEGORY_UNKNOWN
    addr = str(address).strip()
    if not addr:
        return CATEGORY_UNKNOWN
    if addr.lower().endswith(".local"):
        return CATEGORY_MDNS
    # Drop any IPv6 zone id (e.g. fe80::1%eth0) before parsing.
    addr = addr.split("%", 1)[0]
    try:
        ip: Any = ipaddress.ip_address(addr)
    except ValueError:
        return CATEGORY_UNKNOWN
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is None:
            if ip.is_link_local:
                return CATEGORY_IPV6_LINK_LOCAL
            if ip in _ULA_NETWORK:
                return CATEGORY_IPV6_ULA
            return CATEGORY_IPV6_GLOBAL
        ip = mapped
    if ip.is_link_local:  # IPv4 169.254.0.0/16
        return CATEGORY_IPV4_LINK_LOCAL
    return CATEGORY_IPV4


def parse_ice_candidate(line: str | None) -> tuple[str, str] | None:
    """Return ``(connection_address, candidate_type)`` for an SDP candidate line.

    Returns ``None`` for anything that is not a parseable ``candidate:`` line
    (including the empty end-of-candidates marker).
    """

    if not line:
        return None
    text = str(line).strip()
    if text.startswith("a="):
        text = text[2:]
    if not text.startswith("candidate:"):
        return None
    parts = text.split()
    if len(parts) < 6:
        return None
    address = parts[4]
    cand_type = ""
    for index, token in enumerate(parts):
        if token == "typ" and index + 1 < len(parts):
            cand_type = parts[index + 1].lower()
            break
    return address, cand_type


def ice_candidate_should_pass(line: str | None, policy: str | None) -> bool:
    """Whether an SDP candidate line should be forwarded under ``policy``."""

    drop = _DROP_CATEGORIES.get(str(policy or WEBRTC_ICE_POLICY_ALL))
    if not drop:
        # "all" or an unrecognised policy -> forward everything.
        return True
    parsed = parse_ice_candidate(line)
    if parsed is None:
        return True
    address, cand_type = parsed
    if cand_type == "relay":
        # Never drop a TURN relay candidate: it is the cloud fallback path.
        return True
    return classify_ice_address(address) not in drop


def extract_candidate_sdp(obj: Any, _depth: int = 0) -> str | None:
    """Dig the SDP candidate string out of a candidate/message object.

    Handles a raw string, a mapping with a ``candidate`` key, and objects that
    expose a ``candidate`` attribute (an ``RTCIceCandidate``, or a
    ``WebRTCCandidate`` message whose ``candidate`` is itself an
    ``RTCIceCandidate``). Returns ``None`` when no candidate string is found.
    """

    if obj is None or _depth > 4:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, Mapping):
        nested = obj.get("candidate")
        return extract_candidate_sdp(nested, _depth + 1) if nested is not None else None
    nested = getattr(obj, "candidate", None)
    if nested is None or nested is obj:
        return None
    if isinstance(nested, str):
        return nested
    return extract_candidate_sdp(nested, _depth + 1)


def candidate_object_should_pass(obj: Any, policy: str | None) -> bool:
    """Whether a candidate/message object should be forwarded under ``policy``.

    Non-candidate messages (no extractable SDP) and unparseable candidates are
    always forwarded so filtering can never break the offer/answer exchange.
    """

    if not policy or policy == WEBRTC_ICE_POLICY_ALL:
        return True
    sdp = extract_candidate_sdp(obj)
    if sdp is None:
        return True
    return ice_candidate_should_pass(sdp, policy)


def entry_ice_policy(entry: Any) -> str:
    """Return the configured ICE candidate filter policy for a config entry."""

    return str(
        entry_config_value(entry, CONF_WEBRTC_ICE_POLICY, DEFAULT_WEBRTC_ICE_POLICY)
        or DEFAULT_WEBRTC_ICE_POLICY
    )


def filter_candidate(
    obj: Any,
    policy: str | None,
    *,
    logger: logging.Logger | None = None,
    direction: str = "",
) -> bool:
    """Whether a candidate passes ``policy``, logging a debug line when dropped."""

    if candidate_object_should_pass(obj, policy):
        return True
    if logger is not None:
        logger.debug(
            "C300X WebRTC dropping %s ICE candidate under policy %s: %s",
            direction,
            policy,
            extract_candidate_sdp(obj),
        )
    return False


def filter_sdp_candidate_lines(
    sdp: str,
    policy: str | None,
    *,
    logger: logging.Logger | None = None,
    direction: str = "",
) -> str:
    """Return ``sdp`` with candidate lines removed according to ``policy``."""

    if not policy or policy == WEBRTC_ICE_POLICY_ALL:
        return sdp
    lines: list[str] = []
    changed = False
    for line in sdp.splitlines(keepends=True):
        if ice_candidate_should_pass(line, policy):
            lines.append(line)
            continue
        changed = True
        if logger is not None:
            logger.debug(
                "C300X WebRTC dropping %s ICE candidate under policy %s: %s",
                direction,
                policy,
                line.strip(),
            )
    return "".join(lines) if changed else sdp


def _answer_sdp_field(obj: Any) -> tuple[str, str] | None:
    if isinstance(obj, Mapping):
        if obj.get("type") != "answer":
            return None
        for key in ("answer", "sdp"):
            value = obj.get(key)
            if isinstance(value, str):
                return key, value
        return None
    answer = getattr(obj, "answer", None)
    if isinstance(answer, str):
        return "answer", answer
    as_dict = getattr(obj, "as_dict", None)
    if callable(as_dict):
        with suppress(Exception):
            data = as_dict()
            if isinstance(data, Mapping) and data.get("type") == "answer":
                for key in ("answer", "sdp"):
                    value = data.get(key)
                    if isinstance(value, str):
                        return key, value
    return None


def _replace_answer_sdp(obj: Any, field: str, sdp: str) -> Any:
    if isinstance(obj, Mapping):
        updated = dict(obj)
        updated[field] = sdp
        return updated
    if is_dataclass(obj) and not isinstance(obj, type):
        with suppress(Exception):
            return replace(obj, **{field: sdp})
    return obj


def filter_webrtc_message(
    obj: Any,
    policy: str | None,
    *,
    logger: logging.Logger | None = None,
    direction: str = "",
) -> Any | None:
    """Return a WebRTC provider message with candidate policy applied."""

    if not filter_candidate(obj, policy, logger=logger, direction=direction):
        return None
    answer = _answer_sdp_field(obj)
    if answer is None:
        return obj
    field, sdp = answer
    filtered_sdp = filter_sdp_candidate_lines(
        sdp,
        policy,
        logger=logger,
        direction=direction,
    )
    if filtered_sdp == sdp:
        return obj
    return _replace_answer_sdp(obj, field, filtered_sdp)


def filter_candidate_for_entry(
    obj: Any,
    entry: Any,
    *,
    logger: logging.Logger | None = None,
    direction: str = "",
) -> bool:
    """``filter_candidate`` using the policy configured on ``entry``."""

    return filter_candidate(
        obj, entry_ice_policy(entry), logger=logger, direction=direction
    )


def filter_webrtc_message_for_entry(
    obj: Any,
    entry: Any,
    *,
    logger: logging.Logger | None = None,
    direction: str = "",
) -> Any | None:
    """``filter_webrtc_message`` using the policy configured on ``entry``."""

    return filter_webrtc_message(
        obj, entry_ice_policy(entry), logger=logger, direction=direction
    )
