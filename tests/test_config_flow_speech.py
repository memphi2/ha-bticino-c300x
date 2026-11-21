"""The speech area of the settings: engine and language of spoken notifications."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from custom_components.bticino_c300x.const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.entry_config import speech_settings
from custom_components.bticino_c300x.runtime_manager import _entry_update_listener
from tests.test_config_flow_helpers import _options_flow, _options_menu_of


def _entry(*, announcements: bool = True, options: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        data={CONF_AGENT_HOST: "agent.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "token",
              CONF_VIDEO_ENABLED: True},
        options=dict(options or {}),
        runtime_data=SimpleNamespace(capabilities={"announcements": {"supported": announcements}}),
    )


def _open(entry: SimpleNamespace, user_input: dict[str, Any] | None = None) -> dict[str, Any]:
    flow = _options_flow(entry)
    flow.hass.states = SimpleNamespace(get=lambda entity_id: object() if entity_id == "tts.piper" else None)
    flow.async_show_menu = lambda **kwargs: {"type": "menu", **kwargs}  # type: ignore[method-assign]
    return asyncio.run(flow.async_step_speech(user_input))


def test_the_area_is_offered_only_where_the_device_can_speak() -> None:
    assert "speech" in _options_menu_of(_entry())
    assert "speech" not in _options_menu_of(_entry(announcements=False))


def test_the_form_starts_from_the_saved_engine_and_language() -> None:
    form = _open(_entry(options={"tts_engine": "tts.piper", "tts_language": "de"}))

    assert form["step_id"] == "speech" and form["errors"] == {}
    suggested = {str(key): key.description["suggested_value"] for key in form["data_schema"].schema}
    assert suggested == {"tts_engine": "tts.piper", "tts_language": "de"}


def test_saving_keeps_the_other_settings_and_empty_fields_clear_the_choice() -> None:
    entry = _entry(options={"snapshot_width": 640})

    result = _open(entry, {"tts_engine": "tts.piper", "tts_language": "de"})
    assert (result["type"], result["step_id"]) == ("menu", "init")
    assert entry.options == {"snapshot_width": 640, "tts_engine": "tts.piper", "tts_language": "de"}
    assert speech_settings(entry) == ("tts.piper", "de")

    _open(entry, {})
    assert entry.options == {"snapshot_width": 640}
    assert speech_settings(entry) == (None, None)


def test_an_engine_that_does_not_exist_is_refused() -> None:
    entry = _entry()

    for engine in ("tts.gone", "media_player.kitchen"):
        form = _open(entry, {"tts_engine": engine})
        assert form["errors"] == {"tts_engine": "tts_engine_missing"}
    assert entry.options == {}


def test_changing_the_speech_settings_does_not_reload_the_integration(monkeypatch: Any) -> None:
    from custom_components.bticino_c300x import runtime_manager

    reloads: list[Any] = []

    async def reload(_hass: Any, updated: Any) -> None:
        reloads.append(updated)

    async def no_reapply(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(runtime_manager, "_async_update_listener", reload)
    monkeypatch.setattr(runtime_manager, "_async_reapply_display_patch_for_home_page", no_reapply)
    entry = _entry()
    listener = _entry_update_listener(entry)  # type: ignore[arg-type]

    entry.options = {"tts_engine": "tts.piper", "tts_language": "de"}
    asyncio.run(listener(None, entry))  # type: ignore[arg-type]
    assert reloads == []
    entry.options = {**entry.options, "snapshot_width": 640}
    asyncio.run(listener(None, entry))  # type: ignore[arg-type]
    assert reloads == [entry]
