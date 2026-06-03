from __future__ import annotations

# ruff: noqa: E402,I001

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

homeassistant = sys.modules.setdefault(
    "homeassistant",
    types.ModuleType("homeassistant"),
)
components = sys.modules.setdefault(
    "homeassistant.components",
    types.ModuleType("homeassistant.components"),
)
webhook = types.ModuleType("homeassistant.components.webhook")
config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))


class ConfigEntry:  # pragma: no cover - import-time stub only
    pass


class HomeAssistant:  # pragma: no cover - import-time stub only
    pass


webhook.async_generate_url = (
    lambda _hass, webhook_id, **_kwargs: f"http://homeassistant.local:8123/api/webhook/{webhook_id}"
)
components.webhook = webhook
config_entries.ConfigEntry = ConfigEntry
core.HomeAssistant = HomeAssistant
core.callback = lambda func: func
sys.modules["homeassistant.components.webhook"] = webhook

helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers_config_validation = sys.modules.setdefault(
    "homeassistant.helpers.config_validation",
    types.ModuleType("homeassistant.helpers.config_validation"),
)
helpers_dispatcher = sys.modules.setdefault(
    "homeassistant.helpers.dispatcher",
    types.ModuleType("homeassistant.helpers.dispatcher"),
)
helpers_entity = sys.modules.setdefault(
    "homeassistant.helpers.entity",
    types.ModuleType("homeassistant.helpers.entity"),
)
if not hasattr(helpers_dispatcher, "async_dispatcher_connect"):
    helpers_dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
if not hasattr(helpers_config_validation, "config_entry_only_config_schema"):
    helpers_config_validation.config_entry_only_config_schema = lambda _domain: dict
if not hasattr(helpers_entity, "Entity"):

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    helpers_entity.Entity = Entity
    helpers_entity.DeviceInfo = DeviceInfo
helpers.config_validation = helpers_config_validation
helpers.dispatcher = helpers_dispatcher
helpers.entity = helpers_entity

from custom_components.bticino_c300x import callback_url as callback_url_module
from custom_components.bticino_c300x.callback_url import (
    _preferred_source_ip,
    _replace_url_host,
    apply_callback_base_url,
    async_generate_agent_callback_url,
    normalize_callback_base_url,
)
from custom_components.bticino_c300x.const import CONF_CALLBACK_BASE_URL

TEST_NET_IPV4 = "203.0.113.20"
TEST_NET_IPV6 = "2001:db8::10"


def _restore_callback_webhook_stub() -> None:
    components.webhook = webhook
    sys.modules["homeassistant.components.webhook"] = webhook


@dataclass
class _FakeEntry:
    data: dict[str, Any] = field(
        default_factory=lambda: {"agent_host": "c300x.local", "agent_port": 8091}
    )
    options: dict[str, Any] = field(default_factory=dict)


class _FakeHass:
    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)


def test_preferred_source_ip_uses_ipv4_before_ipv6() -> None:
    assert _preferred_source_ip([TEST_NET_IPV6, TEST_NET_IPV4]) == TEST_NET_IPV4


def test_replace_url_host_brackets_ipv6() -> None:
    assert _replace_url_host(
        callback_url_module.urlsplit("http://homeassistant.local:8123/api/webhook/x"),
        TEST_NET_IPV6,
    ) == f"http://[{TEST_NET_IPV6}]:8123/api/webhook/x"


def test_normalize_callback_base_url_accepts_plain_http_endpoint() -> None:
    assert (
        normalize_callback_base_url(" http://192.0.2.10:8123/ ")
        == "http://192.0.2.10:8123"
    )


def test_normalize_callback_base_url_accepts_missing_port() -> None:
    assert normalize_callback_base_url("http://192.0.2.10") == "http://192.0.2.10"


@pytest.mark.parametrize(
    "value",
    [
        "https://192.0.2.10:8123",
        "http://homeassistant.local:8123",
        "http://127.0.0.1:8123",
        "http://0.0.0.0:8123",
        "http://[::]:8123",
        "http://[fe80::1]:8123",
        "http://192.0.2.10:8123/api",
        "http://user:pass@192.0.2.10:8123",
        "http://192.0.2.10:",
        "http://192.0.2.10:bad",
        "http://192.0.2.10:99999",
        "http://192.0.2.10:0",
        "http://[2001:db8::10]:bad",
    ],
)
def test_normalize_callback_base_url_rejects_unusable_targets(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_callback_base_url(value)


def test_apply_callback_base_url_preserves_generated_webhook_path() -> None:
    assert (
        apply_callback_base_url(
            "http://homeassistant.local:8123/api/webhook/display-hook?x=1",
            "http://192.0.2.10:8123",
        )
        == "http://192.0.2.10:8123/api/webhook/display-hook?x=1"
    )


def test_agent_callback_url_rewrites_homeassistant_local_to_route_source() -> None:
    _restore_callback_webhook_stub()
    original_selector = callback_url_module._select_non_link_local_source_ip
    callback_url_module._select_non_link_local_source_ip = lambda *_args: TEST_NET_IPV4
    try:
        result = asyncio.run(
            async_generate_agent_callback_url(
                _FakeHass(),  # type: ignore[arg-type]
                _FakeEntry(),  # type: ignore[arg-type]
                "display-hook",
            )
        )
    finally:
        callback_url_module._select_non_link_local_source_ip = original_selector

    parsed = callback_url_module.urlsplit(result)
    assert parsed.hostname == TEST_NET_IPV4
    assert parsed.port == 8123
    assert parsed.path.endswith("/display-hook")


def test_agent_callback_url_uses_configured_base_before_route_rewrite() -> None:
    _restore_callback_webhook_stub()
    original_selector = callback_url_module._select_non_link_local_source_ip
    callback_url_module._select_non_link_local_source_ip = lambda *_args: pytest.fail(
        "configured callback base URL must not need route source probing"
    )
    try:
        result = asyncio.run(
            async_generate_agent_callback_url(
                _FakeHass(),  # type: ignore[arg-type]
                _FakeEntry(
                    options={CONF_CALLBACK_BASE_URL: "http://192.0.2.10:8123"}
                ),  # type: ignore[arg-type]
                "event-hook",
            )
        )
    finally:
        callback_url_module._select_non_link_local_source_ip = original_selector

    parsed = callback_url_module.urlsplit(result)
    assert parsed.hostname == "192.0.2.10"
    assert parsed.path.endswith("/event-hook")
