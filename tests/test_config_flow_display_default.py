"""The Home Assistant pages on the display: on for a new C300X, kept for an entry."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.bticino_c300x.config_flow import BticinoC300XConfigFlow
from custom_components.bticino_c300x.const import (
    CONF_ACTIONS,
    CONF_AGENT_HOST,
    CONF_AGENT_PORT,
    CONF_AGENT_TOKEN,
    CONF_DEVICE_UI_ENABLED,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.device_profile import (
    C100X,
    QT4_ONDISK,
    QT5_ONDISK,
    QT5_RCC,
)
from custom_components.bticino_c300x.display_support import entry_display_supported
from tests.test_config_flow_helpers import _options_flow

_BRIDGE = {"display_bridge": {"supported": True}}
# A C300X whose own model name and display program disagree: the agent keeps
# the bridge but offers no Display patch (native_agent/src/config.c).
_NO_DISPLAY_PATCH = {**_BRIDGE, "maintenance": {"supported": True, "qml_patch": False}}
_C100X_CONFIRMED = {
    **_BRIDGE,
    "c100x_display": {"confirmed": True, "status_known": True},
}


def _default(form: dict[str, Any], key: str) -> Any:
    for marker in form["data_schema"].schema:
        if str(marker) == key:
            return marker.default()
    raise AssertionError(f"{key} is not in the form")


def _setup_form(agent_info: dict[str, Any]) -> dict[str, Any]:
    flow = BticinoC300XConfigFlow()
    flow.hass = None  # type: ignore[assignment]
    flow.async_show_form = lambda **kwargs: kwargs  # type: ignore[method-assign]
    flow._setup_agent_info = agent_info  # noqa: SLF001
    return asyncio.run(flow._async_show_user_dashboard_form(None, {}))  # noqa: SLF001


@pytest.mark.parametrize(
    "agent_info",
    [
        pytest.param({"display_kind": QT4_ONDISK, "capabilities": _BRIDGE}, id="1.7.x-2.0.2"),
        pytest.param({"display_kind": QT5_RCC, "capabilities": _BRIDGE}, id="3.0.6"),
        pytest.param({"capabilities": _BRIDGE}, id="no-display-kind"),
    ],
)
def test_a_new_c300x_with_a_display_offers_the_pages_switched_on(agent_info) -> None:
    form = _setup_form(agent_info)

    assert form["step_id"] == "user_dashboard"
    assert _default(form, CONF_DEVICE_UI_ENABLED) is True


@pytest.mark.parametrize(
    "agent_info",
    [
        # The C100X activates its pages separately, with a reboot.
        pytest.param({"model": C100X, "capabilities": _C100X_CONFIRMED}, id="c100x"),
        pytest.param({"display_kind": QT5_ONDISK, "capabilities": _C100X_CONFIRMED}, id="c100x-kind"),
        # A display the agent does not confirm stays as shipped.
        pytest.param({"capabilities": {}}, id="unknown-display"),
        pytest.param({"capabilities": {"display_bridge": {"supported": False}}}, id="no-display"),
        pytest.param({"display_kind": QT4_ONDISK, "capabilities": _NO_DISPLAY_PATCH}, id="no-display-patch"),
        pytest.param({}, id="no-agent-answer"),
    ],
)
def test_a_new_entry_without_a_confirmed_c300x_display_keeps_the_pages_off(agent_info) -> None:
    assert _default(_setup_form(agent_info), CONF_DEVICE_UI_ENABLED) is False


def test_an_entry_that_never_stored_the_setting_keeps_it_off_in_the_settings() -> None:
    """An update or opening the settings must not switch the pages on."""

    entry = SimpleNamespace(
        data={
            CONF_AGENT_HOST: "agent.local", CONF_AGENT_PORT: 8091, CONF_AGENT_TOKEN: "token",
            CONF_VIDEO_ENABLED: False, CONF_ACTIONS: {},
        },
        options={},
        runtime_data=SimpleNamespace(
            agent_info={"display_kind": QT4_ONDISK},
            capabilities=_BRIDGE,
            qml_patch_status={"available": True, "patched": False, "state": "original"},
            qml_patch_status_updated_at=None,
            api=None,
        ),
    )
    flow = _options_flow(entry)

    form = asyncio.run(flow.async_step_dashboard(None))

    assert form["step_id"] == "dashboard"
    assert _default(form, CONF_DEVICE_UI_ENABLED) is False
    assert CONF_DEVICE_UI_ENABLED not in entry.options
    assert CONF_DEVICE_UI_ENABLED not in entry.data


@pytest.mark.parametrize("qml_patch", [True, False])
def test_the_settings_offer_the_pages_only_with_the_display_patch(qml_patch) -> None:
    capabilities = {**_BRIDGE, "maintenance": {"supported": True, "qml_patch": qml_patch}}
    entry = SimpleNamespace(
        entry_id="entry", data={CONF_AGENT_HOST: "agent.local", CONF_AGENT_TOKEN: "token"},
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=SimpleNamespace(
            agent_info={"model": "C300X", "display_kind": QT4_ONDISK}, capabilities=capabilities,
            qml_patch_status={}, qml_patch_status_updated_at=None, api=None,
        ),
    )

    assert entry_display_supported(entry) is qml_patch
    form = asyncio.run(_options_flow(entry).async_step_dashboard(None))
    assert (form.get("reason") == "unsupported_display") is not qml_patch
    assert (form.get("step_id") == "dashboard") is qml_patch


def test_an_agent_without_maintenance_leaves_the_display_to_its_bridge() -> None:
    capabilities = {**_BRIDGE, "maintenance": {"supported": False, "qml_patch": False}}

    assert _default(_setup_form({"capabilities": capabilities}), CONF_DEVICE_UI_ENABLED) is True
