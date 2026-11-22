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
