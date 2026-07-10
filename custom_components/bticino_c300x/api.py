"""Async client for the C300X device-agent HTTP API."""

from __future__ import annotations

from ._api_content import _ApiContentMixin
from ._api_device import _ApiDeviceMixin
from ._api_maintenance import _ApiMaintenanceMixin
from ._api_media import _ApiMediaMixin
from ._api_normalize import (
    build_agent_base_url as build_agent_base_url,
)
from ._api_normalize import (
    display_bridge_callback_fingerprint as display_bridge_callback_fingerprint,
)
from ._api_normalize import (
    normalize_activations as normalize_activations,
)
from ._api_normalize import (
    normalize_agent_diagnostics as normalize_agent_diagnostics,
)
from ._api_normalize import (
    normalize_answering_machine as normalize_answering_machine,
)
from ._api_normalize import (
    normalize_answering_machine_messages as normalize_answering_machine_messages,
)
from ._api_normalize import (
    normalize_auth_config_status as normalize_auth_config_status,
)
from ._api_normalize import (
    normalize_device_user_status as normalize_device_user_status,
)
from ._api_normalize import (
    normalize_doorbell_call as normalize_doorbell_call,
)
from ._api_normalize import (
    normalize_doorbell_video as normalize_doorbell_video,
)
from ._api_normalize import (
    normalize_firewall_status as normalize_firewall_status,
)
from ._api_normalize import (
    normalize_home_call as normalize_home_call,
)
from ._api_normalize import (
    normalize_legacy_mqtt_status as normalize_legacy_mqtt_status,
)
from ._api_normalize import (
    normalize_memos as normalize_memos,
)
from ._api_normalize import (
    normalize_mqtt_status as normalize_mqtt_status,
)
from ._api_normalize import (
    normalize_qml_patch_status as normalize_qml_patch_status,
)
from ._api_normalize import (
    normalize_ringer as normalize_ringer,
)
from ._api_normalize import (
    normalize_self_test as normalize_self_test,
)
from ._api_normalize import (
    normalize_smartphone_forwarding as normalize_smartphone_forwarding,
)
from ._api_normalize import (
    normalize_smartphone_forwarding_mode as normalize_smartphone_forwarding_mode,
)
from ._api_normalize import (
    normalize_ssh_status as normalize_ssh_status,
)
from ._api_normalize import (
    normalize_system_metrics as normalize_system_metrics,
)
from .api_errors import (
    C300XAgentApiConnectionError as C300XAgentApiConnectionError,
)
from .api_errors import (
    C300XAgentApiError as C300XAgentApiError,
)
from .api_errors import (
    C300XAgentApiResponseError as C300XAgentApiResponseError,
)
from .api_errors import (
    C300XAgentApiUnsupportedError as C300XAgentApiUnsupportedError,
)
from .api_validation import (
    normalize_activation_id as normalize_activation_id,
)
from .api_validation import (
    normalize_lock_id as normalize_lock_id,
)
from .api_validation import (
    normalize_memo_id as normalize_memo_id,
)
from .api_validation import (
    normalize_stair_light_address as normalize_stair_light_address,
)
from .api_validation import (
    normalize_text_memo_text as normalize_text_memo_text,
)
from .api_validation import (
    normalize_video_message_id as normalize_video_message_id,
)


class C300XAgentApi(
    _ApiMediaMixin,
    _ApiMaintenanceMixin,
    _ApiDeviceMixin,
    _ApiContentMixin,
):
    """Small async client for the C300X device agent API."""
