"""Config-flow feature defaults and schemas for BTicino C300X."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from .config_audio import audio_gain_db_or_default
from .config_flow_dashboard import (
    DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT as _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
)
from .config_flow_dashboard import (
    DASHBOARD_PREVENT_RETURN_DEFAULT as _DASHBOARD_PREVENT_RETURN_DEFAULT,
)
from .config_flow_dashboard import (
    dashboard_entity_display_overrides as _dashboard_entity_display_overrides,
)
from .config_flow_dashboard import (
    dashboard_entity_ids as _dashboard_entity_ids,
)
from .config_flow_forms import actions_json as _actions_json
from .config_flow_forms import optional_suggested as _optional_suggested
from .config_schemas import (
    reconfigure_connection_schema as _reconfigure_connection_schema,
)
from .config_schemas import (
    reconfigure_features_schema as _reconfigure_features_schema,
)
from .const import (
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_UI_ENABLED,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_MAINTENANCE_TOKEN,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    DEFAULT_AGENT_PORT,
    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    DEVICE_ACTIVATION_MODE_AUTO,
)
from .entry_config import entry_config_value

CREATE_HOMEASSISTANT_USER_DEFAULT = True


def options_connection_schema(config_entry: config_entries.ConfigEntry) -> vol.Schema:
    """Return the first options page schema."""

    return vol.Schema(
        {
            vol.Required(
                CONF_AGENT_HOST,
                default=_config_default(config_entry, CONF_AGENT_HOST, ""),
            ): str,
            vol.Optional(
                CONF_AGENT_PORT,
                default=_config_default(
                    config_entry,
                    CONF_AGENT_PORT,
                    DEFAULT_AGENT_PORT,
                ),
            ): int,
            vol.Required(
                CONF_AGENT_TOKEN,
                default=_config_default(config_entry, CONF_AGENT_TOKEN, ""),
            ): str,
            vol.Optional(
                CONF_MAINTENANCE_TOKEN,
                default=_config_default(config_entry, CONF_MAINTENANCE_TOKEN, ""),
            ): str,
            _optional_suggested(
                CONF_CALLBACK_BASE_URL,
                _config_default(config_entry, CONF_CALLBACK_BASE_URL, ""),
            ): str,
        }
    )


def options_features_schema(
    config_entry: config_entries.ConfigEntry,
    *,
    video_enabled: bool | None = None,
    create_homeassistant_user: bool | None = None,
) -> vol.Schema:
    """Return the second options page schema."""

    default_video_enabled = (
        bool(_config_default(config_entry, CONF_VIDEO_ENABLED, False))
        if video_enabled is None
        else bool(video_enabled)
    )
    default_create_homeassistant_user = (
        _config_default(
            config_entry,
            CONF_CREATE_HOMEASSISTANT_USER,
            CREATE_HOMEASSISTANT_USER_DEFAULT,
        )
        if create_homeassistant_user is None
        else create_homeassistant_user
    )
    default_ring_capture_audio_gain_db = audio_gain_db_or_default(
        _config_default(
            config_entry,
            CONF_RING_CAPTURE_AUDIO_GAIN_DB,
            DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
        ),
        DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    )
    default_doorstation_audio_gain_db = audio_gain_db_or_default(
        _config_default(
            config_entry,
            CONF_DOORSTATION_AUDIO_GAIN_DB,
            DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
        ),
        DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    )
    return _reconfigure_features_schema(
        default_video_enabled,
        default_create_homeassistant_user=bool(default_create_homeassistant_user),
        default_doorstation_audio_gain_db=default_doorstation_audio_gain_db,
        default_ring_capture_audio_gain_db=default_ring_capture_audio_gain_db,
    )


def current_connection_options(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Return effective connection options for a restarted options flow."""

    return {
        CONF_AGENT_HOST: _config_default(config_entry, CONF_AGENT_HOST, ""),
        CONF_AGENT_PORT: int(
            _config_default(config_entry, CONF_AGENT_PORT, DEFAULT_AGENT_PORT)
        ),
        CONF_AGENT_TOKEN: _config_default(config_entry, CONF_AGENT_TOKEN, ""),
        CONF_MAINTENANCE_TOKEN: _config_default(
            config_entry,
            CONF_MAINTENANCE_TOKEN,
            "",
        ),
        CONF_CALLBACK_BASE_URL: _config_default(
            config_entry,
            CONF_CALLBACK_BASE_URL,
            "",
        ),
    }


def current_feature_options(
    config_entry: config_entries.ConfigEntry,
) -> dict[str, Any]:
    """Return effective feature options for reconfigure defaults."""

    return {
        CONF_ALARM_ENTITY_ID: _config_default(config_entry, CONF_ALARM_ENTITY_ID, ""),
        CONF_WEATHER_ENTITY_ID: _config_default(
            config_entry,
            CONF_WEATHER_ENTITY_ID,
            "",
        ),
        CONF_DASHBOARD_ENTITIES: _dashboard_entity_ids(
            _config_default(config_entry, CONF_DASHBOARD_ENTITIES, [])
        ),
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: _dashboard_entity_display_overrides(
            _config_default(config_entry, CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {})
        ),
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE: bool(
            _config_default(
                config_entry,
                CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
                _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
            )
        ),
        CONF_VIDEO_ENABLED: bool(
            _config_default(config_entry, CONF_VIDEO_ENABLED, False)
        ),
        CONF_VIDEO_PORT: int(
            _config_default(config_entry, CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)
        ),
        CONF_VIDEO_STREAM_PATH: _config_default(
            config_entry,
            CONF_VIDEO_STREAM_PATH,
            DEFAULT_VIDEO_STREAM_PATH,
        ),
        CONF_DOORSTATION_AUDIO_GAIN_DB: audio_gain_db_or_default(
            _config_default(
                config_entry,
                CONF_DOORSTATION_AUDIO_GAIN_DB,
                DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
            ),
            DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
        ),
        CONF_RING_CAPTURE_AUDIO_GAIN_DB: audio_gain_db_or_default(
            _config_default(
                config_entry,
                CONF_RING_CAPTURE_AUDIO_GAIN_DB,
                DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
            ),
            DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
        ),
        CONF_CREATE_HOMEASSISTANT_USER: bool(
            _config_default(
                config_entry,
                CONF_CREATE_HOMEASSISTANT_USER,
                CREATE_HOMEASSISTANT_USER_DEFAULT,
            )
        ),
        CONF_DEVICE_UI_ENABLED: bool(
            _config_default(config_entry, CONF_DEVICE_UI_ENABLED, False)
        ),
        CONF_ACTIONS: _config_default(config_entry, CONF_ACTIONS, {}),
        CONF_DASHBOARD_PREVENT_RETURN: bool(
            _config_default(
                config_entry,
                CONF_DASHBOARD_PREVENT_RETURN,
                _DASHBOARD_PREVENT_RETURN_DEFAULT,
            )
        ),
        CONF_DEVICE_ACTIVATION_MODE: _config_default(
            config_entry,
            CONF_DEVICE_ACTIVATION_MODE,
            DEVICE_ACTIVATION_MODE_AUTO,
        ),
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: _config_default(
            config_entry,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
            DEFAULT_STAIR_LIGHT_P,
        ),
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: _config_default(
            config_entry,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
            DEFAULT_STAIR_LIGHT_N,
        ),
        CONF_DEVICE_ACTIVATIONS: _config_default(
            config_entry,
            CONF_DEVICE_ACTIVATIONS,
            [],
        ),
    }


def reconfigure_connection_schema_from_current(
    config_entry: config_entries.ConfigEntry,
) -> vol.Schema:
    """Return the reconfigure connection schema using effective entry values."""

    current = current_connection_options(config_entry)
    return _reconfigure_connection_schema(
        current[CONF_AGENT_HOST],
        int(current[CONF_AGENT_PORT]),
        current[CONF_AGENT_TOKEN],
        current[CONF_MAINTENANCE_TOKEN],
        current[CONF_CALLBACK_BASE_URL],
    )


def reconfigure_features_schema_from_current(
    config_entry: config_entries.ConfigEntry,
) -> vol.Schema:
    """Return the reconfigure features schema using effective entry values."""

    current = current_feature_options(config_entry)
    return _reconfigure_features_schema(
        bool(current[CONF_VIDEO_ENABLED]),
        default_create_homeassistant_user=bool(current[CONF_CREATE_HOMEASSISTANT_USER]),
        default_doorstation_audio_gain_db=float(
            current[CONF_DOORSTATION_AUDIO_GAIN_DB]
        ),
        default_ring_capture_audio_gain_db=float(
            current[CONF_RING_CAPTURE_AUDIO_GAIN_DB]
        ),
    )


def feature_input_defaults(
    user_input: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Return feature input with hidden display fields preserved when absent."""

    data = dict(user_input)
    if CONF_CREATE_HOMEASSISTANT_USER not in data:
        media_was_enabled = bool(defaults.get(CONF_VIDEO_ENABLED, False))
        media_enabled = bool(data.get(CONF_VIDEO_ENABLED, media_was_enabled))
        data[CONF_CREATE_HOMEASSISTANT_USER] = (
            CREATE_HOMEASSISTANT_USER_DEFAULT
            if media_enabled and not media_was_enabled
            else defaults.get(
                CONF_CREATE_HOMEASSISTANT_USER,
                CREATE_HOMEASSISTANT_USER_DEFAULT,
            )
        )
    data.setdefault(
        CONF_DEVICE_ACTIVATION_MODE,
        defaults.get(CONF_DEVICE_ACTIVATION_MODE, DEVICE_ACTIVATION_MODE_AUTO),
    )
    data.setdefault(
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
        defaults.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_P),
    )
    data.setdefault(
        CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
        defaults.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, DEFAULT_STAIR_LIGHT_N),
    )
    data.setdefault(
        CONF_DEVICE_ACTIVATIONS,
        defaults.get(CONF_DEVICE_ACTIVATIONS, []),
    )
    data.setdefault(CONF_VIDEO_PORT, defaults.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT))
    data.setdefault(
        CONF_VIDEO_STREAM_PATH,
        defaults.get(CONF_VIDEO_STREAM_PATH, DEFAULT_VIDEO_STREAM_PATH),
    )
    data.setdefault(
        CONF_DOORSTATION_AUDIO_GAIN_DB,
        defaults.get(CONF_DOORSTATION_AUDIO_GAIN_DB, DEFAULT_DOORSTATION_AUDIO_GAIN_DB),
    )
    data.setdefault(
        CONF_RING_CAPTURE_AUDIO_GAIN_DB,
        defaults.get(
            CONF_RING_CAPTURE_AUDIO_GAIN_DB,
            DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
        ),
    )
    data.setdefault(
        CONF_DEVICE_UI_ENABLED,
        defaults.get(CONF_DEVICE_UI_ENABLED, False),
    )
    if not bool(data.get(CONF_DEVICE_UI_ENABLED, False)):
        return data
    data.setdefault(CONF_ALARM_ENTITY_ID, defaults[CONF_ALARM_ENTITY_ID])
    data.setdefault(CONF_ALARM_PAGE_ENTITY_ID, defaults.get(CONF_ALARM_PAGE_ENTITY_ID, ""))
    data.setdefault(CONF_WEATHER_ENTITY_ID, defaults[CONF_WEATHER_ENTITY_ID])
    data.setdefault(CONF_DASHBOARD_ENTITIES, defaults.get(CONF_DASHBOARD_ENTITIES, []))
    data.setdefault(
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
        defaults.get(
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
            _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
        ),
    )
    data.setdefault(
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
        defaults.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, {}),
    )
    data.setdefault(CONF_ACTIONS_JSON, _actions_json(defaults[CONF_ACTIONS]))
    data.setdefault(
        CONF_DASHBOARD_PREVENT_RETURN,
        defaults[CONF_DASHBOARD_PREVENT_RETURN],
    )
    return data


def _config_default(
    config_entry: config_entries.ConfigEntry,
    key: str,
    default: Any,
) -> Any:
    """Return an option override when present, otherwise setup data."""

    return entry_config_value(config_entry, key, default)
