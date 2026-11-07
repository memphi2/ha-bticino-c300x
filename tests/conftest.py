"""Keep shared HA validation aliases and exception types stable across tests."""

import sys
from types import SimpleNamespace

import homeassistant.components.camera  # noqa: F401
import homeassistant.const  # noqa: F401
import homeassistant.exceptions  # noqa: F401
import homeassistant.helpers.aiohttp_client  # noqa: F401
import homeassistant.helpers.selector  # noqa: F401
import pytest

_HA_EXCEPTIONS = homeassistant.exceptions
_ERROR_TYPES = (
    _HA_EXCEPTIONS.HomeAssistantError,
    _HA_EXCEPTIONS.ServiceValidationError,
)


@pytest.fixture
def entity_ha_boundary(monkeypatch):
    """Replace only HA I/O for entity unit tests, never HA modules or classes."""
    from homeassistant.helpers import dispatcher, entity_registry, event, issue_registry

    from custom_components.bticino_c300x.entity import C300XEntity

    monkeypatch.setattr(C300XEntity, "async_write_ha_state", lambda self: setattr(self, "wrote_state", True))
    monkeypatch.setattr(C300XEntity, "async_on_remove", lambda self, cancel: setattr(self, "_remove_callback", cancel))
    monkeypatch.setattr(dispatcher, "async_dispatcher_connect", lambda *_: lambda: None)
    monkeypatch.setattr(dispatcher, "async_dispatcher_send", lambda *_: None)
    monkeypatch.setattr(event, "async_call_later", lambda *_: lambda: None)
    monkeypatch.setattr(issue_registry, "async_create_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(issue_registry, "async_delete_issue", lambda *args, **kwargs: None)
    monkeypatch.setattr(entity_registry, "async_get", lambda _: SimpleNamespace(async_get=lambda _: None))
    for name in (
        "entity", "binary_sensor", "button", "number", "select", "sensor",
        "switch", "services", "agent_diagnostics", "use_cases.common",
    ):
        module = sys.modules.get(f"custom_components.bticino_c300x.{name}")
        if module is None:
            continue
        for attr, replacement in (
            ("async_dispatcher_connect", lambda *_: lambda: None),
            ("async_dispatcher_send", lambda *_: None),
            ("async_call_later", lambda *_: lambda: None),
        ):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, replacement)


@pytest.fixture(autouse=True)
def stable_home_assistant_exceptions():
    """Legacy entity stubs must not replace shared exception classes."""
    _check_exception_types()
    yield
    _check_exception_types()


def _check_exception_types():
    assert sys.modules["homeassistant.exceptions"] is _HA_EXCEPTIONS
    assert (
        _HA_EXCEPTIONS.HomeAssistantError,
        _HA_EXCEPTIONS.ServiceValidationError,
    ) == _ERROR_TYPES
