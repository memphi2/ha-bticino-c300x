"""Guard the read-only display boundary without importing Home Assistant."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components/bticino_c300x"


def test_display_and_command_modules_have_one_way_dependencies():
    for module in ("dashboard", "dashboard_config", "alarm_state", "executor"):
        tree = ast.parse((ROOT / f"{module}.py").read_text())
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 1
        }
        assert "executor" not in imports
        if module != "dashboard":
            assert "dashboard" not in imports


def test_display_builders_cannot_dispatch_commands_directly():
    for module in ("dashboard", "dashboard_config", "alarm_state"):
        tree = ast.parse((ROOT / f"{module}.py").read_text())
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & {
            "async_call",
            "async_fire",
            "async_unlock_door",
            "async_stair_light",
        }
