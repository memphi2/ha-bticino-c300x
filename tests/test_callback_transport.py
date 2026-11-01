"""Exercise explicit TLS opt-in without adding HTTP traffic or restart loops."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.bticino_c300x.api import (
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
    normalize_auth_config_status,
)
from custom_components.bticino_c300x.callback_transport import CallbackTransport


def _capabilities(*, active=False, configured=None, available=None):
    return {
        "https_callbacks_configurable": True,
        "https_callbacks_enabled": active,
        "https_callbacks_configured": active if configured is None else configured,
        "https_callbacks": active if available is None else available,
    }


def _transport(override="", capabilities=None):
    entry = SimpleNamespace(data={}, options={"callback_base_url": override})
    api = AsyncMock()
    return CallbackTransport(entry, api, capabilities or {}), api


@pytest.mark.parametrize("capabilities", [{}, _capabilities()])
@pytest.mark.parametrize("override", ["", "http://192.0.2.1:8123"])
def test_http_never_calls_transport_api(capabilities, override):
    transport, api = _transport(override, capabilities)
    for _ in range(3):
        assert not asyncio.run(transport.async_prepare("http://192.0.2.1/callback"))
    assert not api.mock_calls


def test_automatic_https_url_is_not_an_opt_in():
    transport, api = _transport(capabilities=_capabilities())
    with pytest.raises(C300XAgentApiError, match="explicit HTTPS"):
        asyncio.run(transport.async_prepare("https://ha.example.com/callback"))
    assert not api.mock_calls


def test_https_requires_an_opt_in_capable_agent():
    transport, api = _transport("https://ha.example.com")
    with pytest.raises(C300XAgentApiUnsupportedError, match="Update"):
        asyncio.run(transport.async_prepare("https://ha.example.com/callback"))
    assert not api.mock_calls


@pytest.mark.parametrize("enable", [False, True])
def test_mode_change_writes_and_restarts_once_then_stays_idle(enable):
    url = f"{'https' if enable else 'http'}://ha.example.com"
    transport, api = _transport(url, _capabilities(active=not enable))
    api.async_configure_callback_https.return_value = normalize_auth_config_status({
        "https_callbacks_configured": enable
    })
    api.async_validate_setup.return_value = {
        "capabilities": _capabilities(active=not enable, configured=enable)
    }
    for _ in range(2):
        with pytest.raises(C300XAgentApiError, match="awaiting agent restart"):
            asyncio.run(transport.async_prepare(url))
    api.async_configure_callback_https.assert_awaited_once_with(enable)
    api.async_restart_agent.assert_awaited_once_with(only_if_idle=True)
    api.async_validate_setup.return_value = {"capabilities": _capabilities(active=enable)}
    assert asyncio.run(transport.async_prepare(url))
    api.reset_mock()
    assert not asyncio.run(transport.async_prepare(url))
    assert not api.mock_calls


def test_busy_media_defers_restart_without_rewriting_config():
    transport, api = _transport("https://ha.example.com", _capabilities())
    api.async_configure_callback_https.return_value = {"https_callbacks_configured": True}
    api.async_restart_agent.side_effect = [C300XAgentApiError("media_session_active"), {}]
    api.async_validate_setup.return_value = {
        "capabilities": _capabilities(configured=True)
    }
    with pytest.raises(C300XAgentApiError, match="media_session_active"):
        asyncio.run(transport.async_prepare("https://ha.example.com"))
    with pytest.raises(C300XAgentApiError, match="awaiting agent restart"):
        asyncio.run(transport.async_prepare("https://ha.example.com"))
    api.async_configure_callback_https.assert_awaited_once_with(True)
    assert api.async_restart_agent.await_count == 2


def test_pending_opt_in_can_be_cancelled_without_restart():
    transport, api = _transport("", _capabilities(configured=True))
    api.async_configure_callback_https.return_value = {"https_callbacks_configured": False}
    assert asyncio.run(transport.async_prepare("http://192.0.2.1/callback"))
    api.async_configure_callback_https.assert_awaited_once_with(False)
    api.async_restart_agent.assert_not_awaited()


def test_clearing_override_disables_tls_even_if_ha_generates_https():
    transport, api = _transport("", _capabilities(active=True))
    api.async_configure_callback_https.return_value = normalize_auth_config_status(
        {"https_callbacks_configured": False}
    )
    with pytest.raises(C300XAgentApiError, match="awaiting agent restart"):
        asyncio.run(transport.async_prepare("https://ha.example.com/callback"))
    api.async_configure_callback_https.assert_awaited_once_with(False)
    api.async_restart_agent.assert_awaited_once_with(only_if_idle=True)
    api.async_validate_setup.return_value = {"capabilities": _capabilities()}
    with pytest.raises(C300XAgentApiError, match="explicit HTTPS"):
        asyncio.run(transport.async_prepare("https://ha.example.com/callback"))
    api.reset_mock()
    with pytest.raises(C300XAgentApiError, match="explicit HTTPS"):
        asyncio.run(transport.async_prepare("https://ha.example.com/callback"))
    assert not api.mock_calls


def test_enabled_but_unavailable_tls_never_restarts_or_falls_back():
    transport, api = _transport(
        "https://ha.example.com", _capabilities(active=True, available=False)
    )
    for _ in range(2):
        with pytest.raises(C300XAgentApiError, match="unavailable"):
            asyncio.run(transport.async_prepare("https://ha.example.com"))
    assert not api.mock_calls


def test_config_requires_confirmation_before_restart():
    transport, api = _transport("https://ha.example.com", _capabilities())
    api.async_configure_callback_https.return_value = {}
    with pytest.raises(C300XAgentApiError, match="did not confirm"):
        asyncio.run(transport.async_prepare("https://ha.example.com"))
    api.async_restart_agent.assert_not_awaited()


def test_already_enabled_https_needs_no_requests():
    transport, api = _transport("https://ha.example.com", _capabilities(active=True))
    assert not asyncio.run(transport.async_prepare("https://ha.example.com"))
    assert not api.mock_calls


def test_overlapping_registration_attempts_do_not_duplicate_mode_changes():
    async def scenario():
        transport, api = _transport("https://ha.example.com", _capabilities())

        async def configure(enabled):
            await asyncio.sleep(0)
            return normalize_auth_config_status({"https_callbacks_configured": enabled})

        api.async_configure_callback_https.side_effect = configure
        api.async_validate_setup.return_value = {
            "capabilities": _capabilities(configured=True)
        }
        results = await asyncio.gather(
            transport.async_prepare("https://ha.example.com"),
            transport.async_prepare("https://ha.example.com"),
            return_exceptions=True,
        )
        assert all(isinstance(result, C300XAgentApiError) for result in results)
        api.async_configure_callback_https.assert_awaited_once_with(True)
        api.async_restart_agent.assert_awaited_once_with(only_if_idle=True)

    asyncio.run(scenario())
