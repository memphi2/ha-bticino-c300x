"""All display-dependent HA consumers must respect the Qt 5 fallback state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.bticino_c300x import repair_issues
from custom_components.bticino_c300x.button import _gui_required_action_available
from custom_components.bticino_c300x.capabilities import qml_patch_status_is_active
from custom_components.bticino_c300x.const import CONF_DEVICE_UI_ENABLED


@pytest.mark.parametrize("overlay,running,expected", [
    (None, False, True), ("active", True, True), ("active", False, False),
    ("failed", True, False), ("incomplete", True, False), ("off", True, False),
])
def test_gui_action_availability_uses_activation(overlay: str | None, running: bool, expected: bool) -> None:
    status = {"patched": True, "qt5_overlay": overlay, "gui_running": running}
    entry = SimpleNamespace(options={CONF_DEVICE_UI_ENABLED: True},
                            runtime_data=SimpleNamespace(qml_patch_status=status))
    assert qml_patch_status_is_active(status) is expected
    assert _gui_required_action_available(entry) is expected


@pytest.mark.parametrize("overlay", ["failed", "incomplete", "off"])
def test_inactive_core_overlay_keeps_repair_issue(monkeypatch: pytest.MonkeyPatch, overlay: str) -> None:
    create, delete = Mock(), Mock()
    monkeypatch.setattr(repair_issues, "_entry_media_enabled", lambda entry: True)
    monkeypatch.setattr(repair_issues, "_create_issue", create)
    monkeypatch.setattr(repair_issues, "async_delete_repair_issue", delete)
    entry = SimpleNamespace(entry_id="test", runtime_data=SimpleNamespace(
        capabilities={"maintenance": {"supported": True, "qml_core_patch": True}},
        qml_patch_status={"core_state": "patched", "core_patched": True, "qt5_overlay": overlay, "gui_running": True},
        diagnostics=SimpleNamespace(qml_patch_diagnostics=SimpleNamespace(last_error=None)),
    ))
    repair_issues._sync_device_core_qml_hook_issue(SimpleNamespace(), entry)
    create.assert_called_once()
    delete.assert_not_called()
