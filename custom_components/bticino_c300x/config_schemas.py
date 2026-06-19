"""Reusable config-flow schemas for BTicino C300X."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from .activation_address import (
    normalize_stair_light_part,
    stair_light_parts_from_where,
)
from .config_audio import audio_gain_db
from .const import (
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
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
    DEFAULT_STAIR_LIGHT_ADDRESS,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODES,
)
from .validation_patterns import STAIR_LIGHT_ADDRESS_RE

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
    default_device_activation_stair_light_address: str = DEFAULT_STAIR_LIGHT_ADDRESS,
    *,
    default_create_homeassistant_user: bool = CREATE_HOMEASSISTANT_USER_DEFAULT,
    default_doorstation_audio_gain_db: float = DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    default_ring_capture_audio_gain_db: float = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
) -> vol.Schema:
    """Return the initial setup feature schema."""

    return _media_feature_schema(
        default_video_enabled=default_video_enabled,
        default_device_activation_mode=default_device_activation_mode,
        default_device_activation_stair_light_address=(
            default_device_activation_stair_light_address
        ),
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


def reconfigure_features_schema(
    default_video_enabled: bool,
    default_device_activation_mode: str = DEVICE_ACTIVATION_MODE_AUTO,
    default_device_activation_stair_light_address: str = DEFAULT_STAIR_LIGHT_ADDRESS,
    *,
    default_create_homeassistant_user: bool = CREATE_HOMEASSISTANT_USER_DEFAULT,
    default_doorstation_audio_gain_db: float = DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    default_ring_capture_audio_gain_db: float = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
) -> vol.Schema:
    """Return the reconfigure feature schema."""

    return _media_feature_schema(
        default_video_enabled=default_video_enabled,
        default_device_activation_mode=default_device_activation_mode,
        default_device_activation_stair_light_address=(
            default_device_activation_stair_light_address
        ),
        default_create_homeassistant_user=default_create_homeassistant_user,
        default_doorstation_audio_gain_db=default_doorstation_audio_gain_db,
        default_ring_capture_audio_gain_db=default_ring_capture_audio_gain_db,
    )


def stair_light_address(value: Any) -> str:
    """Validate the OpenWebNet address segment used by the stair light command."""

    address = str(value or "").strip()
    if not STAIR_LIGHT_ADDRESS_RE.fullmatch(address):
        raise vol.Invalid("invalid staircase light address")
    return address


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
            min=-12,
            max=12,
            step=0.5,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement="dB",
        )
    )


def _media_feature_schema(
    *,
    default_video_enabled: bool,
    default_device_activation_mode: str,
    default_device_activation_stair_light_address: str,
    default_create_homeassistant_user: bool,
    default_doorstation_audio_gain_db: float,
    default_ring_capture_audio_gain_db: float,
) -> vol.Schema:
    default_p, default_n = stair_light_parts_from_where(
        default_device_activation_stair_light_address
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
            ): stair_light_p,
            vol.Optional(
                CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
                default=default_n,
            ): stair_light_n,
        }
    )
    return vol.Schema(fields)


def _optional_suggested(key: str, suggested_value: Any) -> vol.Optional:
    """Return an optional form key that can be cleared by the user."""

    if suggested_value in (None, ""):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": suggested_value})
