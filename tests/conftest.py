"""Keep shared HA validation aliases and exception types stable across tests."""

import sys

import homeassistant.const  # noqa: F401
import homeassistant.exceptions  # noqa: F401
import pytest

_HA_EXCEPTIONS = homeassistant.exceptions
_ERROR_TYPES = (
    _HA_EXCEPTIONS.HomeAssistantError,
    _HA_EXCEPTIONS.ServiceValidationError,
)


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
