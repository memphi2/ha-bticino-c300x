"""The auth-config POST must refuse what the config loader refuses at the next start."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "native_agent" / "src"


def _token_required_flags(source: str, owner: str, anchor: str) -> set[str]:
    """Return the maintenance flags of the condition that ends at ``anchor``."""

    end = source.index(anchor)
    start = source.rindex(f"{owner}->maintenance_enabled", 0, end)
    return set(re.findall(rf"{owner}->(maintenance_\w+_enabled)", source[start:end])) - {
        "maintenance_enabled"
    }


def test_post_and_loader_require_the_maintenance_token_for_the_same_actions() -> None:
    loader = _token_required_flags(
        (SRC / "config.c").read_text(encoding="utf-8"),
        "config",
        '"maintenance.adminToken must be set when maintenance actions are enabled"',
    )
    post = _token_required_flags(
        (SRC / "http.c").read_text(encoding="utf-8"),
        "updated",
        '\\"error\\":\\"maintenance_token_required\\"',
    )

    assert loader, "loader condition not found"
    # A config the POST accepts and saves must not stop the agent from starting.
    assert post == loader
