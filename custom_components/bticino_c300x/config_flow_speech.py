"""The speech area of the settings: which text-to-speech engine the C300X speaks with.

The values are read when a notification is spoken, so saving them reloads nothing.
"""

from __future__ import annotations

from typing import Any, cast

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .capabilities import capability_is_supported
from .const import CONF_TTS_ENGINE, CONF_TTS_LANGUAGE, SPEECH_OPTION_KEYS
from .entry_config import speech_settings
from .notify_speech import engine_language
from .schema_compat import vol


def speech_offered(entry: Any) -> bool:
    """Offer the area where the agent can play sound."""

    capabilities = getattr(getattr(entry, "runtime_data", None), "capabilities", {})
    return capability_is_supported(capabilities, "announcements")


def _schema(engine: str | None, language: str | None) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_TTS_ENGINE, description={"suggested_value": engine}): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="tts"),
        ),
        vol.Optional(CONF_TTS_LANGUAGE, description={"suggested_value": language}): selector.LanguageSelector(),
    })


class SpeechOptionsStep:
    """The speech area of the settings menu."""

    async def async_step_speech(
        self: Any,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose the engine and language of spoken notifications."""

        entry = self._config_entry
        engine, language = speech_settings(entry)
        errors: dict[str, str] = {}
        if user_input is not None:
            engine = str(user_input.get(CONF_TTS_ENGINE) or "") or None
            language = str(user_input.get(CONF_TTS_LANGUAGE) or "") or None
            if engine is not None and (
                not engine.startswith("tts.") or self.hass.states.get(engine) is None
            ):
                errors[CONF_TTS_ENGINE] = "tts_engine_missing"
            elif language is not None and (spoken := engine_language(self.hass, engine, language)) is None:
                errors[CONF_TTS_LANGUAGE] = "tts_language_unsupported"
            else:
                # Saved as the engine names it.
                language = spoken if language is not None else None
                options = {key: value for key, value in entry.options.items() if key not in SPEECH_OPTION_KEYS}
                options.update({
                    key: value for key, value in zip(SPEECH_OPTION_KEYS, (engine, language), strict=True)
                    if value is not None
                })
                if options != dict(entry.options):
                    self.hass.config_entries.async_update_entry(entry, options=options)
                return cast(ConfigFlowResult, await self.async_step_init())
        return cast(ConfigFlowResult, self.async_show_form(
            step_id="speech", data_schema=_schema(engine, language), errors=errors,
        ))
