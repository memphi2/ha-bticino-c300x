"""Reusable config-flow schemas for BTicino C300X."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .activation_address import (
    normalize_stair_light_part,
)
from .config_audio import AUDIO_GAIN_DB_MAX, AUDIO_GAIN_DB_MIN, audio_gain_db
from .config_flow_forms import optional_suggested as _optional_suggested
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DEVICE_ACTIVATION_FLOW_ACTION,
    CONF_DEVICE_ACTIVATION_FLOW_TARGET,
    CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
    CONF_DEVICE_ACTIVATION_ITEM_ID,
    CONF_DEVICE_ACTIVATION_ITEM_NAME,
    CONF_DEVICE_ACTIVATION_ITEM_TYPE,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_MAINTENANCE_TOKEN,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_ROTATE_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_FLOW_ACTION_ADD,
    DEVICE_ACTIVATION_FLOW_ACTION_DONE,
    DEVICE_ACTIVATION_FLOW_ACTION_EDIT,
    DEVICE_ACTIVATION_FLOW_ACTION_REMOVE,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODES,
)
from .device_activations import DEVICE_ACTIVATION_TYPES

selector: Any
try:
    from homeassistant.helpers import selector as ha_selector

    selector = ha_selector
except (ImportError, ModuleNotFoundError):  # pragma: no cover - local test stubs
    selector = None

CREATE_HOMEASSISTANT_USER_DEFAULT = True


def setup_features_schema(
    default_video_enabled: bool,
    default_device_activation_mode: str = DEVICE_ACTIVATION_MODE_AUTO,
    default_device_activation_stair_light_p: str = DEFAULT_STAIR_LIGHT_P,
    default_device_activation_stair_light_n: str = DEFAULT_STAIR_LIGHT_N,
    *,
    default_create_homeassistant_user: bool = CREATE_HOMEASSISTANT_USER_DEFAULT,
    default_doorstation_audio_gain_db: float = DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    default_ring_capture_audio_gain_db: float = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
) -> vol.Schema:
    """Return the initial setup feature schema."""

    return _media_feature_schema(
        default_video_enabled=default_video_enabled,
        default_device_activation_mode=default_device_activation_mode,
        default_device_activation_stair_light_p=default_device_activation_stair_light_p,
        default_device_activation_stair_light_n=default_device_activation_stair_light_n,
        default_create_homeassistant_user=default_create_homeassistant_user,
        default_doorstation_audio_gain_db=default_doorstation_audio_gain_db,
        default_ring_capture_audio_gain_db=default_ring_capture_audio_gain_db,
    )


def reconfigure_connection_schema(
    default_agent_host: str,
    default_agent_port: int,
    default_agent_token: str,
    default_maintenance_token: str,
    default_callback_base_url: str,
) -> vol.Schema:
    """Return the reconfigure connection schema."""

    return vol.Schema(
        {
            vol.Required(CONF_AGENT_HOST, default=default_agent_host): str,
            vol.Optional(CONF_AGENT_PORT, default=default_agent_port): int,
            vol.Required(CONF_AGENT_TOKEN, default=default_agent_token): str,
            vol.Optional(
                CONF_MAINTENANCE_TOKEN,
                default=default_maintenance_token,
            ): str,
            _optional_suggested(
                CONF_CALLBACK_BASE_URL,
                default_callback_base_url,
            ): str,
            vol.Optional(CONF_ROTATE_SHARED_SECRET, default=False): bool,
        }
    )


def device_activation_manage_schema(items: list[dict[str, Any]]) -> vol.Schema:
    """Return the activation management action schema."""

    fields: dict[Any, Any] = {
        vol.Required(
            CONF_DEVICE_ACTIVATION_FLOW_ACTION,
            default=DEVICE_ACTIVATION_FLOW_ACTION_DONE,
        ): _device_activation_action_selector(has_items=bool(items)),
    }
    if items:
        fields[
            vol.Optional(
                CONF_DEVICE_ACTIVATION_FLOW_TARGET,
                default=str(items[0].get("id", "")),
            )
        ] = _device_activation_target_selector(items)
    return vol.Schema(fields)


def device_activation_item_schema(
    item: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the schema for one configured activation."""

    item = item or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_ACTIVATION_ITEM_ID,
                default=str(item.get("id") or ""),
            ): str,
            vol.Required(
                CONF_DEVICE_ACTIVATION_ITEM_NAME,
                default=str(item.get("name") or ""),
            ): str,
            vol.Required(
                CONF_DEVICE_ACTIVATION_ITEM_TYPE,
                default=str(item.get("type") or "lock"),
            ): _device_activation_type_selector(),
            vol.Required(
                CONF_DEVICE_ACTIVATION_ITEM_ADDRESS,
                default=str(item.get("address") or ""),
            ): str,
        }
    )


def reconfigure_features_schema(
    default_video_enabled: bool,
    default_device_activation_mode: str = DEVICE_ACTIVATION_MODE_AUTO,
    default_device_activation_stair_light_p: str = DEFAULT_STAIR_LIGHT_P,
    default_device_activation_stair_light_n: str = DEFAULT_STAIR_LIGHT_N,
    *,
    default_create_homeassistant_user: bool = CREATE_HOMEASSISTANT_USER_DEFAULT,
    default_doorstation_audio_gain_db: float = DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    default_ring_capture_audio_gain_db: float = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
) -> vol.Schema:
    """Return the reconfigure feature schema."""

    return _media_feature_schema(
        default_video_enabled=default_video_enabled,
        default_device_activation_mode=default_device_activation_mode,
        default_device_activation_stair_light_p=default_device_activation_stair_light_p,
        default_device_activation_stair_light_n=default_device_activation_stair_light_n,
        default_create_homeassistant_user=default_create_homeassistant_user,
        default_doorstation_audio_gain_db=default_doorstation_audio_gain_db,
        default_ring_capture_audio_gain_db=default_ring_capture_audio_gain_db,
    )


def stair_light_p(value: Any) -> str:
    """Validate the P value for the firmware stair light address."""

    return normalize_stair_light_part(value, default=DEFAULT_STAIR_LIGHT_P)


def stair_light_n(value: Any) -> str:
    """Validate the N value for the firmware stair light address."""

    return normalize_stair_light_part(value, default=DEFAULT_STAIR_LIGHT_N)


def audio_gain_db_selector() -> Any:
    """Return a bounded audio gain selector with a test-friendly fallback."""

    if selector is None:
        return audio_gain_db
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=AUDIO_GAIN_DB_MIN,
            max=AUDIO_GAIN_DB_MAX,
            step=0.5,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="dB",
        )
    )


def _device_activation_action_selector(*, has_items: bool) -> Any:
    options = [
        {"value": DEVICE_ACTIVATION_FLOW_ACTION_DONE, "label": "Done"},
        {"value": DEVICE_ACTIVATION_FLOW_ACTION_ADD, "label": "Add"},
    ]
    if has_items:
        options.extend(
            [
                {"value": DEVICE_ACTIVATION_FLOW_ACTION_EDIT, "label": "Edit"},
                {"value": DEVICE_ACTIVATION_FLOW_ACTION_REMOVE, "label": "Remove"},
            ]
        )
    if selector is None:
        return vol.In(tuple(option["value"] for option in options))
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _device_activation_target_selector(items: list[dict[str, Any]]) -> Any:
    options = [
        {
            "value": str(item.get("id") or ""),
            "label": f"{item.get('name') or item.get('id')} ({item.get('id')})",
        }
        for item in items
        if item.get("id")
    ]
    if selector is None:
        return vol.In(tuple(option["value"] for option in options))
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _device_activation_type_selector() -> Any:
    supported_types = tuple(
        item for item in DEVICE_ACTIVATION_TYPES if item in {"lock", "light", "stair_light"}
    )
    if selector is None:
        return vol.In(supported_types)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "lock", "label": "Door lock"},
                {"value": "light", "label": "Light"},
                {"value": "stair_light", "label": "Stair light"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _media_feature_schema(
    *,
    default_video_enabled: bool,
    default_device_activation_mode: str,
    default_device_activation_stair_light_p: str,
    default_device_activation_stair_light_n: str,
    default_create_homeassistant_user: bool,
    default_doorstation_audio_gain_db: float,
    default_ring_capture_audio_gain_db: float,
) -> vol.Schema:
    default_p = normalize_stair_light_part(
        default_device_activation_stair_light_p,
        default=DEFAULT_STAIR_LIGHT_P,
    )
    default_n = normalize_stair_light_part(
        default_device_activation_stair_light_n,
        default=DEFAULT_STAIR_LIGHT_N,
    )
    fields: dict[Any, Any] = {
        vol.Optional(CONF_VIDEO_ENABLED, default=default_video_enabled): bool,
    }
    if default_video_enabled:
        fields[
            vol.Optional(
                CONF_CREATE_HOMEASSISTANT_USER,
                default=default_create_homeassistant_user,
            )
        ] = bool
        fields[
            vol.Optional(
                CONF_DOORSTATION_AUDIO_GAIN_DB,
                default=default_doorstation_audio_gain_db,
            )
        ] = audio_gain_db_selector()
        fields[
            vol.Optional(
                CONF_RING_CAPTURE_AUDIO_GAIN_DB,
                default=default_ring_capture_audio_gain_db,
            )
        ] = audio_gain_db_selector()
    fields.update(
        {
            vol.Optional(
                CONF_DEVICE_ACTIVATION_MODE,
                default=default_device_activation_mode,
            ): vol.In(DEVICE_ACTIVATION_MODES),
            vol.Optional(
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
                default=default_p,
            ): str,
            vol.Optional(
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
                default=default_n,
            ): str,
        }
    )
    return vol.Schema(fields)
