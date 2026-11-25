"""First-test bootstrap must not migrate Companion or assume an unknown model."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from test_config_flow_bootstrap_retry import _bootstrap_flow

from custom_components.bticino_c300x import config_flow


@pytest.mark.parametrize("model", ["C100X", "C300X", ""])
def test_postinstall_identity_controls_legacy_migration(monkeypatch, model):
    flow = _bootstrap_flow(monkeypatch, AsyncMock())
    # Model is learned after bootstrap, not guessed from the login default.
    assert not flow._setup_agent_info

    async def adopt(**_kwargs):
        flow._setup_agent_info = {"device": {"model": model}}

    flow._async_adopt_agent_unique_id = AsyncMock(side_effect=adopt)
    result = asyncio.run(flow.async_step_agent_missing({"bootstrap_install_agent": True}))
    assert result["step_id"] == "user_features"
    flow._async_adopt_agent_unique_id.assert_awaited_once()
    migrate = config_flow.async_migrate_legacy_mqtt_for_connection
    if model == "C300X":
        migrate.assert_awaited_once()
    else:
        migrate.assert_not_awaited()


def test_failed_postinstall_identity_never_migrates(monkeypatch):
    flow = _bootstrap_flow(monkeypatch, AsyncMock())
    flow._async_adopt_agent_unique_id = AsyncMock(side_effect=RuntimeError("identity unavailable"))
    with pytest.raises(RuntimeError, match="identity unavailable"):
        asyncio.run(flow.async_step_agent_missing({"bootstrap_install_agent": True}))
    config_flow.async_migrate_legacy_mqtt_for_connection.assert_not_awaited()
