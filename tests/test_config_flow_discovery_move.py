"""A known station follows a new address only after proving the saved identity.

mDNS is unauthenticated. Both the saved and the announced endpoint get a fresh
nonce and never a credential; an endpoint proves the station only with an
HMAC keyed by the saved access token over its identity and the address the
request reached it on.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from aiohttp import ClientConnectionError
from homeassistant.config_entries import UNDEFINED, ConfigEntryState
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import aiohttp_client

from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    HEADER_MAINTENANCE_TOKEN,
)

TOKEN = "saved-access-token-0123456789abcdefghij"
OTHER_TOKEN = "other-station-token-0123456789abcdefgh"
DEVICE_ID = "c300x-aabbcc001122"
OTHER_ID = "c300x-ddeeff334455"
OLD_HOST, OLD_PORT = "192.0.2.10", 8091
NEW_HOST, NEW_PORT = "192.0.2.20", 8092
OLD_PROOF_URL = f"http://{OLD_HOST}:{OLD_PORT}/api/v1/identity/proof"
NEW_PROOF_URL = f"http://{NEW_HOST}:{NEW_PORT}/api/v1/identity/proof"
BOTH = [f"POST {OLD_PROOF_URL}", f"POST {NEW_PROOF_URL}"]
UNRELATED_OPTION = "snapshot_retention"


def proof(nonce, *, token=TOKEN, device_id=DEVICE_ID, host=NEW_HOST, port=NEW_PORT):
    message = f"c300x-identity-v1\n{device_id}\n{host}:{port}\n{nonce}"
    return hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()


def valid_reply(nonce):
    return {"ok": True, "id": DEVICE_ID, "proof": proof(nonce)}


def _signed(nonce, **changes):
    return {"ok": True, "id": DEVICE_ID, "proof": proof(nonce), **changes}


def _old(**kwargs):
    """Reply of whatever now sits on the saved address, signed for that address."""
    def reply(nonce):
        device_id = kwargs.get("device_id", DEVICE_ID)
        return {"ok": True, "id": device_id, "proof": proof(nonce, host=OLD_HOST, port=OLD_PORT, **kwargs)}
    return reply


GONE = (0, ClientConnectionError("old address is gone"))
STILL_THERE = (200, _old())


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self._error = body if isinstance(body, Exception) else None
        raw = b"" if self._error else body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.content_length = None if self._error else len(raw)
        self.content = SimpleNamespace(iter_chunked=lambda _size: _chunks(raw))

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *_exc):
        return False


async def _chunks(raw):
    yield raw


class FakeSession:
    """Record every request; the station callback decides each answer."""

    def __init__(self, station) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._station = station

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, body = self._station(method, url, kwargs.get("json"))
        return FakeResponse(status, body)

    @property
    def urls(self):
        return [f"{method} {url}" for method, url, _ in self.calls]


def station(*, old=GONE, status=200, reply=valid_reply):
    """The saved address answers ``old``; the announced address answers ``reply``."""

    def answer(method, url, body):
        if method == "POST" and url == OLD_PROOF_URL:
            old_status, old_reply = old
            return old_status, old_reply(body["nonce"]) if callable(old_reply) else old_reply
        if method == "POST" and url == NEW_PROOF_URL:
            return status, reply(body["nonce"]) if callable(reply) else reply
        raise AssertionError(f"unexpected request {method} {url}")

    return answer


def make_entry(*, unique_id="c300xaabbcc001122", token=TOKEN, token_in_options=False, old_host=OLD_HOST):
    data = {
        CONF_AGENT_HOST: "192.0.2.5", CONF_AGENT_PORT: 8090,
        CONF_AGENT_TOKEN: "stale-data-token" if token_in_options else token,
        "video_enabled": True,
    }
    options = {CONF_AGENT_HOST: old_host, CONF_AGENT_PORT: OLD_PORT, UNRELATED_OPTION: 7}
    if token_in_options:
        options[CONF_AGENT_TOKEN] = token
    return SimpleNamespace(
        entry_id="entry-1", title="Door", unique_id=unique_id, source="zeroconf",
        state=ConfigEntryState.LOADED, update_listeners=[], runtime_data=None,
        data=data, options=options,
    )


def make_hass(entry):
    def update(entry=entry, **kwargs):
        changed = False
        for key, value in kwargs.items():
            if value is not UNDEFINED and getattr(entry, key) != value:
                setattr(entry, key, dict(value) if key in {"data", "options"} else value)
                changed = True
        return changed

    return SimpleNamespace(data={}, config_entries=SimpleNamespace(
        async_update_entry=Mock(side_effect=update),
        async_get_known_entry=lambda _: entry,
        async_entry_for_domain_unique_id=lambda *_: entry,
        async_schedule_reload=Mock(),
    ))


@pytest.fixture
def setup(monkeypatch):
    """Return (entry, hass, flow factory, session) wired to a fake station."""

    def build(answer, **entry_kwargs):
        entry = make_entry(**entry_kwargs)
        hass = make_hass(entry)
        session = FakeSession(answer)
        monkeypatch.setattr(aiohttp_client, "async_get_clientsession", lambda _hass: session)

        def new_flow():
            flow = BticinoC300XConfigFlow()
            flow.hass = hass
            flow.context = {"source": "zeroconf"}
            flow._async_in_progress = lambda **_: []
            flow._async_current_entries = lambda include_ignore=None: [entry]
            return flow

        return entry, hass, new_flow, session

    return build


def announce(flow, host=NEW_HOST, port=NEW_PORT, properties=None):
    info = SimpleNamespace(
        host=host, port=port, name="Door._bticino-c300x-agent._tcp.local.",
        properties={"id": DEVICE_ID} if properties is None else properties,
    )
    try:
        result = asyncio.run(flow.async_step_zeroconf(info))
    except AbortFlow as err:
        return err.reason
    assert result["type"] == "abort"
    return result["reason"]


def assert_unchanged(entry, hass, data, options):
    assert entry.data == data
    assert entry.options == options
    hass.config_entries.async_update_entry.assert_not_called()
    hass.config_entries.async_schedule_reload.assert_not_called()


def assert_moved(entry, hass):
    assert entry.data[CONF_AGENT_HOST] == NEW_HOST
    assert entry.data[CONF_AGENT_PORT] == NEW_PORT
    assert CONF_AGENT_HOST not in entry.options
    assert CONF_AGENT_PORT not in entry.options
    hass.config_entries.async_schedule_reload.assert_called_once_with("entry-1")


@pytest.mark.parametrize("token_in_options", [False, True])
def test_proven_move_updates_endpoint_clears_overrides_and_reloads(setup, caplog, token_in_options):
    caplog.set_level(logging.DEBUG)
    entry, hass, new_flow, session = setup(station(), token_in_options=token_in_options)

    assert announce(new_flow()) == "already_configured"

    assert session.urls == BOTH
    assert_moved(entry, hass)
    assert entry.options[UNRELATED_OPTION] == 7
    if token_in_options:
        assert entry.options[CONF_AGENT_TOKEN] == TOKEN
    assert entry.unique_id == "c300xaabbcc001122"
    assert f"moved from {OLD_HOST}:{OLD_PORT} to {NEW_HOST}:{NEW_PORT} (identity proven)" in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("valid", [True, False])
def test_no_endpoint_ever_receives_the_token(setup, valid):
    reply = valid_reply if valid else (lambda nonce: {"ok": True, "id": DEVICE_ID, "proof": "0" * 64})
    entry, _hass, new_flow, session = setup(station(reply=reply))

    announce(new_flow())

    assert entry.data[CONF_AGENT_HOST] == (NEW_HOST if valid else "192.0.2.5")
    assert session.urls == BOTH
    for _method, url, kwargs in session.calls:
        headers = {str(key).lower() for key in (kwargs.get("headers") or {})}
        assert "authorization" not in headers
        assert HEADER_MAINTENANCE_TOKEN.lower() not in headers
        assert TOKEN not in url
        assert TOKEN not in repr(kwargs)
        assert kwargs.get("allow_redirects") is False
        assert set(kwargs["json"]) == {"nonce"}
        assert re.fullmatch(r"[0-9a-f]{64}", kwargs["json"]["nonce"])
    assert session.calls[0][2]["json"] != session.calls[1][2]["json"]


@pytest.mark.parametrize("status,reply", [
    (200, lambda n: _signed(n, proof=proof(n, token="another-token-0123456789abcdefghijkl"))),
    (200, lambda n: _signed(n, id=OTHER_ID, proof=proof(n, device_id=OTHER_ID))),
    (200, lambda n: _signed(n, proof=proof(n).upper())),
    (200, lambda n: _signed(n, proof=proof(n)[:-1])),
    (200, lambda n: _signed(n, proof=proof("f" * 64))),
    (200, lambda n: _signed(n, ok=False)),
    (200, lambda n: _signed(n, ok="true")),
    (200, lambda n: {"ok": True, "proof": proof(n)}),
    (200, lambda n: {"ok": True, "id": DEVICE_ID}),
    (200, lambda n: {"id": DEVICE_ID, "proof": proof(n)}),
    (200, lambda n: _signed(n, id=["c300x-aabbcc001122"])),
    (200, lambda n: [valid_reply(n)]),
    (200, b"not json"),
    (500, valid_reply),
    (201, valid_reply),
    (401, {"ok": False, "error": "unauthorized"}),
    (404, {"ok": False, "error": "identity_proof_unavailable"}),
    (404, b"Not Found"),
    (400, {"ok": False, "error": "invalid_nonce"}),
    (0, ClientConnectionError("refused")),
    (0, TimeoutError()),
])
def test_unproven_replies_keep_the_entry(setup, status, reply):
    entry, hass, new_flow, session = setup(station(status=status, reply=reply))
    data, options = dict(entry.data), dict(entry.options)

    assert announce(new_flow()) == "already_configured"

    assert session.urls == BOTH
    assert_unchanged(entry, hass, data, options)


@pytest.mark.parametrize("host,port", [("192.0.2.30", NEW_PORT), (NEW_HOST, 8091), ("192.0.2.30", 8091)])
def test_relayed_proof_for_another_address_keeps_the_entry(setup, host, port):
    entry, hass, new_flow, session = setup(station(reply=lambda n: _signed(n, proof=proof(n, host=host, port=port))))
    data, options = dict(entry.data), dict(entry.options)

    assert announce(new_flow()) == "already_configured"

    assert session.urls == BOTH
    assert_unchanged(entry, hass, data, options)


def test_old_endpoint_still_proving_the_identity_is_not_moved(setup):
    entry, hass, new_flow, session = setup(station(old=STILL_THERE))
    data, options = dict(entry.data), dict(entry.options)

    assert announce(new_flow()) == "already_configured"

    assert session.urls == [f"POST {OLD_PROOF_URL}"]
    assert_unchanged(entry, hass, data, options)


@pytest.mark.parametrize("old", [
    pytest.param((200, _old(device_id=OTHER_ID, token=OTHER_TOKEN)), id="swapped-station"),
    pytest.param((200, _old(device_id=OTHER_ID)), id="other-id"),
    pytest.param((200, _old(token=OTHER_TOKEN)), id="other-token"),
    pytest.param((200, lambda n: _signed(n)), id="proof-for-announced-address"),
    pytest.param((200, {"ok": True, "agent": "native-c", "version": "2.8.0"}), id="health-only"),
    pytest.param((404, {"ok": False, "error": "identity_proof_unavailable"}), id="no-route"),
    pytest.param((401, {"ok": False, "error": "unauthorized"}), id="old-agent-401"),
    pytest.param((0, TimeoutError()), id="timeout"),
    pytest.param(GONE, id="gone"),
])
def test_old_address_without_the_saved_identity_counts_as_gone(setup, old):
    entry, hass, new_flow, session = setup(station(old=old))

    assert announce(new_flow()) == "already_configured"

    assert session.urls == BOTH
    assert_moved(entry, hass)


@pytest.mark.parametrize("old_host", ["c300x.local", "door.example", "2001:db8::10", "[2001:db8::10]", "127.0.0.1"])
def test_entry_without_ipv4_literal_is_not_moved(setup, old_host):
    entry, hass, new_flow, session = setup(station(), old_host=old_host)
    data, options = dict(entry.data), dict(entry.options)

    announce(new_flow())

    assert session.calls == []
    assert_unchanged(entry, hass, data, options)


@pytest.mark.parametrize("host", ["2001:db8::20", "fe80::1", "c300x.local", "127.0.0.1", "0.0.0.0", "224.0.0.251"])
def test_non_ipv4_or_unroutable_announcement_is_not_followed(setup, host):
    entry, hass, new_flow, session = setup(station())
    data, options = dict(entry.data), dict(entry.options)

    assert announce(new_flow(), host=host) == "already_configured"

    assert session.calls == []
    assert_unchanged(entry, hass, data, options)


@pytest.mark.parametrize("unique_id,properties,token", [
    ("c300xaabbcc001122", {}, TOKEN),
    ("bticino_c300x", {"id": "bticino_c300x"}, TOKEN),
    ("bticino_c300x:192.0.2.10:8091", {"id": "bticino_c300x:192.0.2.10:8091"}, TOKEN),
    (None, {"id": DEVICE_ID}, TOKEN),
    ("c300xddeeff334455", {"id": DEVICE_ID}, TOKEN),
    ("c300xaabbcc001122", {"id": DEVICE_ID}, ""),
    ("c300xaabbcc001122", {"id": DEVICE_ID}, "short-token"),
])
def test_entry_without_discovered_identity_or_key_is_not_moved(setup, unique_id, properties, token):
    entry, hass, new_flow, session = setup(station(), unique_id=unique_id, token=token)
    data, options = dict(entry.data), dict(entry.options)

    announce(new_flow(), properties=properties)

    assert session.calls == []
    assert_unchanged(entry, hass, data, options)


def test_same_endpoint_announcement_makes_no_request(setup):
    entry, hass, new_flow, session = setup(station())
    data, options = dict(entry.data), dict(entry.options)

    assert announce(new_flow(), host=OLD_HOST, port=OLD_PORT) == "already_configured"

    assert session.calls == []
    assert_unchanged(entry, hass, data, options)


@pytest.mark.parametrize("change", ["endpoint", "token", "identity", "removed"])
def test_entry_change_during_the_proof_is_not_overwritten(setup, change):
    entries: list[Any] = []

    def reply(nonce):
        entry = entries[0]
        if change == "endpoint":
            entry.options[CONF_AGENT_HOST] = "192.0.2.99"
        elif change == "token":
            entry.options[CONF_AGENT_TOKEN] = "rotated-token-0123456789abcdefghijklm"
        elif change == "identity":
            entry.unique_id = "c300xddeeff334455"
        else:
            entries.clear()
        return valid_reply(nonce)

    entry, hass, new_flow, session = setup(station(reply=reply))
    entries.append(entry)
    flow = new_flow()
    flow._async_current_entries = lambda include_ignore=None: list(entries)

    announce(flow)

    assert session.urls == BOTH
    assert entry.data[CONF_AGENT_HOST] == "192.0.2.5"
    hass.config_entries.async_update_entry.assert_not_called()
    hass.config_entries.async_schedule_reload.assert_not_called()


def test_repeated_announcements_are_throttled_per_entry(setup, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.discovery_move.monotonic", lambda: now[0],
    )
    entry, hass, new_flow, session = setup(station(old=STILL_THERE))
    data, options = dict(entry.data), dict(entry.options)

    announce(new_flow())
    assert session.urls == [f"POST {OLD_PROOF_URL}"]

    now[0] += 599
    announce(new_flow())
    assert len(session.calls) == 1

    now[0] += 2
    announce(new_flow())
    assert session.urls == [f"POST {OLD_PROOF_URL}", f"POST {OLD_PROOF_URL}"]
    assert_unchanged(entry, hass, data, options)


def test_every_request_sends_a_fresh_nonce(setup, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(
        "custom_components.bticino_c300x.discovery_move.monotonic", lambda: now[0],
    )
    entry, _hass, new_flow, session = setup(station(reply=lambda n: _signed(n, proof="0" * 64)))

    announce(new_flow())
    now[0] += 601
    announce(new_flow())

    assert session.urls == BOTH + BOTH
    nonces = {kwargs["json"]["nonce"] for _, _, kwargs in session.calls}
    assert len(nonces) == 4
    assert entry.data[CONF_AGENT_HOST] == "192.0.2.5"
