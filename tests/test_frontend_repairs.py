"""Frontend repair preserves stored dashboards and their view layouts."""

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


@pytest.mark.parametrize("layout", [
    pytest.param({"cards": [{"type": "entities", "entities": ["light.kitchen"]}]}, id="default-masonry"),
    pytest.param({"type": "masonry", "cards": []}, id="explicit-masonry"),
    pytest.param({"type": "masonry", "sections": [{"type": "grid", "cards": []}]}, id="masonry-with-inert-sections"),
    pytest.param({"type": "sections"}, id="sections-missing-list"),
    pytest.param({"type": "sections", "sections": []}, id="sections-empty-list"),
    pytest.param({"type": "sections", "sections": [{"type": "grid", "cards": [
        {"type": "entities", "entities": ["light.kitchen"]},
    ]}]}, id="sections-existing-list"),
])
def test_frontend_repair_inserts_into_actual_view_layout_and_is_idempotent(dashboard, layout):
    view = {"path": "home", "title": "Home", **deepcopy(layout)}
    unrelated = {"path": "other", "cards": [{"type": "markdown", "content": "Keep"}]}
    config = {"views": [view, deepcopy(unrelated)]}
    dashboard._store.async_load.return_value = {"config": config}

    async def repair_twice():
        for _ in range(2):
            assert await frontend._async_setup_lovelace_cards(
                dashboard.hass, SimpleNamespace(), view_path="home",
            ) == "/lovelace/home"

    asyncio.run(repair_twice())
    if layout.get("type") == "sections":
        cards = view["sections"][0]["cards"]
        assert "cards" not in view
        before = layout.get("sections") or [{"cards": []}]
        original_cards = before[0]["cards"]
    else:
        cards = view["cards"]
        assert view.get("sections") == layout.get("sections")
        original_cards = layout.get("cards", [])
    assert cards[:-1] == original_cards
    assert cards[-1]["type"] == "custom:c300x-doorbell-call-card"
    assert cards[-1]["entity"] == "camera.door"
    assert view.get("type") == layout.get("type")
    assert config["views"][1] == unrelated
    dashboard._store.async_save.assert_awaited_once()


@pytest.mark.parametrize("view_type", [None, "masonry", "sections"])
def test_frontend_repair_preserves_existing_card_without_duplicates(dashboard, view_type):
    card = {"type": "custom:c300x-doorbell-call-card", "entity": "camera.door", "name": "My door"}
    view = {"path": "home", "title": "Home"}
    if view_type is not None:
        view["type"] = view_type
    if view_type == "sections":
        view["sections"] = [{"type": "grid", "cards": [card]}]
    else:
        view["cards"] = [card]
    config = {"views": [view]}
    original = deepcopy(config)
    dashboard._store.async_load.return_value = {"config": config}

    async def repair_twice():
        for _ in range(2):
            await frontend._async_setup_lovelace_cards(
                dashboard.hass, SimpleNamespace(), view_path="home",
            )

    asyncio.run(repair_twice())
    assert config == original
    dashboard._store.async_save.assert_not_awaited()


@pytest.mark.parametrize("sections", ["invalid", [None], [{"cards": "invalid"}]])
def test_frontend_repair_rejects_invalid_sections_instead_of_using_hidden_cards(sections):
    view = {"type": "sections", "sections": sections, "cards": []}
    original = deepcopy(view)
    with pytest.raises(frontend._LovelaceCardSetupError):
        frontend._cards_for_view(view)
    assert view == original
