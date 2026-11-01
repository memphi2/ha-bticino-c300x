"""Keep public HA contracts usable across the supported release window."""

import ast
import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "bticino_c300x"


def test_flow_results_have_explicit_step_ids() -> None:
    methods = {
        "async_show_form", "async_show_menu", "async_show_progress", "async_external_step"
    }
    missing = []
    for path in COMPONENT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in methods
                and not any(keyword.arg == "step_id" for keyword in node.keywords)
            ):
                missing.append(f"{path.name}:{node.lineno}")
    assert not missing


def test_listener_does_not_combine_with_flow_reload_helpers() -> None:
    calls = {
        node.func.attr
        for path in COMPONENT.glob("config_flow*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "async_update_reload_and_abort" not in calls


def test_marketplace_metadata_and_package_assets() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["categories"] == ["security_safety.doorbells_intercoms"]
    assert manifest["domain"] == "bticino_c300x"
    for name in ("brand/icon.png", "brand/logo.png", "translations/en.json"):
        assert (COMPONENT / name).is_file()
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "ha-bticino-c300x.zip"


def test_deprecation_gate_allows_documentation_and_negative_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    gate = importlib.import_module("check_ha_deprecations")
    assert gate._skip_path(Path(__file__))
    assert gate._skip_path(ROOT / "docs" / "ha-2026.11-audit.md")
    assert gate._forbidden_token_failures(
        COMPONENT / "config_flow.py", "self.async_update_reload_and_abort(entry)"
    )
