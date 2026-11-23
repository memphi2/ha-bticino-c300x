"""Follow a station to a new address only after it proves the saved identity.

mDNS is unauthenticated. A station proves itself by answering a fresh nonce
with an HMAC keyed by the saved access token over its identity and the
address the request reached it on. An entry saved with an IPv4 literal moves
to an announced address only when the saved address no longer proves the
identity and the announced one does. The requests carry no credentials, and
a relay gets a proof for the address of the real station, not for its own.
Host names are left alone: they resolve on their own.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientTimeout

from ._api_normalize import build_agent_base_url
from .config_flow_entry_update import async_update_reconfigured_entry
from .config_flow_identity import (
    entry_connection_matches_discovery,
    entry_identity_connection,
    entry_uses_manual_setup_unique_id,
)
from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, CONF_AGENT_TOKEN, DOMAIN
from .discovery import discovery_matches_entry
from .http_body import read_capped_body

_LOGGER = logging.getLogger(__name__)

PROOF_CONTEXT = "c300x-identity-v1"
MOVE_RETRY_SECONDS = 600.0
_ATTEMPTS_KEY = f"{DOMAIN}_discovery_move_attempts"
_TIMEOUT = ClientTimeout(total=3.0)
_MAX_REPLY_BYTES = 4096
# The agent refuses proofs for shorter tokens: they could be guessed offline.
_MIN_TOKEN_LENGTH = 32
_PROOF = re.compile(r"[0-9a-f]{64}")


def identity_proof(token: str, device_id: str, host: str, port: int, nonce: str) -> str:
    """Return the proof the agent computes for this identity and address."""
    message = f"{PROOF_CONTEXT}\n{device_id}\n{host}:{port}\n{nonce}"
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


async def async_follow_proven_move(
    flow: Any, discovered_unique_id: str | None, connection: dict[str, Any],
) -> bool:
    """Move the matching entry to the announced IPv4 endpoint once proven."""
    host = _routable_ipv4(connection.get(CONF_AGENT_HOST))
    if discovered_unique_id is None or host is None:
        return False
    port = int(connection[CONF_AGENT_PORT])
    entry = next((
        entry for entry in flow._async_current_entries()
        if discovery_matches_entry(discovered_unique_id, entry.unique_id)
    ), None)
    announced = {CONF_AGENT_HOST: host, CONF_AGENT_PORT: port}
    if (
        entry is None or entry_uses_manual_setup_unique_id(entry)
        or entry_connection_matches_discovery(entry, announced)
    ):
        return False
    saved, unique_id = entry_identity_connection(entry), entry.unique_id
    token = str(saved[CONF_AGENT_TOKEN] or "")
    old_host = _routable_ipv4(saved[CONF_AGENT_HOST])
    if (
        old_host is None or len(token) < _MIN_TOKEN_LENGTH
        or not _start_attempt(flow.hass, entry.entry_id)
    ):
        return False
    old_port = int(saved[CONF_AGENT_PORT])
    old, new = f"{old_host}:{old_port}", f"{host}:{port}"
    if await _async_identity_proven(flow.hass, old_host, old_port, unique_id, token):
        _LOGGER.debug(
            "%s still proves its identity at %s; ignoring the announcement at %s",
            entry.title, old, new,
        )
        return False
    proven = await _async_identity_proven(flow.hass, host, port, unique_id, token)
    if proven is None:
        _LOGGER.debug("%s: no identity proof from %s; keeping %s", entry.title, new, old)
        return False
    if not proven:
        _LOGGER.warning(
            "%s: the station announced at %s did not prove the saved identity; keeping %s",
            entry.title, new, old,
        )
        return False
    if (
        entry not in flow._async_current_entries() or entry.unique_id != unique_id
        or entry_identity_connection(entry) != saved
    ):
        return False
    async_update_reconfigured_entry(flow, entry, announced, frozenset(announced))
    _LOGGER.info("%s moved from %s to %s (identity proven)", entry.title, old, new)
    return True


def _routable_ipv4(value: Any) -> str | None:
    try:
        address = ipaddress.IPv4Address(str(value or "").strip())
    except ValueError:
        return None
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        return None
    return str(address)


def _start_attempt(hass: Any, entry_id: str) -> bool:
    """Allow one attempt per entry and interval; mDNS repeats announcements."""
    attempts: dict[str, float] = hass.data.setdefault(_ATTEMPTS_KEY, {})
    now, last = monotonic(), attempts.get(entry_id)
    if last is not None and now - last < MOVE_RETRY_SECONDS:
        return False
    attempts[entry_id] = now
    return True


def _proves(
    reply: dict[str, Any], unique_id: str, token: str, host: str, port: int, nonce: str,
) -> bool:
    device_id, proof = reply.get("id"), reply.get("proof")
    if (
        reply.get("ok") is not True or not isinstance(device_id, str)
        or not isinstance(proof, str) or not _PROOF.fullmatch(proof)
        or not discovery_matches_entry(device_id, unique_id)
    ):
        return False
    return hmac.compare_digest(proof, identity_proof(token, device_id, host, port, nonce))


async def _async_identity_proven(
    hass: Any, host: str, port: int, unique_id: str, token: str,
) -> bool | None:
    """Ask host:port to prove the identity; None when it gave no proof reply."""
    nonce = secrets.token_hex(32)
    status, reply = await _async_request_proof(hass, host, port, nonce)
    if status != 200 or not isinstance(reply, dict):
        return None
    return _proves(reply, unique_id, token, host, port, nonce)


async def _async_request_proof(hass: Any, host: str, port: int, nonce: str) -> tuple[int, Any]:
    """Send the nonce without credentials; return status and decoded JSON."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    url = f"{build_agent_base_url(host, port)}/api/v1/identity/proof"
    try:
        async with async_get_clientsession(hass).request(
            "POST", url, json={"nonce": nonce}, allow_redirects=False, timeout=_TIMEOUT,
        ) as response:
            status = response.status
            raw = await read_capped_body(response.content, response.content_length, _MAX_REPLY_BYTES)
    except (TimeoutError, ClientError):
        return 0, None
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None
