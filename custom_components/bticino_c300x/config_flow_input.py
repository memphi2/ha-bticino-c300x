"""Config-flow input validation helpers for BTicino C300X."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_NAME

from .action import ActionValidationError, parse_actions_json
from .callback_url import (
    validated_callback_base_url as _validated_callback_base_url,
)
from .camera_media.ha_compat import HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO
from .config_audio import audio_gain_db
from .config_flow_dashboard import (
    DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT as _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT,
)
from .config_flow_dashboard import (
    DASHBOARD_PREVENT_RETURN_DEFAULT as _DASHBOARD_PREVENT_RETURN_DEFAULT,
)
from .config_flow_dashboard import (
    alarm_page_entity_id as _alarm_page_entity_id,
)
from .config_flow_dashboard import (
    dashboard_entity_display_overrides as _dashboard_entity_display_overrides,
)
from .config_flow_dashboard import (
    dashboard_entity_ids as _dashboard_entity_ids,
)
from .config_flow_dashboard import (
    dashboard_pages as _dashboard_pages,
)
from .config_flow_forms import optional_suggested as _optional_suggested
from .config_flow_forms import password_selector as _password_selector
from .config_schemas import stair_light_n as _stair_light_n
from .config_schemas import stair_light_p as _stair_light_p
from .config_snapshots import SNAPSHOT_DEFAULTS, snapshot_values
from .const import (
    ALARM_DOMAIN,
    CONF_ACTIONS,
    CONF_ACTIONS_JSON,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_ALARM_ENTITY_ID,
    CONF_ALARM_PAGE_ENTITY_ID,
    CONF_BOOTSTRAP_INSTALL_AGENT,
    CONF_BOOTSTRAP_SSH_PASSWORD,
    CONF_BOOTSTRAP_SSH_USERNAME,
    CONF_CALLBACK_BASE_URL,
    CONF_CREATE_HOMEASSISTANT_USER,
    CONF_DASHBOARD_DYNAMIC_HOMEPAGE,
    CONF_DASHBOARD_ENTITIES,
    CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES,
    CONF_DASHBOARD_NAVIGATION,
    CONF_DASHBOARD_PAGES,
    CONF_DASHBOARD_PREVENT_RETURN,
    CONF_DASHBOARD_STATUS_PAGE_ENABLED,
    CONF_DEVICE_ACTIVATION_MODE,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N,
    CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P,
    CONF_DEVICE_ACTIVATIONS,
    CONF_DEVICE_UI_ENABLED,
    CONF_DOORSTATION_AUDIO_GAIN_DB,
    CONF_ENERGY_PAGE,
    CONF_MAINTENANCE_TOKEN,
    CONF_NATIVE_TWO_WAY_AUDIO,
    CONF_RING_CAPTURE_AUDIO_GAIN_DB,
    CONF_ROTATE_SHARED_SECRET,
    CONF_VIDEO_ENABLED,
    CONF_VIDEO_PORT,
    CONF_VIDEO_STREAM_PATH,
    CONF_WEATHER_ENTITY_ID,
    CONF_WEBRTC_ICE_POLICY,
    DEFAULT_AGENT_PORT,
    DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
    DEFAULT_NAME,
    DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
    DEFAULT_STAIR_LIGHT_N,
    DEFAULT_STAIR_LIGHT_P,
    DEFAULT_VIDEO_PORT,
    DEFAULT_VIDEO_STREAM_PATH,
    DEFAULT_WEBRTC_ICE_POLICY,
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODES,
    WEATHER_DOMAIN,
    WEBRTC_ICE_POLICIES,
)
from .dashboard_energy import normalize_energy_page
from .dashboard_optional_config import optional_page_values
from .dashboard_page_order import dashboard_navigation
from .device_activations import (
    DeviceActivationConfigError,
    normalize_device_activations,
)
from .schema_compat import vol
from .validation_patterns import ENTITY_OBJECT_ID_RE

_CREATE_HOMEASSISTANT_USER_DEFAULT = True


def _setup_connection_schema(
    default_name: str,
    default_agent_host: str,
    default_agent_port: int,
    default_callback_base_url: str = "",
) -> vol.Schema:
    """Return the initial setup schema before auth and feature choices."""

    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=default_name): str,
            vol.Required(CONF_AGENT_HOST, default=default_agent_host): str,
            vol.Optional(CONF_AGENT_PORT, default=default_agent_port): int,
            _optional_suggested(
                CONF_CALLBACK_BASE_URL,
                default_callback_base_url,
            ): str,
        }
    )


def _agent_missing_schema() -> vol.Schema:
    """Return the explicit agent-missing bootstrap choice schema."""

    return vol.Schema(
        {
            vol.Optional(CONF_BOOTSTRAP_INSTALL_AGENT, default=True): bool,
        }
    )


def _bootstrap_install_schema() -> vol.Schema:
    """Return the one-shot SSH bootstrap install schema."""

    return vol.Schema(
        {
            vol.Optional(CONF_BOOTSTRAP_SSH_USERNAME, default=""): str,
            vol.Optional(CONF_BOOTSTRAP_SSH_PASSWORD, default=""): _password_selector(),
        }
    )


def _agent_auth_schema(require_agent_token: bool) -> vol.Schema:
    """Return the agent token schema."""

    token_key = (
        vol.Required(CONF_AGENT_TOKEN, default="")
        if require_agent_token
        else vol.Optional(CONF_AGENT_TOKEN, default="")
    )
    return vol.Schema(
        {
            token_key: _password_selector(),
            vol.Optional(CONF_MAINTENANCE_TOKEN, default=""): _password_selector(),
        }
    )


def _device_activation_mode(value: Any) -> str:
    """Validate the configured C300X device activation address mode."""

    mode = str(value or DEVICE_ACTIVATION_MODE_AUTO).strip()
    if mode not in DEVICE_ACTIVATION_MODES:
        raise vol.Invalid("invalid device activation mode")
    return mode


def _alarm_entity_id(value: Any) -> str:
    """Validate an optional alarm-control-panel entity ID."""

    return _optional_domain_entity_id(
        value,
        domain=ALARM_DOMAIN,
        error="invalid alarm entity",
    )


def _weather_entity_id(value: Any) -> str:
    """Validate an optional weather entity ID."""

    return _optional_domain_entity_id(
        value,
        domain=WEATHER_DOMAIN,
        error="invalid weather entity",
    )


def _optional_domain_entity_id(value: Any, *, domain: str, error: str) -> str:
    """Validate an optional HA entity ID for one domain."""

    entity_id = str(value or "").strip().lower()
    if not entity_id:
        return ""
    if not entity_id.startswith(f"{domain}."):
        raise vol.Invalid(error)
    object_id = entity_id.removeprefix(f"{domain}.")
    if not ENTITY_OBJECT_ID_RE.fullmatch(object_id):
        raise vol.Invalid(error)
    return entity_id


def _non_empty_string(value: Any) -> str:
    """Validate non-empty setup strings."""

    text = str(value or "").strip()
    if not text:
        raise vol.Invalid("required")
    return text


def _agent_host(value: Any) -> str:
    """Validate the configured device-agent host."""

    host = str(value or "").strip()
    if not host or any(char.isspace() for char in host) or "/" in host:
        # Empty, or a URL: the form asks for the address only.
        raise vol.Invalid("invalid agent host")
    if ":" in host:
        # Only an IPv6 address has colons. "192.0.2.5:8091" would otherwise be
        # wrapped in brackets and probed as a host that cannot exist.
        try:
            ipaddress.IPv6Address(host.removeprefix("[").removesuffix("]").split("%", 1)[0])
        except ValueError as err:
            raise vol.Invalid("invalid agent host") from err
    return host


def _agent_port(user_input: dict[str, Any], errors: dict[str, str]) -> int:
    """Return the device-agent port, reporting one outside 1..65535."""

    try:
        port = int(user_input.get(CONF_AGENT_PORT, DEFAULT_AGENT_PORT))
    except (TypeError, ValueError, OverflowError):
        port = 0
    if not 1 <= port <= 65535:
        errors[CONF_AGENT_PORT] = "invalid_agent_port"
        return DEFAULT_AGENT_PORT
    return port


def _initial_connection_input(
    user_input: dict[str, Any],
    *,
    include_name: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the first setup page without asking for tokens."""

    errors: dict[str, str] = {}
    try:
        agent_host = _agent_host(user_input.get(CONF_AGENT_HOST, ""))
    except vol.Invalid:
        errors[CONF_AGENT_HOST] = "invalid_agent_host"
        agent_host = ""
    callback_base_url = _validated_callback_base_url(user_input, errors)

    data: dict[str, Any] = {
        CONF_AGENT_HOST: agent_host,
        CONF_AGENT_PORT: _agent_port(user_input, errors),
        CONF_CALLBACK_BASE_URL: callback_base_url,
    }
    if include_name:
        data[CONF_NAME] = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip()
    return data, errors


def _agent_auth_input(
    user_input: dict[str, Any],
    *,
    require_agent_token: bool,
    saved: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate setup auth values after the agent has been detected."""

    errors: dict[str, str] = {}
    agent_token = _key_or_saved(user_input, saved, CONF_AGENT_TOKEN)
    if require_agent_token and not agent_token:
        errors[CONF_AGENT_TOKEN] = "required"
    return (
        {
            CONF_AGENT_TOKEN: agent_token,
            CONF_MAINTENANCE_TOKEN: _key_or_saved(user_input, saved, CONF_MAINTENANCE_TOKEN),
        },
        errors,
    )


def _key_or_saved(
    user_input: Mapping[str, Any],
    saved: Mapping[str, Any] | None,
    key: str,
) -> str:
    """Return the entered key, or the saved one when the field is empty."""

    entered = str(user_input.get(key, "")).strip()
    if entered or saved is None:
        return entered
    return str(saved.get(key, "") or "").strip()


def _connection_input(
    user_input: dict[str, Any],
    *,
    include_name: bool = False,
    include_rotate: bool = False,
    saved: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate common connection page input.

    The forms of an existing entry do not show the saved keys. With ``saved``
    an empty key field keeps the saved key.
    """

    errors: dict[str, str] = {}
    try:
        agent_host = _agent_host(user_input.get(CONF_AGENT_HOST, ""))
    except vol.Invalid:
        errors[CONF_AGENT_HOST] = "invalid_agent_host"
        agent_host = ""
    agent_token = _key_or_saved(user_input, saved, CONF_AGENT_TOKEN)
    callback_base_url = _validated_callback_base_url(user_input, errors)

    data: dict[str, Any] = {
        CONF_AGENT_HOST: agent_host,
        CONF_AGENT_PORT: _agent_port(user_input, errors),
        CONF_AGENT_TOKEN: agent_token,
        CONF_MAINTENANCE_TOKEN: _key_or_saved(
            user_input, saved, CONF_MAINTENANCE_TOKEN
        ),
        CONF_CALLBACK_BASE_URL: callback_base_url,
    }
    if include_name:
        data[CONF_NAME] = str(user_input.get(CONF_NAME, DEFAULT_NAME)).strip()
    if include_rotate:
        data[CONF_ROTATE_SHARED_SECRET] = bool(
            user_input.get(CONF_ROTATE_SHARED_SECRET, False)
        )
    return data, errors


def _actions_json_errors(values: dict[str, Any]) -> dict[str, str]:
    """Return the form error for an action list that does not parse.

    The dashboard step checks its own field before the flow moves on. The
    final validation would report it too, but only after the pages and tiles
    forms, whose input is then lost.
    """

    try:
        parse_actions_json(values.get(CONF_ACTIONS_JSON, ""))
    except ActionValidationError:
        return {CONF_ACTIONS_JSON: "invalid_action_map"}
    return {}


def _device_activation_input(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> tuple[str, list[dict[str, Any]], str, str]:
    """Validate device activation fields and return mode/items/P/N."""

    try:
        mode = _device_activation_mode(
            user_input.get(CONF_DEVICE_ACTIVATION_MODE, DEVICE_ACTIVATION_MODE_AUTO)
        )
    except vol.Invalid:
        errors[CONF_DEVICE_ACTIVATION_MODE] = "invalid_device_activation_mode"
        mode = DEVICE_ACTIVATION_MODE_AUTO
    try:
        stair_light_p = _stair_light_p(
            user_input.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P, DEFAULT_STAIR_LIGHT_P)
        )
    except vol.Invalid:
        errors[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P] = "invalid_stair_light_part"
        stair_light_p = DEFAULT_STAIR_LIGHT_P
    try:
        stair_light_n = _stair_light_n(
            user_input.get(CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N, DEFAULT_STAIR_LIGHT_N)
        )
    except vol.Invalid:
        errors[CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N] = "invalid_stair_light_part"
        stair_light_n = DEFAULT_STAIR_LIGHT_N
    try:
        device_activations = normalize_device_activations(
            user_input.get(CONF_DEVICE_ACTIVATIONS, []),
            reserved_ids={"stair_light"},
        )
    except DeviceActivationConfigError:
        errors[CONF_DEVICE_ACTIVATIONS] = "invalid_device_activations"
        device_activations = []
    return mode, device_activations, stair_light_p, stair_light_n


def _dashboard_feature_input(
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> dict[str, Any]:
    """Validate optional C300X display dashboard feature fields."""

    device_ui_enabled = bool(user_input.get(CONF_DEVICE_UI_ENABLED, False))
    alarm_entity_id = ""
    alarm_page_entity_id = ""
    weather_entity_id = ""
    dashboard_entities: list[str] = []
    dashboard_pages: list[dict[str, Any]] = []
    dashboard_entity_display_overrides: dict[str, dict[str, str]] = {}
    dashboard_dynamic_homepage = _DASHBOARD_DYNAMIC_HOMEPAGE_DEFAULT
    actions: dict[str, dict[str, Any]] = {}
    # The alarm commands do not need the Display patch, so Alarmo is kept
    # with it off.
    try:
        alarm_entity_id = _alarm_entity_id(user_input.get(CONF_ALARM_ENTITY_ID, ""))
    except vol.Invalid:
        errors[CONF_ALARM_ENTITY_ID] = "invalid_alarm_entity"
    try:
        alarm_page_entity_id = _alarm_page_entity_id(
            user_input.get(CONF_ALARM_PAGE_ENTITY_ID, "")
        )
    except vol.Invalid:
        errors[CONF_ALARM_PAGE_ENTITY_ID] = "invalid_alarm_page_entity"
    if device_ui_enabled:
        try:
            actions = parse_actions_json(user_input.get(CONF_ACTIONS_JSON, ""))
        except ActionValidationError:
            errors[CONF_ACTIONS_JSON] = "invalid_action_map"
        try:
            weather_entity_id = _weather_entity_id(
                user_input.get(CONF_WEATHER_ENTITY_ID, "")
            )
        except vol.Invalid:
            errors[CONF_WEATHER_ENTITY_ID] = "invalid_weather_entity"
        try:
            dashboard_entities = _dashboard_entity_ids(
                user_input.get(CONF_DASHBOARD_ENTITIES, [])
            )
        except vol.Invalid:
            errors[CONF_DASHBOARD_ENTITIES] = "invalid_dashboard_entities"
        try:
            dashboard_pages = _dashboard_pages(user_input.get(CONF_DASHBOARD_PAGES, []))
        except vol.Invalid:
            errors["base"] = "invalid_dashboard_pages"
        try:
            dashboard_entity_display_overrides = _dashboard_entity_display_overrides(
                user_input.get(CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES, "")
            )
        except vol.Invalid:
            # Not a field of the form, where an error would not be shown.
            errors["base"] = "invalid_dashboard_entity_display_overrides"
        dashboard_dynamic_homepage = True
    return {
        CONF_ALARM_ENTITY_ID: alarm_entity_id,
        **optional_page_values(user_input if device_ui_enabled else {}),
        CONF_ALARM_PAGE_ENTITY_ID: alarm_page_entity_id,
        CONF_WEATHER_ENTITY_ID: weather_entity_id,
        CONF_DASHBOARD_ENTITIES: dashboard_entities,
        CONF_DASHBOARD_PAGES: dashboard_pages,
        CONF_DASHBOARD_NAVIGATION: dashboard_navigation(
            user_input.get(CONF_DASHBOARD_NAVIGATION) if device_ui_enabled else None
        ),
        CONF_DASHBOARD_STATUS_PAGE_ENABLED: user_input.get(
            CONF_DASHBOARD_STATUS_PAGE_ENABLED, True
        ) is True,
        CONF_ENERGY_PAGE: normalize_energy_page(
            user_input.get(CONF_ENERGY_PAGE) if device_ui_enabled else None
        ),
        CONF_DASHBOARD_DYNAMIC_HOMEPAGE: dashboard_dynamic_homepage,
        CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: dashboard_entity_display_overrides,
        CONF_ACTIONS: actions,
        CONF_DASHBOARD_PREVENT_RETURN: bool(
            user_input.get(
                CONF_DASHBOARD_PREVENT_RETURN,
                _DASHBOARD_PREVENT_RETURN_DEFAULT,
            )
            if device_ui_enabled
            else _DASHBOARD_PREVENT_RETURN_DEFAULT
        ),
        CONF_DEVICE_UI_ENABLED: device_ui_enabled,
    }


def _audio_feature_input(
    user_input: dict[str, Any],
    errors: dict[str, str],
    *,
    media_enabled: bool,
) -> tuple[float, float]:
    """Validate media audio feature fields."""

    if not media_enabled:
        return DEFAULT_DOORSTATION_AUDIO_GAIN_DB, DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB

    try:
        doorstation_audio_gain_db = audio_gain_db(
            user_input.get(
                CONF_DOORSTATION_AUDIO_GAIN_DB,
                DEFAULT_DOORSTATION_AUDIO_GAIN_DB,
            )
        )
    except vol.Invalid:
        errors[CONF_DOORSTATION_AUDIO_GAIN_DB] = "invalid_audio_gain"
        doorstation_audio_gain_db = DEFAULT_DOORSTATION_AUDIO_GAIN_DB
    try:
        ring_capture_audio_gain_db = audio_gain_db(
            user_input.get(
                CONF_RING_CAPTURE_AUDIO_GAIN_DB,
                DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB,
            )
        )
    except vol.Invalid:
        errors[CONF_RING_CAPTURE_AUDIO_GAIN_DB] = "invalid_audio_gain"
        ring_capture_audio_gain_db = DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
    return doorstation_audio_gain_db, ring_capture_audio_gain_db


def _webrtc_ice_policy_input(user_input: dict[str, Any]) -> str:
    """Return a validated WebRTC ICE policy from feature page input."""

    policy = str(
        user_input.get(CONF_WEBRTC_ICE_POLICY, DEFAULT_WEBRTC_ICE_POLICY)
        or DEFAULT_WEBRTC_ICE_POLICY
    ).strip()
    return policy if policy in WEBRTC_ICE_POLICIES else DEFAULT_WEBRTC_ICE_POLICY


def _feature_input(
    user_input: dict[str, Any],
    *,
    default_video_enabled: bool = False,
    default_create_homeassistant_user: bool = _CREATE_HOMEASSISTANT_USER_DEFAULT,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate common feature page input."""

    errors: dict[str, str] = {}
    try:
        snapshots = snapshot_values(user_input)
    except ValueError as err:
        errors[str(err)] = "invalid_snapshot_option"
        snapshots = dict(SNAPSHOT_DEFAULTS)
    dashboard = _dashboard_feature_input(user_input, errors)
    (
        device_activation_mode,
        device_activations,
        device_activation_stair_light_p,
        device_activation_stair_light_n,
    ) = _device_activation_input(user_input, errors)
    media_enabled = bool(user_input.get(CONF_VIDEO_ENABLED, default_video_enabled))
    doorstation_audio_gain_db, ring_capture_audio_gain_db = _audio_feature_input(
        user_input,
        errors,
        media_enabled=media_enabled,
    )
    return (
        {
            **snapshots,
            **optional_page_values(dashboard),
            CONF_ALARM_ENTITY_ID: dashboard[CONF_ALARM_ENTITY_ID],
            CONF_ALARM_PAGE_ENTITY_ID: dashboard[CONF_ALARM_PAGE_ENTITY_ID],
            CONF_WEATHER_ENTITY_ID: dashboard[CONF_WEATHER_ENTITY_ID],
            CONF_DASHBOARD_ENTITIES: dashboard[CONF_DASHBOARD_ENTITIES],
            CONF_DASHBOARD_PAGES: dashboard[CONF_DASHBOARD_PAGES],
            CONF_DASHBOARD_NAVIGATION: dashboard[CONF_DASHBOARD_NAVIGATION],
            CONF_ENERGY_PAGE: dashboard[CONF_ENERGY_PAGE],
            CONF_DASHBOARD_STATUS_PAGE_ENABLED: dashboard[CONF_DASHBOARD_STATUS_PAGE_ENABLED],
            CONF_DASHBOARD_DYNAMIC_HOMEPAGE: dashboard[CONF_DASHBOARD_DYNAMIC_HOMEPAGE],
            CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES: dashboard[
                CONF_DASHBOARD_ENTITY_DISPLAY_OVERRIDES
            ],
            CONF_ACTIONS: dashboard[CONF_ACTIONS],
            CONF_DASHBOARD_PREVENT_RETURN: dashboard[CONF_DASHBOARD_PREVENT_RETURN],
            CONF_DEVICE_ACTIVATION_MODE: device_activation_mode,
            CONF_DEVICE_ACTIVATIONS: device_activations,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_P: device_activation_stair_light_p,
            CONF_DEVICE_ACTIVATION_STAIR_LIGHT_N: device_activation_stair_light_n,
            CONF_VIDEO_ENABLED: media_enabled,
            CONF_NATIVE_TWO_WAY_AUDIO: (
                media_enabled
                and HA_SUPPORTS_NATIVE_CAMERA_TWO_WAY_AUDIO
                and user_input.get(CONF_NATIVE_TWO_WAY_AUDIO, False) is True
            ),
            CONF_CREATE_HOMEASSISTANT_USER: (
                bool(
                    user_input.get(
                        CONF_CREATE_HOMEASSISTANT_USER,
                        default_create_homeassistant_user,
                    )
                )
                if media_enabled
                else False
            ),
            CONF_DOORSTATION_AUDIO_GAIN_DB: (
                doorstation_audio_gain_db
                if media_enabled
                else DEFAULT_DOORSTATION_AUDIO_GAIN_DB
            ),
            CONF_RING_CAPTURE_AUDIO_GAIN_DB: (
                ring_capture_audio_gain_db
                if media_enabled
                else DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB
            ),
            CONF_WEBRTC_ICE_POLICY: (
                _webrtc_ice_policy_input(user_input)
                if media_enabled
                else DEFAULT_WEBRTC_ICE_POLICY
            ),
            CONF_VIDEO_PORT: int(user_input.get(CONF_VIDEO_PORT, DEFAULT_VIDEO_PORT)),
            CONF_VIDEO_STREAM_PATH: str(
                user_input.get(CONF_VIDEO_STREAM_PATH, DEFAULT_VIDEO_STREAM_PATH)
            ),
            CONF_DEVICE_UI_ENABLED: dashboard[CONF_DEVICE_UI_ENABLED],
        },
        errors,
    )
