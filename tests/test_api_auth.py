"""Credential failures must not become retryable network failures."""

import asyncio
import json

import pytest

from custom_components.bticino_c300x.api import (
    C300XAgentApi,
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
)
from custom_components.bticino_c300x.const import HEADER_MAINTENANCE_TOKEN
from tests.test_api import _FakeSession


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize(
    ("status", "body", "path", "maintenance"),
    [
        (401, '{"error":"secret-token"}', "/api/v1/capabilities", False),
        (401, "not json", "/api/v1/maintenance/ssh", False),
        (403, "not json", "/api/v1/capabilities", False),
        (403, '{"error":"maintenance_unauthorized"}', "/api/v1/maintenance/auth", True),
    ],
)
def test_auth_errors_are_typed_and_do_not_echo_response(binary, status, body, path, maintenance):
    api = C300XAgentApi(_FakeSession(body, response_status=status), "http://agent", "key")
    with pytest.raises(C300XAgentApiAuthError) as caught:
        asyncio.run(api._request_bytes("GET", path) if binary else api._request_json("GET", path))
    assert caught.value.maintenance is maintenance
    assert not isinstance(caught.value, C300XAgentApiConnectionError)
    assert "secret-token" not in str(caught.value)


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("binary", [False, True])
def test_oversized_auth_response_does_not_hide_rejection(status, binary):
    api = C300XAgentApi(_FakeSession(response_status=status, response_content_length=100_000_000), "http://agent", "key")
    with pytest.raises(C300XAgentApiAuthError):
        asyncio.run(api._request_bytes("GET", "/api/v1/state") if binary else api._request_json("GET", "/api/v1/state"))


def test_policy_denial_is_not_invalid_credentials():
    api = C300XAgentApi(_FakeSession('{"error":"loopback_required"}', response_status=403), "http://agent", "key")
    with pytest.raises(C300XAgentApiResponseError):
        asyncio.run(api._request_json("GET", "/api/v1/state"))


def test_maintenance_validation_omits_bearer():
    session = _FakeSession()
    api = C300XAgentApi(session, "http://agent", "access-secret", "admin-secret")
    asyncio.run(api.async_validate_maintenance_auth())
    assert session.requests[0]["kwargs"]["headers"] == {
        "Authorization": "", HEADER_MAINTENANCE_TOKEN: "admin-secret",
    }


@pytest.mark.parametrize(
    ("enabled", "allowed", "fingerprint", "accepted"),
    [(True, False, "", False), (False, True, "", False),
     (True, True, "", True), (False, False, "admin-only", True)],
)
def test_public_auth_status_does_not_validate_wrong_maintenance_key(enabled, allowed, fingerprint, accepted):
    session = _FakeSession(json.dumps({
        "noAuth": True, "maintenance_enabled": enabled,
        "maintenance_no_auth_allowed": allowed,
        "maintenance_token_fingerprint": fingerprint,
    }))
    api = C300XAgentApi(session, "http://agent", "", "admin")
    if accepted:
        asyncio.run(api.async_validate_maintenance_auth())
    else:
        with pytest.raises(C300XAgentApiAuthError) as caught:
            asyncio.run(api.async_validate_maintenance_auth())
        assert caught.value.maintenance
