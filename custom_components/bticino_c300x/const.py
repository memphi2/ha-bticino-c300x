"""Constants for the BTicino C300X integration."""

from __future__ import annotations

DOMAIN = "bticino_c300x"
DEFAULT_NAME = "BTicino C300X"

CONF_ACTIONS = "actions"
CONF_ACTIONS_JSON = "actions_json"
CONF_AGENT_TOKEN = "agent_token"
CONF_ALARM_ENTITY_ID = "alarm_entity_id"
CONF_AGENT_HOST = "agent_host"
CONF_AGENT_PORT = "agent_port"
CONF_BOOTSTRAP_INSTALL_AGENT = "bootstrap_install_agent"
CONF_BOOTSTRAP_SSH_PASSWORD = "bootstrap_ssh_password"
CONF_BOOTSTRAP_SSH_USERNAME = "bootstrap_ssh_username"
CONF_CALLBACK_BASE_URL = "callback_base_url"
CONF_CREATE_HOMEASSISTANT_USER = "create_homeassistant_user"
CONF_DASHBOARD_PREVENT_RETURN = "dashboard_prevent_return"
CONF_DASHBOARD_ENTITIES = "dashboard_entities"
CONF_DEVICE_ACTIVATION_MODE = "device_activation_mode"
CONF_DEVICE_ACTIVATION_STAIR_LIGHT_ADDRESS = (
    "device_activation_stair_light_address"
)
CONF_DEVICE_UI_ENABLED = "device_ui_enabled"
CONF_EVENT_WEBHOOK_ID = "event_webhook_id"
CONF_EVENT_WEBHOOK_TOKEN = "event_webhook_token"
CONF_FRONTEND_CARD_SETUP_DISMISSED = "frontend_card_setup_dismissed"
CONF_FRONTEND_CARD_SETUP_REPAIR_VERSION = "frontend_card_setup_repair_version"
CONF_MAINTENANCE_TOKEN = "maintenance_token"
CONF_ROTATE_SHARED_SECRET = "rotate_shared_secret"
CONF_SHARED_SECRET = "shared_secret"
CONF_VIDEO_ENABLED = "video_enabled"
CONF_DOORSTATION_AUDIO_GAIN_DB = "doorstation_audio_gain_db"
CONF_RING_CAPTURE_AUDIO_GAIN_DB = "ring_capture_audio_gain_db"
CONF_VIDEO_PORT = "video_port"
CONF_VIDEO_STREAM_PATH = "video_stream_path"
CONF_WEBHOOK_ID = "webhook_id"
CONF_WEATHER_ENTITY_ID = "weather_entity_id"

DEFAULT_AGENT_PORT = 8091
DEFAULT_EVENT_RESET_SECONDS = 30
DEFAULT_RECONNECT_GRACE_SECONDS = 15
MAX_HOME_CALL_DURATION_SECONDS = 3600
DEFAULT_STAIR_LIGHT_ADDRESS = "10"
DEFAULT_VIDEO_PORT = 6554
DEFAULT_VIDEO_STREAM_PATH = "/doorbell-video"
DEFAULT_DOORSTATION_AUDIO_GAIN_DB = 9.5
DEFAULT_RING_CAPTURE_AUDIO_GAIN_DB = 6.0
FRONTEND_CARD_SETUP_REPAIR_VERSION = "card-loader-v2"
STAIR_LIGHT_ADDRESS_PATTERN = r"^[0-9#]{1,16}$"
LOCK_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
ACTIVATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
DEVICE_ACTIVATION_MODE_AUTO = "automatic"
DEVICE_ACTIVATION_MODE_MANUAL = "manual"
DEVICE_ACTIVATION_MODES = (
    DEVICE_ACTIVATION_MODE_AUTO,
    DEVICE_ACTIVATION_MODE_MANUAL,
)
SMARTPHONE_FORWARDING_MODE_ENABLED = "enabled"
SMARTPHONE_FORWARDING_MODE_IN_HOUSE_ONLY = "in-house-only"
SMARTPHONE_FORWARDING_MODE_BLOCKED = "blocked"
SMARTPHONE_FORWARDING_MODES = (
    SMARTPHONE_FORWARDING_MODE_ENABLED,
    SMARTPHONE_FORWARDING_MODE_IN_HOUSE_ONLY,
    SMARTPHONE_FORWARDING_MODE_BLOCKED,
)

HEADER_SHARED_SECRET = "X-Bticino-C300X-Secret"
HEADER_EVENT_TOKEN = "X-Bticino-C300X-Event-Token"
HEADER_MAINTENANCE_TOKEN = "X-Bticino-C300X-Maintenance-Token"
EVENT_ACTION_RECEIVED = f"{DOMAIN}_action_received"
EVENT_AGENT_EVENT_RECEIVED = f"{DOMAIN}_agent_event_received"

DASHBOARD_ACTION_DOMAIN = "c300x"
DASHBOARD_ENTITY_ANSWERING_MACHINE = "answering_machine"
DASHBOARD_ENTITY_DOOR_UNLOCK = "door_unlock"
DASHBOARD_ENTITY_STAIR_LIGHT = "stair_light"
SIGNAL_CONNECTION_STATE_CHANGED = f"{DOMAIN}_connection_state_changed"
SIGNAL_SYSTEM_METRICS_CHANGED = f"{DOMAIN}_system_metrics_changed"
SIGNAL_VIDEO_MESSAGES_CHANGED = f"{DOMAIN}_video_messages_changed"
SIGNAL_MEMOS_CHANGED = f"{DOMAIN}_memos_changed"
SIGNAL_QML_PATCH_CHANGED = f"{DOMAIN}_qml_patch_changed"
SIGNAL_AGENT_DIAGNOSTICS_CHANGED = f"{DOMAIN}_agent_diagnostics_changed"
SIGNAL_AGENT_INFO_CHANGED = f"{DOMAIN}_agent_info_changed"
SIGNAL_AUTH_CONFIG_CHANGED = f"{DOMAIN}_auth_config_changed"
SIGNAL_MQTT_CHANGED = f"{DOMAIN}_mqtt_changed"

SERVICE_RUN_ACTION = "run_action"
SERVICE_RUN_DEVICE_ACTIVATION = "run_device_activation"
SERVICE_ALARM_COMMAND = "alarm_command"
SERVICE_UNLOCK_DOOR = "unlock_door"
SERVICE_STAIR_LIGHT = "stair_light"
SERVICE_ACTIVATE_DOORBELL_VIDEO = "activate_doorbell_video"
SERVICE_STOP_DOORBELL_VIDEO = "stop_doorbell_video"
SERVICE_ANSWER_DOORBELL_CALL = "answer_doorbell_call"
SERVICE_HANGUP_DOORBELL_CALL = "hangup_doorbell_call"
SERVICE_CAPTURE_DOORBELL_CALL = "capture_doorbell_call"
SERVICE_RUN_RING_WYOMING_ANALYSIS = "run_ring_wyoming_analysis"
SERVICE_EVALUATE_RING_ANALYSIS = "evaluate_ring_analysis"
SERVICE_START_HOME_CALL = "start_home_call"
SERVICE_STOP_HOME_CALL = "stop_home_call"
SERVICE_REBOOT = "reboot"
SERVICE_RELOAD_GUI = "reload_gui"
SERVICE_PLAY_LATEST_VIDEO_MESSAGE = "play_latest_video_message"
SERVICE_PLAY_LATEST_VOICE_MEMO = "play_latest_voice_memo"
SERVICE_WRITE_TEXT_MEMO = "write_text_memo"
SERVICE_DELETE_LATEST_VIDEO_MESSAGE = "delete_latest_video_message"
SERVICE_DELETE_LATEST_TEXT_MEMO = "delete_latest_text_memo"
SERVICE_DELETE_LATEST_VOICE_MEMO = "delete_latest_voice_memo"

ALARM_DOMAIN = "alarm_control_panel"
WEATHER_DOMAIN = "weather"
ALARM_COMMAND_TO_SERVICE = {
    "arm_away": "alarm_arm_away",
    "arm_home": "alarm_arm_home",
    "arm_night": "alarm_arm_night",
    "arm_custom_bypass": "alarm_arm_custom_bypass",
    "arm_vacation": "alarm_arm_vacation",
    "disarm": "alarm_disarm",
}
