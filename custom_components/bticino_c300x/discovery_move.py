"""Follow a station to a new address only after it proves the saved identity.

mDNS is unauthenticated. A station proves itself by answering a fresh nonce
with an HMAC keyed by the saved access token over its identity and the
address the request reached it on. An entry saved with an IPv4 literal moves
to an announced address only when the saved address no longer proves the
identity and the announced one does. The requests carry no credentials, and
a relay gets a proof for the address of the real station, not for its own.
Host names are left alone: they resolve on their own.

mDNS calls back only for records it has not cached, so an announcement the
station repeats starts no new flow. When the announced address gave no proof
reply, or the saved one still proved, HA checks the same announcement again
itself, at most MOVE_RECHECKS times, MOVE_RETRY_SECONDS apart. An announcement
inside that interval is checked when it ends. A newer announcement replaces the
pending check; a wrong proof plans none.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
from collections.abc import Callable, Coroutine
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback

from ._api_normalize import build_agent_base_url
from .config_flow_entry_update import async_update_reconfigured_entry
from .config_flow_identity import (
    entry_connection_matches_discovery,
    entry_identity_connection,
    entry_uses_manual_setup_unique_id,
)
from .const import CONF_AGENT_HOST, CONF_AGENT_PORT, CONF_AGENT_TOKEN, DOMAIN
from .discovery import discovery_matches_entry, discovery_model_conflicts
from .http_body import read_capped_body

_LOGGER = logging.getLogger(__name__)

PROOF_CONTEXT = "c300x-identity-v1"
MOVE_RETRY_SECONDS = 600.0
MOVE_RECHECKS = 2
_ATTEMPTS_KEY = f"{DOMAIN}_discovery_move_attempts"
_RECHECKS_KEY = f"{DOMAIN}_discovery_move_rechecks"
# Attempt outcomes. Only an unproven one (no proof reply from the announced
# address, or the saved address still proves) is checked again: a wrong proof
# may be a spoof.
_MOVED, _UNPROVEN, _THROTTLED, _REJECTED = "moved", "unproven", "throttled", "rejected"
_TIMEOUT = ClientTimeout(total=3.0)
_MAX_REPLY_BYTES = 4096
# The agent refuses proofs for shorter tokens: they could be guessed offline.
_MIN_TOKEN_LENGTH = 32
_PROOF = re.compile(r"[0-9a-f]{64}")
_RESOLVE_SECONDS = 5.0


def identity_proof(token: str, device_id: str, host: str, port: int, nonce: str) -> str:
    """Return the proof the agent computes for this identity and address."""
    message = f"{PROOF_CONTEXT}\n{device_id}\n{host}:{port}\n{nonce}"
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


async def async_follow_proven_move(
    flow: Any, discovered_unique_id: str | None, connection: dict[str, Any], *, model: str = "",
) -> bool:
    """Move the matching entry to the announced IPv4 endpoint once proven.

    The announcement replaces a pending re-check of the same entry. An entry
    whose agent reported the other model never follows it.
    """
    return await _async_check(flow, discovered_unique_id, connection, MOVE_RECHECKS, recheck=False, model=model)


def async_cancel_move_recheck(hass: Any, entry_id: str) -> None:
    """Drop the pending re-check of an entry that unloads or is removed."""
    rechecks: _Rechecks | None = hass.data.get(_RECHECKS_KEY)
    if rechecks is not None:
        rechecks.cancel(entry_id)


async def _async_check(
    flow: Any, discovered_unique_id: str | None, connection: dict[str, Any],
    rechecks_left: int, *, recheck: bool, model: str = "",
) -> bool:
    """Run one attempt; plan the next check of this announcement if it may help."""
    host = _routable_ipv4(connection.get(CONF_AGENT_HOST))
    if discovered_unique_id is None or host is None:
        return False
    entry = next((
        entry for entry in flow._async_current_entries()
        if discovery_matches_entry(discovered_unique_id, entry.unique_id)
    ), None)
    if entry is None or discovery_model_conflicts(entry, model):
        return False
    rechecks = _rechecks(flow.hass)
    ticket = rechecks.begin(entry.entry_id)
    port = int(connection[CONF_AGENT_PORT])
    outcome = await _async_attempt(flow, entry, host, port, recheck=recheck)
    if outcome == _UNPROVEN and rechecks_left > 0:
        delay, rechecks_left = MOVE_RETRY_SECONDS, rechecks_left - 1
    elif outcome == _THROTTLED:
        delay = _next_attempt_in(flow.hass, entry.entry_id)
    else:
        return outcome == _MOVED

    def check() -> Coroutine[Any, Any, bool]:
        return _async_check(flow, discovered_unique_id, connection, rechecks_left, recheck=True, model=model)

    if rechecks.schedule(entry.entry_id, ticket, delay, check):
        _LOGGER.debug(
            "%s: checking the announcement at %s:%s again in %.0f s",
            entry.title, host, port, delay,
        )
    return False


async def _async_attempt(flow: Any, entry: Any, host: str, port: int, *, recheck: bool) -> str:
    announced = {CONF_AGENT_HOST: host, CONF_AGENT_PORT: port}
    if (
        entry_uses_manual_setup_unique_id(entry)
        or entry_connection_matches_discovery(entry, announced)
    ):
        return _REJECTED
    saved, unique_id = entry_identity_connection(entry), entry.unique_id
    token = str(saved[CONF_AGENT_TOKEN] or "")
    old_host = _routable_ipv4(saved[CONF_AGENT_HOST])
    if old_host is None or len(token) < _MIN_TOKEN_LENGTH:
        return _REJECTED
    if not _start_attempt(flow.hass, entry.entry_id, recheck=recheck):
        return _THROTTLED
    old_port = int(saved[CONF_AGENT_PORT])
    old, new = f"{old_host}:{old_port}", f"{host}:{port}"
    if await _async_identity_proven(flow.hass, old_host, old_port, unique_id, token):
        _LOGGER.debug(
            "%s still proves its identity at %s; ignoring the announcement at %s",
            entry.title, old, new,
        )
        return _UNPROVEN
    proven = await _async_identity_proven(flow.hass, host, port, unique_id, token)
    if proven is None:
        _LOGGER.debug("%s: no identity proof from %s; keeping %s", entry.title, new, old)
        return _UNPROVEN
    if not proven:
        _LOGGER.warning(
            "%s: the station announced at %s did not prove the saved identity; keeping %s",
            entry.title, new, old,
        )
        return _REJECTED
    if (
        entry not in flow._async_current_entries() or entry.unique_id != unique_id
        or entry_identity_connection(entry) != saved
    ):
        return _REJECTED
    async_update_reconfigured_entry(flow, entry, announced, frozenset(announced))
    _LOGGER.info("%s moved from %s to %s (identity proven)", entry.title, old, new)
    return _MOVED


class _Rechecks:
    """At most one pending re-check per entry; only the newest check may plan one.

    A re-check keeps the ended flow as its handle to hass and the entries; the
    flow only reads entries and updates one, which works after it ended.
    """

    def __init__(self, hass: Any) -> None:
        self._hass = hass
        self._tickets: dict[str, object] = {}
        self._cancels: dict[str, Callable[[], None]] = {}
        self._listening = self._stopped = False

    def begin(self, entry_id: str) -> object:
        """Cancel what is pending for the entry and own its next re-check."""
        self.cancel(entry_id)
        ticket = self._tickets[entry_id] = object()
        return ticket

    def cancel(self, entry_id: str) -> None:
        """Cancel the pending re-check; a check still running plans none."""
        self._tickets.pop(entry_id, None)
        if (cancel := self._cancels.pop(entry_id, None)) is not None:
            cancel()

    def schedule(
        self, entry_id: str, ticket: object, delay: float,
        check: Callable[[], Coroutine[Any, Any, bool]],
    ) -> bool:
        """Plan the check unless a newer announcement, a cancel or HA stop came first."""
        from homeassistant.helpers.event import async_call_later

        if self._stopped or self._tickets.get(entry_id) is not ticket:
            return False

        @callback
        def fire(_now: Any) -> None:
            self._cancels.pop(entry_id, None)
            self._hass.async_create_background_task(
                check(), f"{DOMAIN} discovery move re-check {entry_id}", eager_start=True,
            )

        if not self._listening:
            self._listening = True
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_stop)
        self._cancels[entry_id] = async_call_later(self._hass, delay, fire)
        return True

    @callback
    def _async_stop(self, _event: Any) -> None:
        self._stopped = True
        for entry_id in list(self._tickets):
            self.cancel(entry_id)


def _rechecks(hass: Any) -> _Rechecks:
    rechecks: _Rechecks | None = hass.data.get(_RECHECKS_KEY)
    if rechecks is None:
        rechecks = hass.data[_RECHECKS_KEY] = _Rechecks(hass)
    return rechecks


def _routable_ipv4(value: Any) -> str | None:
    try:
        address = ipaddress.IPv4Address(str(value or "").strip())
    except ValueError:
        return None
    if address.is_loopback or address.is_unspecified or address.is_multicast:
        return None
    return str(address)


def _start_attempt(hass: Any, entry_id: str, *, recheck: bool) -> bool:
    """Allow one attempt per entry and interval; mDNS repeats announcements.

    A re-check is due by construction: it is planned no earlier than one
    interval after the last attempt, and every attempt before it cancels it.
    """
    attempts: dict[str, float] = hass.data.setdefault(_ATTEMPTS_KEY, {})
    now, last = monotonic(), attempts.get(entry_id)
    if not recheck and last is not None and now - last < MOVE_RETRY_SECONDS:
        return False
    attempts[entry_id] = now
    return True


def _next_attempt_in(hass: Any, entry_id: str) -> float:
    """Return the seconds until a throttled entry may be tried again."""
    last: float = hass.data[_ATTEMPTS_KEY][entry_id]
    return max(0.0, last + MOVE_RETRY_SECONDS - monotonic())


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


async def async_ipv4_addresses(host: str) -> list[str]:
    """The routable IPv4 addresses a saved host stands for, at most four.

    A proof binds the address the agent saw itself reached on, its IPv4
    address: a host name is resolved first. An IPv6 address, or a name
    without an IPv4 address, gives none.
    """
    host = str(host or "").strip()
    literal = _routable_ipv4(host)
    if literal is not None:
        return [literal]
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        return []
    try:
        async with asyncio.timeout(_RESOLVE_SECONDS):
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, None, family=socket.AF_INET, type=socket.SOCK_STREAM,
            )
    except (OSError, UnicodeError, TimeoutError):
        return []
    found: list[str] = []
    for *_, sockaddr in infos:
        address = _routable_ipv4(sockaddr[0])
        if address is not None and address not in found:
            found.append(address)
    return found[:4]


async def async_identity_proven(
    hass: Any, host: str, port: int, unique_id: str, token: str,
) -> bool | None:
    """Ask IPv4 host:port to prove the identity; None when it gave no proof reply.

    The request carries the nonce only, never the token.
    """
    return await _async_identity_proven(hass, host, port, unique_id, token)


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
