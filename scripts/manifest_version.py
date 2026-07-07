#!/usr/bin/env python3
"""Shared helper for reading the packaged integration version."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "custom_components" / "bticino_c300x" / "manifest.json"


def read_integration_version(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> str:
    """Return the manifest.json version string, or raise if it is missing/invalid."""

    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ValueError("manifest.json version must be a string")
    return version
