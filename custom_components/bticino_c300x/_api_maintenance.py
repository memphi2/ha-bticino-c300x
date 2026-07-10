"""Maintenance endpoints: ssh, reboot, firewall, qml, mqtt, agent update, display bridge."""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from ._api_core import _SETUP_TIMEOUT, _C300XApiCore
from ._api_normalize import (
    _ok_response,
    normalize_agent_diagnostics,
    normalize_auth_config_status,
    normalize_device_user_status,
    normalize_firewall_status,
    normalize_legacy_mqtt_status,
    normalize_mqtt_status,
    normalize_qml_patch_status,
    normalize_self_test,
    normalize_ssh_status,
)
from .agent_contracts import (
    AgentDiagnosticsStatus,
    AuthConfigStatus,
    FirewallStatus,
    SelfTestStatus,
)
from .api_errors import (
    C300XAgentApiResponseError,
)


class _ApiMaintenanceMixin(_C300XApiCore):
    """Maintenance endpoints: ssh, reboot, firewall, qml, mqtt, agent update, display bridge."""

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
    ) -> AuthConfigStatus:
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
