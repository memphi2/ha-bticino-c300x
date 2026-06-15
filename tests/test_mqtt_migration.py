from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from custom_components.bticino_c300x import mqtt_migration
from custom_components.bticino_c300x.api import C300XAgentApiUnsupportedError


class _MigratingApi:
    async def async_migrate_legacy_mqtt_to_native(self) -> dict[str, Any]:
        return {"ok": True, "migrated": True}


class _UnsupportedApi:
    async def async_migrate_legacy_mqtt_to_native(self) -> dict[str, Any]:
        raise C300XAgentApiUnsupportedError("unsupported")


def test_migrate_legacy_mqtt_if_available_returns_agent_result() -> None:
    import asyncio

    assert asyncio.run(
        mqtt_migration.async_migrate_legacy_mqtt_if_available(_MigratingApi())
    ) == {"ok": True, "migrated": True}


def test_migrate_legacy_mqtt_if_available_skips_unsupported_agent() -> None:
    import asyncio

    assert asyncio.run(
        mqtt_migration.async_migrate_legacy_mqtt_if_available(_UnsupportedApi())
    ) == {"ok": True, "available": False, "skipped": "unsupported"}


def test_migrate_legacy_mqtt_for_connection_builds_temporary_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    calls: dict[str, Any] = {}
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: "session"
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.aiohttp_client",
        aiohttp_client,
    )

    class _Api:
        def __init__(
            self,
            session: Any,
            base_url: str,
            api_token: str,
            *,
            maintenance_token: str,
        ) -> None:
            calls.update(
                {
                    "session": session,
                    "base_url": base_url,
                    "api_token": api_token,
                    "maintenance_token": maintenance_token,
                }
            )

        async def async_migrate_legacy_mqtt_to_native(self) -> dict[str, Any]:
            return {"ok": True}

    monkeypatch.setattr(mqtt_migration, "C300XAgentApi", _Api)

    result = asyncio.run(
        mqtt_migration.async_migrate_legacy_mqtt_for_connection(
            object(),
            {"agent_host": "agent.local", "agent_port": 8099},
            api_token="api-token",
            maintenance_token="maintenance-token",
        )
    )

    assert result == {"ok": True}
    assert calls == {
        "session": "session",
        "base_url": "http://agent.local:8099",
        "api_token": "api-token",
        "maintenance_token": "maintenance-token",
    }
