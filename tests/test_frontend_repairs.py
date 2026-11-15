"""Frontend repair preserves stored dashboards across read failures."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x import repair_flows_frontend as frontend


@pytest.fixture
def dashboard(monkeypatch):
    hass = SimpleNamespace(
        config=SimpleNamespace(recovery_mode=False),
        bus=SimpleNamespace(async_fire=Mock()),
    )
    # Keep HA's load/save behavior; replace only its storage and lookup boundaries.
    dashboard = object.__new__(LovelaceStorage)
    dashboard.hass = hass
    dashboard.config = None
    dashboard._data = None
    dashboard._json_config = None
    dashboard._store = SimpleNamespace(async_load=AsyncMock(), async_save=AsyncMock())
    monkeypatch.setattr(frontend, "_resolve_doorbell_camera_entity_id", lambda *_: "camera.door")
    monkeypatch.setattr(frontend, "_storage_lovelace_dashboard", lambda *_: (None, dashboard))
    return dashboard


@pytest.mark.parametrize("error", [
    OSError("transient read failure"),
    RuntimeError("unexpected read failure"),
    HomeAssistantError("storage unavailable"),
    asyncio.CancelledError(),
])
def test_frontend_repair_read_failure_never_overwrites_existing_dashboard(dashboard, error):
    original = {"config": {"views": [{
        "path": "family", "title": "Family",
        "cards": [{"type": "entities", "entities": ["light.kitchen"]}],
    }]}}
    stored = deepcopy(original)
    dashboard._store.async_load.side_effect = [error, stored]
    expected = asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else frontend._LovelaceCardSetupError
    with pytest.raises(expected) as raised:
        asyncio.run(frontend._async_setup_lovelace_cards(dashboard.hass, SimpleNamespace()))
    if expected is frontend._LovelaceCardSetupError:
        assert raised.value.error_key == "lovelace_config_invalid"
        assert raised.value.__cause__ is error
    assert stored == original
    dashboard._store.async_load.assert_awaited_once()
    dashboard._store.async_save.assert_not_awaited()
    dashboard.hass.bus.async_fire.assert_not_called()


def test_frontend_repair_initializes_only_missing_config(dashboard):
    # LovelaceStorage raises ConfigNotFound for an absent stored configuration.
    dashboard._store.async_load.return_value = None
    result = asyncio.run(frontend._async_setup_lovelace_cards(dashboard.hass, SimpleNamespace()))
    assert result == "/lovelace/c300x"
    dashboard._store.async_save.assert_awaited_once()
    saved = dashboard._store.async_save.call_args.args[0]["config"]
    assert saved["views"][0]["sections"][0]["cards"][0]["entity"] == "camera.door"
