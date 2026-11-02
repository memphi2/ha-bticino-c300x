"""Verify migrated unit tests against HA without legacy module stubs."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", ["test_executor", "test_init_runtime", "test_config_flow_helpers", "test_config_flow_forms"])
def test_unit_tests_preserve_home_assistant_modules(module):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import sys

import pytest

attributes = {
    "homeassistant.config_entries": ("ConfigEntry",),
    "homeassistant.core": ("HomeAssistant", "callback"),
    "homeassistant.exceptions": ("HomeAssistantError", "ServiceValidationError"),
    "homeassistant.helpers.selector": ("SelectSelector", "EntitySelector"),
    "homeassistant.helpers.config_validation": ("ensure_list",),
    "homeassistant.helpers.dispatcher": ("async_dispatcher_send",),
    "homeassistant.helpers.aiohttp_client": ("async_get_clientsession",),
    "homeassistant.components.http": ("HomeAssistantView",),
    "homeassistant.components.webhook": ("async_register",),
    "homeassistant.helpers": ("selector",),
}
modules = {name: importlib.import_module(name) for name in attributes}
originals = {
    (name, attr): getattr(modules[name], attr)
    for name, attrs in attributes.items() for attr in attrs
}
assert pytest.main([sys.argv[1]]) == 0
for name, original in modules.items():
    assert sys.modules[name] is original, name
for (name, attr), original in originals.items():
    assert getattr(modules[name], attr) is original, (name, attr)
""",
            f"tests/{module}.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Task exception was never retrieved" not in result.stderr, result.stderr
