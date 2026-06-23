"""Async client for the C300X device-agent HTTP API."""

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession

from .agent_contracts import (
    AgentDiagnosticsStatus,
    AuthConfigStatus,
    CapabilityPayload,
    DoorbellVideoStatus,
    FirewallStatus,
    ForwardingStatus,
    HomeCallStatus,
    RingCallStatus,
    SelfTestStatus,
)
from .agent_contracts.self_test import normalize_self_test_contract
from .api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
)
from .api_validation import (
    normalize_activation_id,
    normalize_lock_id,
    normalize_memo_id,
    normalize_stair_light_address,
    normalize_text_memo_text,
    normalize_video_message_id,
)
from .const import (
    DEFAULT_AGENT_PORT,
    HEADER_MAINTENANCE_TOKEN,
    SMARTPHONE_FORWARDING_MODES,
)
from .fingerprint import fnv1a64_fingerprint
from .forwarding import coerce_forwarding_mode_state
from .validation_patterns import ACTIVATION_ID_RE
from .value_parsing import (
    optional_bool as _optional_bool,
)
from .value_parsing import (
    optional_int as _optional_int,
)
from .value_parsing import (
    optional_string as _optional_string,
)

_SETUP_TIMEOUT = 2.0


class C300XAgentApi:
    """Small async client for the C300X device agent API."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        token: str,
        maintenance_token: str = "",
        timeout: float = 5.0,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._maintenance_token = maintenance_token
        self._timeout = timeout

    async def async_validate_setup(self) -> CapabilityPayload:
        """Return agent/device metadata from `/api/v1/capabilities`."""

        data = await self._request_json(
            "GET",
            "/api/v1/capabilities",
            request_timeout=_SETUP_TIMEOUT,
        )
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("capabilities returned non-object JSON")
        agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
        device = data.get("device") if isinstance(data.get("device"), dict) else {}
        capabilities = data.get("capabilities")
        return CapabilityPayload(
            raw=data,
            version=_optional_string(agent.get("version") or data.get("api_version")),
            agent=agent,
            implementation=_optional_string(agent.get("implementation")),
            api_version=_optional_string(data.get("api_version")),
            device_id=_optional_string(device.get("id")),
            model=_optional_string(device.get("model")),
            firmware=_optional_string(device.get("firmware")),
            capabilities=capabilities if isinstance(capabilities, dict) else {},
        )

    async def async_smartphone_forwarding_status(self) -> ForwardingStatus:
        """Return smartphone forwarding status."""

        try:
            data = await self._request_json("GET", "/api/v1/smartphone-forwarding")
        except C300XAgentApiUnsupportedError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_smartphone_forwarding(data)

    async def async_state(self) -> dict[str, Any]:
        """Return the current aggregate device-agent state."""

        data = await self._request_json("GET", "/api/v1/state")
        return data if isinstance(data, dict) else {}

    async def async_smartphone_forwarding_cached_status(self) -> ForwardingStatus:
        """Return cached smartphone forwarding status without touching the device."""

        data = await self._request_json("GET", "/api/v1/state")
        return normalize_smartphone_forwarding(data)

    async def async_set_smartphone_forwarding_mode(self, mode: str) -> ForwardingStatus:
        """Set the smartphone forwarding mode."""

        normalized_mode = normalize_smartphone_forwarding_mode(mode)
        data = await self._request_json(
            "POST",
            "/api/v1/smartphone-forwarding",
            json_data={"mode": normalized_mode},
        )
        return normalize_smartphone_forwarding(data)

    async def async_stair_light(self, address: str) -> dict[str, Any]:
        """Activate the staircase light through an agent endpoint."""

        address = normalize_stair_light_address(address)
        data = await self._request_json(
            "POST",
            "/api/v1/stair-light/actions/activate",
            json_data={"address": address},
        )
        return _ok_response(data)

    async def async_unlock_door(self, lock_id: str = "default") -> dict[str, Any]:
        """Unlock the configured C300X door lock through the device agent."""

        normalized_lock_id = normalize_lock_id(lock_id)
        data = await self._request_json(
            "POST",
            f"/api/v1/locks/{quote(normalized_lock_id, safe='')}/actions/unlock",
        )
        return _ok_response(data)

    async def async_activations(self) -> dict[str, Any]:
        """Return configured C300X device activations."""

        data = await self._request_json("GET", "/api/v1/activations")
        return normalize_activations(data)

    async def async_run_device_activation(self, activation_id: str) -> dict[str, Any]:
        """Run one configured C300X device activation."""

        normalized_activation_id = normalize_activation_id(activation_id)
        data = await self._request_json(
            "POST",
            (
                "/api/v1/activations/"
                f"{quote(normalized_activation_id, safe='')}/actions/run"
            ),
        )
        return _ok_response(data)

    async def async_ringer_status(self) -> dict[str, Any]:
        """Return ringer mute and volume status."""

        try:
            data = await self._request_json("GET", "/api/v1/ringer")
        except C300XAgentApiError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_ringer(data)

    async def async_answering_machine_status(self) -> dict[str, Any]:
        """Return answering-machine status."""

        try:
            data = await self._request_json("GET", "/api/v1/answering-machine")
        except C300XAgentApiError:
            data = await self._request_json("GET", "/api/v1/state")
        return normalize_answering_machine(data)

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        """Return answering-machine video message metadata."""

        data = await self._request_json("GET", "/api/v1/answering-machine/messages")
        return normalize_answering_machine_messages(data)

    async def async_answering_machine_message_video(
        self,
        message_id: str,
    ) -> tuple[bytes, str]:
        """Return a stored answering-machine video message."""

        normalized_message_id = normalize_video_message_id(message_id)
        return await self._request_bytes(
            "GET",
            (
                "/api/v1/answering-machine/messages/"
                f"{quote(normalized_message_id, safe='')}/video"
            ),
        )

    async def async_delete_answering_machine_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        """Delete a stored answering-machine video message."""

        normalized_message_id = normalize_video_message_id(message_id)
        data = await self._request_json(
            "POST",
            "/api/v1/answering-machine/messages/actions/delete",
            json_data={"id": normalized_message_id},
        )
        return _ok_response(data)

    async def async_memos(self) -> dict[str, Any]:
        """Return local manual text and voice memo metadata."""

        data = await self._request_json("GET", "/api/v1/memos")
        return normalize_memos(data)

    async def async_create_text_memo(self, text: str, *, read: bool = False) -> dict[str, Any]:
        """Create a local manual text memo on the C300X."""

        normalized_text = normalize_text_memo_text(text)
        data = await self._request_json(
            "POST",
            "/api/v1/memos/text/actions/create",
            json_data={
                "text_b64": b64encode(normalized_text.encode()).decode("ascii"),
                "read": bool(read),
            },
        )
        return _ok_response(data)

    async def async_memo_audio(self, memo_id: str) -> tuple[bytes, str]:
        """Return a stored manual voice memo audio file."""

        normalized_memo_id = normalize_memo_id(memo_id)
        kind, entry_name = normalized_memo_id.split("/", 1)
        if kind != "voice":
            raise C300XAgentApiResponseError("memo id does not reference a voice memo")
        return await self._request_bytes(
            "GET",
            f"/api/v1/memos/voice/{quote(entry_name, safe='')}/audio",
        )

    async def async_delete_memo(self, memo_id: str) -> dict[str, Any]:
        """Delete a local manual memo by normalized agent memo id."""

        normalized_memo_id = normalize_memo_id(memo_id)
        data = await self._request_json(
            "POST",
            "/api/v1/memos/actions/delete",
            json_data={"id": normalized_memo_id},
        )
        return _ok_response(data)

    async def async_doorbell_video_status(self) -> DoorbellVideoStatus:
        """Return doorbell video availability and bridge status."""

        data = await self._request_json("GET", "/api/v1/video/doorbell/status")
        return normalize_doorbell_video(data)

    async def async_activate_doorbell_video(self, audio: bool = True) -> dict[str, Any]:
        """Start or renew the native doorbell video call on demand."""

        try:
            data = await self._request_json(
                "POST",
                "/api/v1/video/doorbell/actions/activate",
                json_data={"audio": bool(audio)},
            )
        except C300XAgentApiConnectionError as err:
            if "HTTP 409" not in str(err) or "external_session_active" not in str(err):
                raise
            status = await self.async_doorbell_video_status()
            if not _doorbell_video_has_ring_call(status):
                raise
            return {
                "ok": True,
                "audio": bool(audio),
                "ring_active": True,
                "status": status,
            }
        return _ok_response(data)

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        """Stop the native doorbell video call."""

        data = await self._request_json(
            "POST",
            "/api/v1/video/doorbell/actions/stop",
        )
        return _ok_response(data)

    async def async_doorbell_call_status(self) -> RingCallStatus:
        """Return the native doorbell ring-call control status."""

        data = await self._request_json("GET", "/api/v1/calls/doorbell/status")
        return normalize_doorbell_call(data)

    async def async_answer_doorbell_call(self) -> dict[str, Any]:
        """Request local media answering of the active doorbell ring call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/answer",
        )
        return _ok_response(data)

    async def async_hangup_doorbell_call(self) -> dict[str, Any]:
        """Hang up the active doorbell ring call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/hangup",
        )
        return _ok_response(data)

    async def async_capture_doorbell_call(self) -> dict[str, Any]:
        """Request a native doorbell ring-call capture."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/doorbell/actions/capture",
        )
        return _ok_response(data)

    async def async_home_call_status(self) -> HomeCallStatus:
        """Return the local Home Call status."""

        data = await self._request_json("GET", "/api/v1/calls/home/status")
        return normalize_home_call(data)

    async def async_start_home_call(
        self,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Start a local SIP/SRTP Home Call to the C300X."""

        payload: dict[str, Any] = {}
        if duration_seconds is not None:
            payload["duration_seconds"] = int(duration_seconds)
        data = await self._request_json(
            "POST",
            "/api/v1/calls/home/actions/start",
            json_data=payload,
        )
        return _ok_response(data)

    async def async_stop_home_call(self) -> dict[str, Any]:
        """Stop the local SIP/SRTP Home Call."""

        data = await self._request_json(
            "POST",
            "/api/v1/calls/home/actions/stop",
        )
        return _ok_response(data)

    async def async_system_metrics(self) -> dict[str, Any]:
        """Return low-frequency device-agent system metrics."""

        data = await self._request_json("GET", "/api/v1/system/metrics")
        return normalize_system_metrics(data)

    async def async_set_ringer_muted(self, muted: bool) -> dict[str, Any]:
        """Mute or unmute the device ringer."""

        data = await self._request_json(
            "POST",
            "/api/v1/ringer",
            json_data={"muted": muted},
        )
        return normalize_ringer(data)

    async def async_set_ringer_volume(self, volume: int) -> dict[str, Any]:
        """Set the device ringer volume."""

        data = await self._request_json(
            "POST",
            "/api/v1/ringer",
            json_data={"volume": int(volume)},
        )
        return normalize_ringer(data)

    async def async_set_answering_machine_enabled(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable the device answering machine."""

        data = await self._request_json(
            "POST",
            "/api/v1/answering-machine",
            json_data={"enabled": enabled},
        )
        return normalize_answering_machine(data)

    async def async_register_event_subscription(
        self,
        callback_url: str,
        token: str,
        events: list[str],
    ) -> dict[str, Any]:
        """Register the HA event webhook with the device agent."""

        data = await self._request_json(
            "POST",
            "/api/v1/events/subscriptions",
            json_data={
                "callback_url": callback_url,
                "token": token,
                "events": events,
            },
        )
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("event subscription returned non-object JSON")
        return data

    async def async_list_event_subscriptions(self) -> dict[str, Any]:
        """Return runtime event subscriptions from the device agent."""

        data = await self._request_json("GET", "/api/v1/events/subscriptions")
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError(
                "event subscriptions returned non-object JSON"
            )
        return data

    async def async_delete_event_subscription(self, subscription_id: str) -> None:
        """Delete a runtime event subscription from the device agent."""

        await self._request_json("DELETE", f"/api/v1/events/subscriptions/{subscription_id}")

    async def async_configure_display_bridge(
        self,
        *,
        enabled: bool,
        webhook_url: str = "",
        shared_secret: str = "",
    ) -> dict[str, Any]:
        """Configure the display bridge callback on the running device agent."""

        payload: dict[str, Any] = {"enabled": bool(enabled)}
        if enabled:
            payload["webhook_url"] = webhook_url
            payload["shared_secret"] = shared_secret
        data = await self._request_json(
            "POST",
            "/api/v1/display-bridge",
            json_data=payload,
        )
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("display bridge returned non-object JSON")
        return data

    async def async_display_bridge_status(self) -> dict[str, Any]:
        """Return display-bridge configuration status without mutating the agent."""

        data = await self._request_json("GET", "/api/v1/display-bridge")
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("display bridge status returned non-object JSON")
        return data

    async def async_notify_display_bridge_event(self, topic: str) -> dict[str, Any]:
        """Wake local display-bridge UI long-poll listeners for one topic."""

        data = await self._request_json(
            "POST",
            "/api/v1/display-bridge/events",
            json_data={"topic": str(topic)},
            request_timeout=2.0,
        )
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("display bridge event returned non-object JSON")
        return data

    async def async_diagnostics(self) -> AgentDiagnosticsStatus:
        """Return non-sensitive runtime diagnostics from the device agent."""

        data = await self._request_json("GET", "/api/v1/diagnostics")
        if not isinstance(data, dict):
            raise C300XAgentApiResponseError("diagnostics returned non-object JSON")
        return normalize_agent_diagnostics(data)

    async def async_self_test(self) -> SelfTestStatus:
        """Return the read-only device-agent architecture self-test."""

        data = await self._request_json(
            "GET",
            "/api/v1/self-test",
            request_timeout=_SETUP_TIMEOUT,
        )
        return normalize_self_test(data)

    async def async_device_user_status(self) -> dict[str, Any]:
        """Return non-sensitive Flexisip device-user status."""

        data = await self._request_json("GET", "/api/v1/device-user")
        return normalize_device_user_status(data)

    async def async_auth_config_status(self) -> AuthConfigStatus:
        """Return bootstrap/auth configuration status without exposing token values."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/auth",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_set_no_auth_enabled(
        self,
        enabled: bool,
        *,
        api_token: str | None = None,
        maintenance_token: str | None = None,
        maintenance_no_auth_allowed: bool | None = None,
    ) -> AuthConfigStatus:
        """Enable or disable the agent bootstrap noAuth mode."""

        payload: dict[str, Any] = {"noAuth": enabled}
        if api_token:
            payload["apiToken"] = api_token
        if maintenance_token:
            payload["maintenanceToken"] = maintenance_token
        if maintenance_no_auth_allowed is not None:
            payload["maintenanceNoAuthAllowed"] = maintenance_no_auth_allowed
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_set_mdns_enabled(self, enabled: bool) -> AuthConfigStatus:
        """Enable or disable bootstrap mDNS discovery in the device agent."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data={"mdnsEnabled": bool(enabled)},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_configure_device_activations(
        self,
        *,
        enabled: bool,
        auto_discover: bool,
        stair_light_address: str,
    ) -> AuthConfigStatus:
        """Configure native-agent C300X activation discovery."""

        payload: dict[str, Any] = {
            "activationsEnabled": bool(enabled),
            "activationsAutoDiscover": bool(auto_discover),
        }
        if not auto_discover:
            payload["activationStairLightAddress"] = normalize_stair_light_address(
                stair_light_address
            )
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_set_ipv6_firewall_enabled(self, enabled: bool) -> AuthConfigStatus:
        """Enable or disable the IPv6 firewall maintenance endpoint."""

        payload: dict[str, Any] = {"ipv6FirewallEnabled": bool(enabled)}
        if enabled:
            payload["maintenanceEnabled"] = True
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_set_firewall_enabled(self, enabled: bool) -> AuthConfigStatus:
        """Enable or disable the IPv4 firewall maintenance endpoint."""

        payload: dict[str, Any] = {"firewallEnabled": bool(enabled)}
        if enabled:
            payload["maintenanceEnabled"] = True
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_mqtt_status(self) -> dict[str, Any]:
        """Return native MQTT bridge status."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/mqtt",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_mqtt_status(data)

    async def async_set_mqtt_enabled(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable the native MQTT bridge."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/mqtt",
            json_data={"enabled": bool(enabled)},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_mqtt_status(data)

    async def async_migrate_legacy_mqtt_to_native(self) -> dict[str, Any]:
        """Disable legacy TcpDump2Mqtt and enable native MQTT when needed."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/mqtt/actions/migrate-legacy",
            json_data={"confirm": "migrate_legacy_mqtt"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_legacy_mqtt_status(self) -> dict[str, Any]:
        """Return legacy TcpDump2Mqtt autostart status."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/legacy-mqtt",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_legacy_mqtt_status(data)

    async def async_set_legacy_mqtt_enabled(self, enabled: bool) -> dict[str, Any]:
        """Enable or disable the legacy TcpDump2Mqtt autostart."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/legacy-mqtt",
            json_data={"enabled": bool(enabled)},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_legacy_mqtt_status(data)

    async def async_agent_update_status(self) -> dict[str, Any]:
        """Return native-agent self-update status."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/update/status",
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_prepare_agent_update(
        self,
        *,
        bundle_hash: str,
        agent_version: str,
    ) -> dict[str, Any]:
        """Prepare a staged native-agent self-update."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/update/prepare",
            json_data={
                "bundle_hash": bundle_hash,
                "agent_version": agent_version,
            },
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_upload_agent_update_chunk(
        self,
        *,
        path: str,
        sha256: str,
        mode: str,
        offset: int,
        data: bytes,
        final: bool,
    ) -> dict[str, Any]:
        """Upload one base64-encoded chunk for a staged agent update file."""

        response = await self._request_json(
            "POST",
            "/api/v1/maintenance/update/file",
            json_data={
                "path": path,
                "sha256": sha256,
                "mode": mode,
                "offset": offset,
                "data": b64encode(data).decode("ascii"),
                "final": final,
            },
            extra_headers=self._maintenance_headers(),
            request_timeout=max(self._timeout, 20.0),
        )
        return _ok_response(response)

    async def async_apply_agent_update(self, *, bundle_hash: str) -> dict[str, Any]:
        """Apply a verified staged native-agent self-update."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/update/apply",
            json_data={"bundle_hash": bundle_hash, "confirm": "update_agent"},
            extra_headers=self._maintenance_headers(),
            request_timeout=max(self._timeout, 20.0),
        )
        return _ok_response(data)

    async def async_normalize_agent_config(self) -> dict[str, Any]:
        """Rewrite the device config with the current agent schema and values."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/config/actions/normalize",
            json_data={"confirm": "normalize_config"},
            extra_headers=self._maintenance_headers(),
            request_timeout=max(self._timeout, 20.0),
        )
        return _ok_response(data)

    async def async_ensure_homeassistant_user(
        self,
        *,
        account_label: str | None = None,
    ) -> dict[str, Any]:
        """Create or repair the dedicated Home Assistant Flexisip user."""

        payload: dict[str, Any] = {"confirm": "ensure_homeassistant_user"}
        if account_label:
            payload["account_label"] = account_label
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/device-user/actions/ensure-homeassistant",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
            request_timeout=max(self._timeout, 20.0),
        )
        return normalize_device_user_status(data)

    async def async_restore_homeassistant_media_user_setup(self) -> dict[str, Any]:
        """Restore the device-side Home Assistant media user files from backups."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup",
            json_data={"confirm": "restore_ha_user_setup"},
            extra_headers=self._maintenance_headers(),
            request_timeout=max(self._timeout, 20.0),
        )
        return normalize_device_user_status(data)

    async def async_set_maintenance_no_auth_allowed(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        """Allow or deny noAuth access to maintenance endpoints."""

        payload: dict[str, Any] = {"maintenanceNoAuthAllowed": bool(enabled)}
        if enabled:
            payload["maintenanceEnabled"] = True
        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/auth",
            json_data=payload,
            extra_headers=self._maintenance_headers(),
        )
        return normalize_auth_config_status(data)

    async def async_start_ssh(self) -> dict[str, Any]:
        """Start the device SSH service through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/ssh/actions/start",
            json_data={"confirm": "start_ssh"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_stop_ssh(self) -> dict[str, Any]:
        """Stop the device SSH service through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/ssh/actions/stop",
            json_data={"confirm": "stop_ssh"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_ssh_status(data)

    async def async_ssh_status(self) -> dict[str, Any]:
        """Return SSH service state through the maintenance API."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/ssh",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_ssh_status(data)

    async def async_set_ssh_enabled(self, enabled: bool) -> dict[str, Any]:
        """Start or stop SSH through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/ssh",
            json_data={"enabled": enabled},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_ssh_status(data)

    async def async_reboot(self) -> dict[str, Any]:
        """Schedule a device reboot through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/reboot",
            json_data={"confirm": "reboot"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_remove_agent(self) -> dict[str, Any]:
        """Schedule native agent removal while keeping SSH available."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/agent/actions/remove",
            json_data={"confirm": "remove_agent"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_restart_agent(self) -> dict[str, Any]:
        """Restart the native device agent through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/agent/actions/restart",
            json_data={"confirm": "restart_agent"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_reload_gui(self) -> dict[str, Any]:
        """Reload the C300X graphical interface through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/gui/actions/reload",
            json_data={"confirm": "reload_gui"},
            extra_headers=self._maintenance_headers(),
        )
        return _ok_response(data)

    async def async_firewall_status(self) -> FirewallStatus:
        """Return C300X persistent firewall rule state through the maintenance API."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/firewall",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_apply_firewall(self) -> FirewallStatus:
        """Apply the persistent C300X API firewall rule."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/firewall/actions/apply",
            json_data={"confirm": "apply_firewall"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_restore_firewall(self) -> FirewallStatus:
        """Remove the persistent C300X API firewall rule."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/firewall/actions/restore",
            json_data={"confirm": "restore_firewall"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_ipv6_firewall_status(self) -> FirewallStatus:
        """Return C300X persistent IPv6 firewall rule state."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/ipv6-firewall",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_apply_ipv6_firewall(self) -> FirewallStatus:
        """Apply the persistent C300X IPv6 API firewall rules."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/ipv6-firewall/actions/apply",
            json_data={"confirm": "apply_ipv6_firewall"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_restore_ipv6_firewall(self) -> FirewallStatus:
        """Remove the persistent C300X IPv6 API firewall rules."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/ipv6-firewall/actions/restore",
            json_data={"confirm": "restore_ipv6_firewall"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_firewall_status(data)

    async def async_qml_patch_status(self) -> dict[str, Any]:
        """Return device UI patch state through the maintenance API."""

        data = await self._request_json(
            "GET",
            "/api/v1/maintenance/qml-patch",
            extra_headers=self._maintenance_headers(),
        )
        return normalize_qml_patch_status(data)

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        """Apply the device UI patch through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/qml-patch/actions/apply",
            json_data={
                "confirm": "apply_qml_patch",
                "dynamic_homepage": dynamic_homepage,
            },
            extra_headers=self._maintenance_headers(),
        )
        return normalize_qml_patch_status(data)

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        """Apply the core media QML hook through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/qml-patch/actions/apply-core",
            json_data={"confirm": "apply_qml_core_patch"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_qml_patch_status(data)

    async def async_restore_qml_core_patch(self) -> dict[str, Any]:
        """Restore the core media QML hook through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/qml-patch/actions/restore-core",
            json_data={"confirm": "restore_qml_core_patch"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_qml_patch_status(data)

    async def async_restore_qml_patch(self) -> dict[str, Any]:
        """Restore original device UI files through the maintenance API."""

        data = await self._request_json(
            "POST",
            "/api/v1/maintenance/qml-patch/actions/restore",
            json_data={"confirm": "restore_qml_patch"},
            extra_headers=self._maintenance_headers(),
        )
        return normalize_qml_patch_status(data)

    async def _request_json(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data,
                timeout=self._timeout if request_timeout is None else request_timeout,
            ) as response:
                text = await response.text()
                if response.status == 404:
                    raise C300XAgentApiUnsupportedError(
                        _http_error_text(
                            response.status,
                            text,
                            fallback=f"device-agent endpoint is not available: {path}",
                        )
                    )
                if response.status < 200 or response.status >= 300:
                    raise C300XAgentApiConnectionError(
                        _http_error_text(response.status, text)
                    )
        except TimeoutError as err:
            raise C300XAgentApiConnectionError("device-agent request timed out") from err
        except ClientError as err:
            raise C300XAgentApiConnectionError(str(err)) from err

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as err:
            raise C300XAgentApiResponseError("device agent returned invalid JSON") from err

    async def _request_bytes(
        self,
        method: str,
        path: str,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                timeout=self._timeout,
            ) as response:
                if response.status == 404:
                    text = await response.text()
                    raise C300XAgentApiUnsupportedError(
                        _http_error_text(
                            response.status,
                            text,
                            fallback=f"device-agent endpoint is not available: {path}",
                        )
                    )
                if response.status < 200 or response.status >= 300:
                    text = await response.text()
                    raise C300XAgentApiConnectionError(
                        _http_error_text(response.status, text)
                    )
                content = await response.read()
                content_type = response.headers.get(
                    "Content-Type",
                    "application/octet-stream",
                )
        except TimeoutError as err:
            raise C300XAgentApiConnectionError("device-agent request timed out") from err
        except ClientError as err:
            raise C300XAgentApiConnectionError(str(err)) from err
        return content, content_type.split(";", 1)[0]

    def _maintenance_headers(self) -> dict[str, str]:
        """Return maintenance authorization headers when configured."""

        if not self._maintenance_token:
            return {}
        return {HEADER_MAINTENANCE_TOKEN: self._maintenance_token}


def build_agent_base_url(host: str, port: int) -> str:
    """Build the HTTP device-agent base URL from config entry data."""

    normalized_host = host.strip().strip("/")
    normalized_port = port if port > 0 else DEFAULT_AGENT_PORT
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    return f"http://{normalized_host}:{normalized_port}"


def encode_endpoint_url(url: str) -> str:
    """Return a base64-encoded endpoint URL."""

    return b64encode(url.encode("utf-8")).decode("ascii")


def _http_error_text(status: int, text: str, *, fallback: str | None = None) -> str:
    """Return a compact, safe HTTP error text from an agent response."""

    base = fallback or f"device agent returned HTTP {status}"
    detail = _agent_error_detail(text)
    if detail:
        return f"{base}: {detail}"
    return base


def _agent_error_detail(text: str) -> str | None:
    """Extract a short non-secret agent error from a JSON response body."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("error", "message"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _compact_agent_error_value(value)
    return None


def _compact_agent_error_value(value: str, *, max_length: int = 120) -> str:
    """Return one safe line from an agent error string."""

    compacted = " ".join(value.strip().split())
    if len(compacted) > max_length:
        return f"{compacted[: max_length - 3]}..."
    return compacted


def display_bridge_callback_fingerprint(
    enabled: bool,
    webhook_url: str,
    shared_secret: str,
) -> str:
    """Return the non-secret display-bridge callback fingerprint used by the agent."""

    material = f"{1 if enabled else 0}\n{webhook_url if enabled else ''}\n{shared_secret if enabled else ''}"
    return fnv1a64_fingerprint(material)


def _ok_response(data: Any) -> dict[str, Any]:
    """Return mutation responses as dictionaries."""

    return data if isinstance(data, dict) else {"ok": True, "raw": data}


def normalize_doorbell_video(data: Any) -> DoorbellVideoStatus:
    """Normalize device-agent doorbell video status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("doorbell video returned non-object JSON")
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    return DoorbellVideoStatus(
        raw=data,
        available=bool(data.get("available")),
        window_available=bool(data.get("window_available")),
        stream_path=_optional_string(data.get("stream_path")),
        audio_stream_path=_optional_string(data.get("audio_stream_path")),
        recorder_stream_path=_optional_string(data.get("recorder_stream_path")),
        media_owner=_optional_string(bridge.get("media_owner")) or "unknown",
        external_media_active=_optional_bool(bridge.get("external_media_active"))
        is True,
        external_owner=_optional_string(bridge.get("external_owner")),
        last_block_reason=_optional_string(bridge.get("last_block_reason")),
        bridge=bridge,
    )


def _doorbell_video_has_ring_call(data: Mapping[str, Any]) -> bool:
    """Return true while the native bridge owns a doorbell ring call."""

    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    owner = str(data.get("media_owner") or bridge.get("media_owner") or "").lower()
    return owner == "ring" or bool(
        bridge.get("ring_call_active") or bridge.get("ring_media_active")
    )


def normalize_doorbell_call(data: Any) -> RingCallStatus:
    """Normalize device-agent doorbell ring-call control status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("doorbell call returned non-object JSON")
    return RingCallStatus(
        raw=data,
        supported=bool(data.get("supported")),
        active=bool(data.get("active")),
        early_media_active=bool(data.get("early_media_active")),
        audio_active=bool(data.get("audio_active")),
        answer_requested=bool(data.get("answer_requested")),
        answered=bool(data.get("answered")),
        can_answer=bool(data.get("can_answer")),
        can_hangup=bool(data.get("can_hangup")),
        media_owner=_optional_string(data.get("media_owner")) or "unknown",
        ring_receiver_running=bool(data.get("ring_receiver_running")),
        ring_registered=bool(data.get("ring_registered")),
        capture_supported=bool(data.get("capture_supported")),
        open_fds=_optional_int(data.get("open_fds"), 0) or 0,
        active_threads=_optional_int(data.get("active_threads"), 0) or 0,
        last_error=_optional_string(data.get("last_error")),
    )


def normalize_home_call(data: Any) -> HomeCallStatus:
    """Normalize device-agent local Home Call status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("home call returned non-object JSON")
    return HomeCallStatus(
        raw=data,
        available=bool(data.get("available")),
        running=bool(data.get("running")),
        active=bool(data.get("active")),
        answered=bool(data.get("answered")),
        rtp_proxy=bool(data.get("rtp_proxy")),
        target_audio_port=_optional_int(data.get("target_audio_port")),
        rtp_packets=_optional_int(data.get("rtp_packets"), 0) or 0,
        rtcp_packets=_optional_int(data.get("rtcp_packets"), 0) or 0,
        max_duration_seconds=_optional_int(data.get("max_duration_seconds")),
        last_error=_optional_string(data.get("last_error")),
    )


def normalize_activations(data: Any) -> dict[str, Any]:
    """Normalize configured C300X activation discovery responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("activations returned non-object JSON")
    items = data.get("items") if isinstance(data.get("items"), list) else []
    normalized_items = [
        activation
        for activation in (_normalize_activation(item) for item in items)
        if activation is not None
    ]
    return {
        "available": bool(data.get("available", True)),
        "supported": bool(data.get("supported", bool(normalized_items))),
        "count": _optional_int(data.get("count"), len(normalized_items)),
        "items": normalized_items,
        "raw": data,
    }


def normalize_system_metrics(data: Any) -> dict[str, Any]:
    """Normalize device-agent system metric responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("system metrics returned non-object JSON")
    return {
        "cpu_count": _optional_int(data.get("cpu_count")),
        "cpu_usage_percent": _optional_float(data.get("cpu_usage_percent")),
        "load_1m": _optional_float(data.get("load_1m")),
        "load_5m": _optional_float(data.get("load_5m")),
        "load_15m": _optional_float(data.get("load_15m")),
        "load_1m_percent": _optional_float(data.get("load_1m_percent")),
        "load_5m_percent": _optional_float(data.get("load_5m_percent")),
        "load_15m_percent": _optional_float(data.get("load_15m_percent")),
        "memory_total_kb": _optional_int(data.get("memory_total_kb")),
        "memory_available_kb": _optional_int(data.get("memory_available_kb")),
        "memory_used_kb": _optional_int(data.get("memory_used_kb")),
        "memory_usage_percent": _optional_float(data.get("memory_usage_percent")),
        "temperature_c": _optional_float(data.get("temperature_c")),
        "temperature_source": data.get("temperature_source"),
        "raw": data,
    }


def normalize_agent_diagnostics(data: Any) -> AgentDiagnosticsStatus:
    """Normalize non-sensitive agent diagnostics."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("diagnostics returned non-object JSON")
    return AgentDiagnosticsStatus(
        raw=data,
        agent_write_count=_optional_int(data.get("agent_write_count")) or 0,
        last_write_at=_optional_int(data.get("last_write_at")),
        last_write_reason=_optional_string(data.get("last_write_reason")),
        last_write_class=_optional_string(data.get("last_write_class")),
        qml_patch_last_action=_optional_string(data.get("qml_patch_last_action")),
        loop_iterations=_optional_int(data.get("loop_iterations")),
        poll_wakeups=_optional_int(data.get("poll_wakeups")),
        accepted_clients=_optional_int(data.get("accepted_clients")),
        last_wake_reason=_optional_string(data.get("last_wake_reason")),
        last_poll_timeout_ms=_optional_int(data.get("last_poll_timeout_ms")),
        last_poll_count=_optional_int(data.get("last_poll_count")),
        open_fd_count=_optional_int(data.get("open_fd_count")),
        agent_init_script_present=_optional_bool(data.get("agent_init_script_present")),
        agent_init_link_ok=_optional_bool(data.get("agent_init_link_ok")),
        subscription_count=_optional_int(data.get("subscription_count")),
        recent_event_count=_optional_int(data.get("recent_event_count")),
        recent_event_capacity=_optional_int(data.get("recent_event_capacity")),
        display_bridge_registered=_optional_bool(data.get("display_bridge_registered")),
        display_bridge_disabled=_optional_bool(data.get("display_bridge_disabled")),
        home_assistant_connected_this_run=_optional_bool(
            data.get("home_assistant_connected_this_run")
        ),
        home_assistant_last_seen_at=_optional_int(
            data.get("home_assistant_last_seen_at")
        ),
        ui_event_revision=_optional_int(data.get("ui_event_revision")),
        ui_event_waiters=_optional_int(data.get("ui_event_waiters")),
        ui_event_waiter_capacity=_optional_int(data.get("ui_event_waiter_capacity")),
        ui_event_waiter_overflows=_optional_int(data.get("ui_event_waiter_overflows")),
        video_running=_optional_bool(data.get("video_running")),
        video_rtsp_server_running=_optional_bool(
            data.get("video_rtsp_server_running")
        ),
        video_media_starting=_optional_bool(data.get("video_media_starting")),
        video_call_active=_optional_bool(data.get("video_call_active")),
        video_clients=_optional_int(data.get("video_clients")),
        video_media_owner=_optional_string(data.get("video_media_owner")),
        video_external_media_active=_optional_bool(
            data.get("video_external_media_active")
        ),
        video_external_owner=_optional_string(data.get("video_external_owner")),
        video_last_block_reason=_optional_string(data.get("video_last_block_reason")),
        video_bridge_running=_optional_bool(data.get("video_bridge_running")),
        video_bridge_media_active=_optional_bool(data.get("video_bridge_media_active")),
        video_bridge_stop_in_progress=_optional_bool(
            data.get("video_bridge_stop_in_progress")
        ),
        video_bridge_open_fds=_optional_int(data.get("video_bridge_open_fds")),
        video_bridge_active_threads=_optional_int(
            data.get("video_bridge_active_threads")
        ),
        ring_receiver_running=_optional_bool(data.get("ring_receiver_running")),
        ring_registered=_optional_bool(data.get("ring_registered")),
        ring_call_active=_optional_bool(data.get("ring_call_active")),
        ring_media_active=_optional_bool(data.get("ring_media_active")),
        home_call_running=_optional_bool(data.get("home_call_running")),
        home_call_active=_optional_bool(data.get("home_call_active")),
        flexisip_backup_available=_optional_bool(data.get("flexisip_backup_available")),
        flexisip_restart_marker=_optional_bool(data.get("flexisip_restart_marker")),
        flexisip_backup_marker=_optional_bool(data.get("flexisip_backup_marker")),
        flexisip_reference_state=_optional_string(data.get("flexisip_reference_state")),
    )


def normalize_self_test(data: Any) -> SelfTestStatus:
    """Normalize device-agent self-test status."""

    return normalize_self_test_contract(data, C300XAgentApiResponseError)


def normalize_device_user_status(data: Any) -> dict[str, Any]:
    """Normalize non-sensitive Flexisip device-user status."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("device user status returned non-object JSON")
    available = _optional_bool(data.get("ok")) is not False

    def status_bool(key: str) -> bool | None:
        if not available:
            return None
        return _optional_bool(data.get(key))

    return {
        "available": available,
        "supported": _optional_bool(data.get("supported")) is True,
        "domain_present": status_bool("domain_present"),
        "homeassistant_user_present": status_bool("homeassistant_user_present"),
        "accounts_homeassistant_present": status_bool(
            "accounts_homeassistant_present"
        ),
        "route_int_homeassistant_present": status_bool(
            "route_int_homeassistant_present"
        ),
        "route_ext_homeassistant_present": status_bool(
            "route_ext_homeassistant_present"
        ),
        "route_conf_homeassistant_present": status_bool(
            "route_conf_homeassistant_present"
        ),
        "route_conf_is_symlink": status_bool("route_conf_is_symlink"),
        "writable_files_present": status_bool("writable_files_present"),
        "media_identity_available": status_bool("media_identity_available"),
        "routes_consistent": status_bool("routes_consistent"),
        "device_routing_supported": status_bool("device_routing_supported"),
        "device_routing_applied": status_bool("device_routing_applied"),
        "device_routing_state": _optional_string(
            data.get("device_routing_state")
        ),
        "device_routing_backup_present": status_bool("device_routing_backup_present"),
        "device_routing_error": _optional_string(
            data.get("device_routing_error")
        ),
        "media_user_label_available": status_bool("media_user_label_available"),
        "media_user_label_applied": status_bool("media_user_label_applied"),
        "media_user_label_state": _optional_string(
            data.get("media_user_label_state")
        ),
        "account_label": _optional_string(data.get("account_label")),
        "error": _optional_string(data.get("error")),
        "raw": _safe_device_user_raw(data),
    }


_SAFE_DEVICE_USER_RAW_KEYS = frozenset(
    {
        "ok",
        "status_available",
        "supported",
        "domain_present",
        "homeassistant_user_present",
        "accounts_homeassistant_present",
        "route_int_homeassistant_present",
        "route_ext_homeassistant_present",
        "route_conf_homeassistant_present",
        "route_conf_is_symlink",
        "writable_files_present",
        "media_identity_available",
        "routes_consistent",
        "device_routing_supported",
        "device_routing_applied",
        "device_routing_state",
        "device_routing_backup_present",
        "device_routing_error",
        "media_user_label_available",
        "media_user_label_applied",
        "media_user_label_state",
        "error",
    }
)


def _safe_device_user_raw(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a non-sensitive raw view for device-user diagnostics.

    The device-side SIP realm and AOR values are local implementation details.
    Keep the functional presence flags, but never preserve unknown fields from
    this endpoint because they may include route contents, digests, or AORs.
    """

    return {key: data.get(key) for key in _SAFE_DEVICE_USER_RAW_KEYS if key in data}


def normalize_auth_config_status(data: Any) -> AuthConfigStatus:
    """Normalize bootstrap/auth configuration status."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("auth config returned non-object JSON")
    no_auth = _optional_bool(data.get("noAuth"))
    if no_auth is None:
        no_auth = _optional_bool(data.get("no_auth"))
    return AuthConfigStatus(
        raw=data,
        no_auth=bool(no_auth),
        restart_required=_optional_bool(data.get("restart_required")) is True,
        api_token_configured=bool(data.get("api_token_configured")),
        maintenance_token_configured=bool(data.get("maintenance_token_configured")),
        maintenance_enabled=_optional_bool(data.get("maintenance_enabled")),
        maintenance_no_auth_allowed=_optional_bool(
            data.get("maintenance_no_auth_allowed")
        ),
        mdns_enabled=_optional_bool(data.get("mdns_enabled")),
        firewall_enabled=_optional_bool(data.get("firewall_enabled")),
        ipv6_firewall_enabled=_optional_bool(data.get("ipv6_firewall_enabled")),
        activations_enabled=_optional_bool(data.get("activations_enabled")),
        activations_auto_discover=_optional_bool(data.get("activations_auto_discover")),
        activation_stair_light_address=_optional_string(
            data.get("activation_stair_light_address")
        ),
    )


def normalize_ssh_status(data: Any) -> dict[str, Any]:
    """Normalize maintenance SSH status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("SSH status returned non-object JSON")
    raw_value = data.get("running", data.get("enabled"))
    if raw_value is None:
        return {"running": None, "enabled": None, "raw": data}
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "running", "enabled"}:
            running = True
        elif normalized in {"false", "0", "off", "stopped", "disabled"}:
            running = False
        else:
            running = None
    else:
        running = bool(raw_value)
    return {
        "running": running,
        "enabled": running,
        "raw": data.get("raw", data),
    }


def normalize_qml_patch_status(data: Any) -> dict[str, Any]:
    """Normalize maintenance Display patch status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("Display patch status returned non-object JSON")
    state = str(data.get("state") or "").strip().lower()
    patched = _optional_bool(data.get("patched"))
    if patched is None:
        if state in {"patched", "applied"}:
            patched = True
        elif state in {"original", "restored", "not_patched"}:
            patched = False
    if not state:
        if patched is True:
            state = "patched"
        elif patched is False:
            state = "original"
        else:
            state = "unknown"
    return {
        "available": bool(data.get("available", True)),
        "patched": patched,
        "state": state,
        "core_patched": _optional_bool(data.get("core_patched")),
        "core_state": _optional_string(data.get("core_state")),
        "backup_available": _optional_bool(data.get("backup_available")),
        "core_backup_available": _optional_bool(data.get("core_backup_available")),
        "gui_running": _optional_bool(data.get("gui_running")),
        "raw": data.get("raw", data),
    }


def normalize_firewall_status(data: Any) -> FirewallStatus:
    """Normalize maintenance firewall status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("firewall status returned non-object JSON")
    state = _optional_string(data.get("state")) or "unknown"
    patched = _optional_bool(data.get("patched"))
    if patched is None and state == "patched":
        patched = True
    elif patched is None and state in {"original", "missing"}:
        patched = False
    return FirewallStatus(
        raw=data,
        available=data.get("available", True) is not False,
        state=state,
        patched=patched,
        family=_optional_string(data.get("family")),
        exists=_optional_bool(data.get("exists")),
        backup_available=_optional_bool(data.get("backup_available")),
        api_port=_optional_int(data.get("api_port")),
        rtsp_port=_optional_int(data.get("rtsp_port")),
        talkback_rtp_port=_optional_int(data.get("talkback_rtp_port")),
        media_ports_enabled=_optional_bool(data.get("media_ports_enabled")),
        changed_files=_optional_int(data.get("changed_files")),
    )


def normalize_mqtt_status(data: Any) -> dict[str, Any]:
    """Normalize native MQTT bridge status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("MQTT status returned non-object JSON")
    topics = data.get("topics") if isinstance(data.get("topics"), dict) else {}
    return {
        "available": data.get("available", True) is not False,
        "enabled": _optional_bool(data.get("enabled")),
        "configured": _optional_bool(data.get("configured")),
        "connected": _optional_bool(data.get("connected")),
        "subscribed": _optional_bool(data.get("subscribed")),
        "host_configured": _optional_bool(data.get("host_configured")),
        "username_configured": _optional_bool(data.get("username_configured")),
        "password_configured": _optional_bool(data.get("password_configured")),
        "port": _optional_int(data.get("port")),
        "client_id": _optional_string(data.get("client_id")),
        "command_host": _optional_string(data.get("command_host")),
        "command_port": _optional_int(data.get("command_port")),
        "command_topic": _optional_string(topics.get("command")),
        "event_topic": _optional_string(topics.get("event")),
        "json_event_topic": _optional_string(topics.get("json_event")),
        "status_topic": _optional_string(topics.get("status")),
        "availability_topic": _optional_string(topics.get("availability")),
        "qos": _optional_int(data.get("qos")),
        "keepalive_seconds": _optional_int(data.get("keepalive_seconds")),
        "reconnect_initial_seconds": _optional_int(
            data.get("reconnect_initial_seconds")
        ),
        "reconnect_max_seconds": _optional_int(data.get("reconnect_max_seconds")),
        "legacy_installed": _optional_bool(data.get("legacy_installed")),
        "legacy_enabled": _optional_bool(data.get("legacy_enabled")),
        "legacy_running": _optional_bool(data.get("legacy_running")),
        "exclusive": data.get("exclusive") is True,
        "raw": data,
    }


def normalize_legacy_mqtt_status(data: Any) -> dict[str, Any]:
    """Normalize legacy TcpDump2Mqtt patch status responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("legacy MQTT status returned non-object JSON")
    return {
        "available": data.get("available", True) is not False,
        "enabled": _optional_bool(data.get("enabled")),
        "installed": _optional_bool(data.get("installed")),
        "running": _optional_bool(data.get("running")),
        "backup_available": _optional_bool(data.get("backup_available")),
        "native_enabled": _optional_bool(data.get("native_enabled")),
        "exclusive": data.get("exclusive") is True,
        "script_path": _optional_string(data.get("script_path")),
        "init_link": _optional_string(data.get("init_link")),
        "flexisip_backup_available": _optional_bool(
            data.get("flexisip_backup_available")
        ),
        "flexisip_restart_marker": _optional_bool(data.get("flexisip_restart_marker")),
        "flexisip_reference_state": _optional_string(
            data.get("flexisip_reference_state")
        ),
        "raw": data,
    }


def normalize_smartphone_forwarding_mode(mode: Any) -> str:
    """Validate and normalize a smartphone-forwarding mode string."""

    value = str(mode or "").strip().lower()
    if value not in SMARTPHONE_FORWARDING_MODES:
        raise C300XAgentApiResponseError("invalid smartphone-forwarding mode")
    return value


def normalize_smartphone_forwarding(data: Any) -> ForwardingStatus:
    """Normalize device-agent smartphone-forwarding responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("smartphone-forwarding returned non-object JSON")
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("smartphone_forwarding")
        if raw_value is None:
            return ForwardingStatus(raw=data, mode=None, state="unknown")
        return _normalized_smartphone_forwarding(raw_value, raw_value, raw=data)
    if data.get("mode") is None and data.get("state") == "unknown":
        return ForwardingStatus(raw=data.get("raw", data), mode=None, state="unknown")
    if "enabled" in data:
        return _normalized_smartphone_forwarding(
            data["enabled"],
            data["enabled"],
            raw=data.get("raw"),
        )
    normalized = coerce_forwarding_mode_state(data.get("mode"), data.get("state"))
    if normalized["mode"] is None:
        raise C300XAgentApiResponseError("smartphone-forwarding mode is missing")
    mode_value = normalized["mode"]
    return ForwardingStatus(
        raw=data.get("raw"),
        mode=mode_value if isinstance(mode_value, int) else None,
        state=str(normalized["state"]),
    )


def _normalized_smartphone_forwarding(
    mode: Any,
    state: Any,
    *,
    raw: Any,
) -> ForwardingStatus:
    normalized = coerce_forwarding_mode_state(mode, state)
    mode_value = normalized["mode"]
    return ForwardingStatus(
        raw=raw,
        mode=mode_value if isinstance(mode_value, int) else None,
        state=str(normalized["state"]),
    )


def normalize_ringer(data: Any) -> dict[str, Any]:
    """Normalize device-agent ringer responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("ringer returned non-object JSON")
    raw_value: Any
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("ringer_muted")
        volume_value = data["state"].get("ringer_volume")
        has_volume = "ringer_volume" in data["state"]
        raw = data
    else:
        raw_value = data.get("muted")
        volume_value = data.get("volume")
        has_volume = "volume" in data
        raw = data.get("raw", data)
    result: dict[str, Any] = {"muted": None, "raw": raw}
    if raw_value is None:
        result["muted"] = None
    elif isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "muted"}:
            result["muted"] = True
        elif normalized in {"false", "0", "off", "unmuted"}:
            result["muted"] = False
        else:
            result["muted"] = bool(raw_value)
    else:
        result["muted"] = bool(raw_value)
    if has_volume:
        result["volume"] = _normalize_ringer_volume(volume_value)
    return result


def _normalize_ringer_volume(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= volume <= 100:
        return volume
    return None


def normalize_answering_machine(data: Any) -> dict[str, Any]:
    """Normalize device-agent answering-machine responses."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("answering-machine returned non-object JSON")
    raw_value: Any
    if "state" in data and isinstance(data["state"], dict):
        raw_value = data["state"].get("answering_machine_enabled")
        raw = data
    else:
        raw_value = data.get("enabled")
        raw = data.get("raw", data)
    result: dict[str, Any] = {
        "enabled": None,
        "greeting_message_enabled": _optional_bool(data.get("greeting_message_enabled")),
        "status_fields": (
            data.get("status_fields")
            if isinstance(data.get("status_fields"), list)
            else []
        ),
        "raw": raw,
    }
    if raw_value is None:
        return result
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "on", "enabled"}:
            result["enabled"] = True
            return result
        if normalized in {"false", "0", "off", "disabled"}:
            result["enabled"] = False
            return result
    result["enabled"] = bool(raw_value)
    return result


def normalize_answering_machine_messages(data: Any) -> dict[str, Any]:
    """Normalize device-agent answering-machine video message metadata."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError(
            "answering-machine messages returned non-object JSON"
        )
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    normalized_messages = [
        message
        for message in (_normalize_voicemail_message(item) for item in messages)
        if message is not None
    ]
    return {
        "available": bool(data.get("available", True)),
        "total": _optional_int(data.get("total"), len(normalized_messages)),
        "unread": _optional_int(data.get("unread"), 0),
        "read": _optional_int(data.get("read"), 0),
        "newest_at": data.get("newest_at"),
        "messages": normalized_messages,
        "raw": data,
    }


def normalize_memos(data: Any) -> dict[str, Any]:
    """Normalize device-agent local memo metadata."""

    if not isinstance(data, dict):
        raise C300XAgentApiResponseError("memos returned non-object JSON")
    memos = data.get("memos") if isinstance(data.get("memos"), list) else []
    normalized_memos = [
        memo
        for memo in (_normalize_memo(item) for item in memos)
        if memo is not None
    ]
    text_total = _optional_int(data.get("text_total"), None)
    voice_total = _optional_int(data.get("voice_total"), None)
    if text_total is None:
        text_total = sum(1 for memo in normalized_memos if memo["kind"] == "text")
    if voice_total is None:
        voice_total = sum(1 for memo in normalized_memos if memo["kind"] == "voice")
    return {
        "available": bool(data.get("available", True)),
        "total": _optional_int(data.get("total"), text_total + voice_total),
        "text_total": text_total,
        "voice_total": voice_total,
        "unread": _optional_int(data.get("unread"), 0),
        "read": _optional_int(data.get("read"), 0),
        "newest_at": data.get("newest_at"),
        "memos": normalized_memos,
        "raw": data,
    }


def _normalize_voicemail_message(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    message_id = str(data.get("id") or "").strip()
    if not message_id:
        return None
    return {
        "id": message_id,
        "read": _optional_bool(data.get("read")),
        "date": data.get("date"),
        "unix_time": _optional_int(data.get("unix_time")),
        "iso_time": data.get("iso_time"),
        "has_thumbnail": bool(data.get("has_thumbnail")),
        "has_video": bool(data.get("has_video")),
        "media_mime_type": data.get("media_mime_type"),
        "media_size": _optional_int(data.get("media_size")),
    }


def _normalize_memo(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    memo_id = str(data.get("id") or "").strip()
    kind = str(data.get("kind") or "").strip().lower()
    if not memo_id or kind not in {"text", "voice"}:
        return None
    text = data.get("text")
    return {
        "id": memo_id,
        "kind": kind,
        "read": _optional_bool(data.get("read")),
        "date": data.get("date"),
        "unix_time": _optional_int(data.get("unix_time")),
        "iso_time": data.get("iso_time"),
        "has_text": bool(data.get("has_text")),
        "has_audio": bool(data.get("has_audio")),
        "audio_mime_type": data.get("audio_mime_type"),
        "audio_size": _optional_int(data.get("audio_size")),
        "text": text if isinstance(text, str) else None,
        "text_truncated": bool(data.get("text_truncated")),
    }


def _normalize_activation(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    activation_id = str(data.get("id") or "").strip()
    if not ACTIVATION_ID_RE.fullmatch(activation_id):
        return None
    name = str(data.get("name") or "").strip()
    if not name:
        name = activation_id.replace("_", " ").replace("-", " ").title()
    activation_type = str(data.get("type") or "unknown").strip().lower()
    if activation_type not in {
        "lock",
        "light",
        "stair_light",
        "generic",
        "scenario",
        "unknown",
    }:
        activation_type = "unknown"
    address_mode = str(
        data.get("addressMode") or data.get("address_mode") or "manual"
    ).strip().lower()
    if address_mode not in {"manual", "auto"}:
        address_mode = "manual"
    source = str(data.get("source") or "agent").strip().lower() or "agent"
    return {
        "id": activation_id,
        "name": name,
        "type": activation_type,
        "address_mode": address_mode,
        "address": _optional_string(data.get("address")),
        "source": source,
        "executable": _optional_bool(data.get("executable")) is True,
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise C300XAgentApiResponseError("system metric value is invalid") from err
