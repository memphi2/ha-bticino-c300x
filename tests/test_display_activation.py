"""Activation evidence is not the same thing as installed Qt 5 files."""

import pytest

from custom_components.bticino_c300x.api_errors import C300XAgentApiError
from custom_components.bticino_c300x.display_activation import (
    display_activation_confirmed,
    require_display_activation,
)


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("overlay", [None, "active", "off", "failed", "incomplete", "unknown"])
@pytest.mark.parametrize("running", [True, False, None])
def test_confirmation_requires_activation_and_process_evidence(required, overlay, running):
    status = {"qt5_overlay": overlay, "gui_running": running}
    expected = overlay is None or (
        running is True and (overlay == "active" or (not required and overlay == "off"))
    )
    assert display_activation_confirmed(status, required=required) is expected
    if expected:
        require_display_activation(status, required=required)
    else:
        with pytest.raises(C300XAgentApiError, match="activation is not confirmed"):
            require_display_activation(status, required=required)


@pytest.mark.parametrize(("http_status", "agent_state", "failed"), [
    (502, "reload_failed", True),
    (504, None, True),
    (502, "script_missing", False),
    (502, "reload_script_missing", False),
    (409, "maintenance_busy", False),
])
def test_a_step_whose_script_is_missing_never_ran(http_status, agent_state, failed):
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
    from custom_components.bticino_c300x.display_activation import display_step_failed

    err = C300XAgentApiConnectionError("x", http_status=http_status, agent_state=agent_state)
    assert display_step_failed(err) is failed



@pytest.mark.parametrize(("body", "state"), [
    ('{"ok":false,"available":false,"state":"script_missing"}', "script_missing"),
    ('{"ok":false,"error":"reload_failed"}', "reload_failed"),
    ("not json", None),
])
def test_the_agents_error_answer_carries_its_state(body, state):
    import asyncio

    from custom_components.bticino_c300x.api import C300XAgentApi
    from custom_components.bticino_c300x.api_errors import C300XAgentApiConnectionError
    from tests.test_api import _FakeSession

    api = C300XAgentApi(_FakeSession(body, response_status=502),  # type: ignore[arg-type]
                        "http://agent.local:8080", "agent-token")
    with pytest.raises(C300XAgentApiConnectionError) as raised:
        asyncio.run(api.async_delete_memo("text/memo_1"))
    assert raised.value.http_status == 502
    assert raised.value.agent_state == state
