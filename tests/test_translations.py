from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "custom_components" / "bticino_c300x" / "translations"


def test_localized_translation_files_match_english_keys() -> None:
    english = _load_json(TRANSLATIONS / "en.json")

    for language in ("de", "it"):
        localized = _load_json(TRANSLATIONS / f"{language}.json")
        assert _leaf_paths(localized) == _leaf_paths(english)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if not isinstance(value, dict):
        return {prefix}

    paths: set[tuple[str, ...]] = set()
    for key, child in value.items():
        paths.update(_leaf_paths(child, (*prefix, key)))
    return paths
