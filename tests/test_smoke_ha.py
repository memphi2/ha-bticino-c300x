from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SMOKE_HA_PATH = ROOT / "scripts" / "smoke_ha.py"
PROJECT_VERSIONS_PATH = ROOT / "project-versions.json"

# smoke_ha.py imports the shared check_reporting helper as a plain top-level
# module, matching how it resolves when run directly (python scripts/foo.py
# puts its own directory on sys.path).
sys.path.insert(0, str(ROOT / "scripts"))


def _load_smoke_ha() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_ha_under_test", SMOKE_HA_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RuntimeClient:
    def __init__(self, *, ha_version: str, python_version: str) -> None:
        self._ha_version = ha_version
        self._python_version = python_version

    def get_json(self, path: str) -> dict[str, Any]:
        assert path == "/api/diagnostics/config_entry/entry-1"
        return {
            "home_assistant": {
                "python_version": self._python_version,
                "version": self._ha_version,
            }
        }


class _StatesClient:
    def __init__(self, entity_ids: set[str]) -> None:
        self._entity_ids = entity_ids

    def get_json(self, path: str) -> list[dict[str, str]]:
        assert path == "/api/states"
        return [
            {"entity_id": entity_id, "state": "ok"}
            for entity_id in sorted(self._entity_ids)
        ]


def test_smoke_ha_defaults_follow_project_versions(monkeypatch: Any) -> None:
    monkeypatch.delenv("HA_EXPECTED_VERSION_PREFIXES", raising=False)
    monkeypatch.delenv("HA_EXPECTED_PYTHON_PREFIXES", raising=False)
    versions = json.loads(PROJECT_VERSIONS_PATH.read_text(encoding="utf-8"))

    smoke_ha = _load_smoke_ha()

    assert tuple(dict.fromkeys((
        versions["min_homeassistant"].rsplit(".", maxsplit=1)[0] + ".",
        versions["current_homeassistant"].rsplit(".", maxsplit=1)[0] + ".",
    ))) == smoke_ha.EXPECTED_HA_VERSION_PREFIXES
    assert (versions["python"] + ".",) == smoke_ha.EXPECTED_PYTHON_PREFIXES


def test_smoke_ha_runtime_check_accepts_current_minor(monkeypatch: Any) -> None:
    monkeypatch.delenv("HA_EXPECTED_VERSION_PREFIXES", raising=False)
    monkeypatch.delenv("HA_EXPECTED_PYTHON_PREFIXES", raising=False)
    smoke_ha = _load_smoke_ha()

    assert smoke_ha.check_runtime(
        _RuntimeClient(ha_version="2026.9.99", python_version="3.14.4"),
        "entry-1",
    ) == []


def test_smoke_ha_runtime_check_rejects_unconfigured_minor(monkeypatch: Any) -> None:
    monkeypatch.delenv("HA_EXPECTED_VERSION_PREFIXES", raising=False)
    monkeypatch.delenv("HA_EXPECTED_PYTHON_PREFIXES", raising=False)
    smoke_ha = _load_smoke_ha()

    failures = smoke_ha.check_runtime(
        _RuntimeClient(ha_version="2026.7.9", python_version="3.14.4"),
        "entry-1",
    )

    assert failures == ["HA version 2026.7.9 does not match 2026.5.*, 2026.9.*"]


def test_smoke_ha_does_not_require_optional_ssh_maintenance_entity() -> None:
    smoke_ha = _load_smoke_ha()

    assert "switch.bticino_c300x_ssh" not in smoke_ha.REQUIRED_ENTITIES
    assert "switch.bticino_c300x_ssh" in smoke_ha.FORBIDDEN_ENTITIES
    assert smoke_ha.check_entities(_StatesClient(set(smoke_ha.REQUIRED_ENTITIES))) == []
