#!/usr/bin/env python3
"""Reject Home Assistant APIs that are deprecated for the supported LTS line."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from check_reporting import report_failures

ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

TEXT_SUFFIXES = {
    ".c",
    ".h",
    ".js",
    ".json",
    ".md",
    ".py",
    ".qml",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".release",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}
FORBIDDEN_TOKENS = {
    "async_update_reload_and_abort": (
        "use async_update_and_abort() when an entry update listener is registered"
    ),
    "show_advanced_options": "advanced-mode flow branching is deprecated",
    "hass.helpers": "import Home Assistant helpers directly instead of hass.helpers",
    "hass.components": "import Home Assistant components directly instead of hass.components",
    "mwc-": "Material Web Components tags are not LTS-safe in HA frontend",
    "paper-": "Paper tags are not LTS-safe in HA frontend",
    "ha-fab": "ha-fab is not LTS-safe in HA frontend",
    "async_register_entity_service": "old entity-service registration API",
    "async_register_admin_service": "old service registration API",
    "async_register_platform_entity_service": "old platform entity-service API",
}
MQTT_QOS_NONE_RE = re.compile(r"\.async_publish\([^)]*\bqos\s*=\s*None", re.DOTALL)
MQTT_RETAIN_NONE_RE = re.compile(
    r"\.async_publish\([^)]*\bretain\s*=\s*None",
    re.DOTALL,
)


def main() -> int:
    failures = check_ha_deprecations()
    return report_failures(failures, "Home Assistant deprecation gate passed")


def check_ha_deprecations() -> list[str]:
    """Return HA deprecation and frontend compatibility failures."""

    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if _skip_path(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        failures.extend(_forbidden_token_failures(path, text))
        failures.extend(_mqtt_publish_failures(path, text))
    return failures


def _skip_path(path: Path) -> bool:
    if path.resolve() == THIS_FILE:
        return True
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return True
    relative = path.relative_to(ROOT)
    if any(part in IGNORED_PARTS for part in relative.parts):
        return True
    return _git_ignored(relative)


def _git_ignored(relative: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
        check=False,
    )
    return result.returncode == 0


def _forbidden_token_failures(path: Path, text: str) -> list[str]:
    return [
        f"{_relative(path)} must not use {token!r}: {reason}"
        for token, reason in FORBIDDEN_TOKENS.items()
        if token in text
    ]


def _mqtt_publish_failures(path: Path, text: str) -> list[str]:
    failures: list[str] = []
    if MQTT_QOS_NONE_RE.search(text):
        failures.append(f"{_relative(path)} must not publish MQTT messages with qos=None")
    if MQTT_RETAIN_NONE_RE.search(text):
        failures.append(
            f"{_relative(path)} must not publish MQTT messages with retain=None"
        )
    return failures


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
