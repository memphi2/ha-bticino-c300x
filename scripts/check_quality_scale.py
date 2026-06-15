#!/usr/bin/env python3
"""Validate local Home Assistant quality-scale tracking.

This is intentionally small and dependency-free so it can run in the same
minimal validation environment as the rest of the repository checks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCALE = ROOT / "custom_components" / "bticino_c300x" / "quality_scale.yaml"
QUALITY_DOC = ROOT / "docs" / "quality-scale.md"

OFFICIAL_RULES = (
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    "async-dependency",
    "inject-websession",
    "strict-typing",
)

EXPECTED_PLATINUM_BLOCKERS = {
    "brands",
    "config-flow-test-coverage",
    "test-coverage",
    "strict-typing",
}

VALID_STATUSES = {"done", "todo", "exempt"}
SCALAR_RULE_RE = re.compile(r"^  (?P<rule>[a-z0-9-]+): (?P<status>[a-z]+)$")
MAPPING_RULE_RE = re.compile(r"^  (?P<rule>[a-z0-9-]+):$")
STATUS_RE = re.compile(r"^    status: (?P<status>[a-z]+)$")


def main() -> int:
    failures = validate_quality_scale()
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    sys.stdout.write("Quality scale validation passed\n")
    return 0


def validate_quality_scale() -> list[str]:
    statuses = parse_quality_scale(QUALITY_SCALE.read_text(encoding="utf-8"))
    docs = QUALITY_DOC.read_text(encoding="utf-8")

    failures: list[str] = []
    failures.extend(validate_rules(statuses))
    failures.extend(validate_blockers(statuses, docs))
    failures.extend(validate_documentation(docs))
    return failures


def parse_quality_scale(text: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    current_rule: str | None = None
    for line in text.splitlines():
        scalar = SCALAR_RULE_RE.match(line)
        if scalar:
            statuses[scalar.group("rule")] = scalar.group("status")
            current_rule = None
            continue

        mapping = MAPPING_RULE_RE.match(line)
        if mapping:
            current_rule = mapping.group("rule")
            continue

        status = STATUS_RE.match(line)
        if status and current_rule:
            statuses[current_rule] = status.group("status")
            current_rule = None
    return statuses


def validate_rules(statuses: dict[str, str]) -> list[str]:
    failures: list[str] = []
    expected = set(OFFICIAL_RULES)
    actual = set(statuses)

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        failures.append(f"quality_scale.yaml missing official rule(s): {', '.join(missing)}")
    if extra:
        failures.append(f"quality_scale.yaml has unknown rule(s): {', '.join(extra)}")

    invalid = sorted(
        f"{rule}={status}"
        for rule, status in statuses.items()
        if status not in VALID_STATUSES
    )
    if invalid:
        failures.append(f"quality_scale.yaml has invalid status value(s): {', '.join(invalid)}")

    unexpected_todo = sorted(
        rule
        for rule, status in statuses.items()
        if status == "todo" and rule not in EXPECTED_PLATINUM_BLOCKERS
    )
    if unexpected_todo:
        failures.append(
            "quality_scale.yaml has undocumented TODO blocker(s): "
            + ", ".join(unexpected_todo)
        )
    return failures


def validate_blockers(statuses: dict[str, str], docs: str) -> list[str]:
    failures: list[str] = []
    blockers = {rule for rule, status in statuses.items() if status == "todo"}
    if blockers != EXPECTED_PLATINUM_BLOCKERS:
        failures.append(
            "quality_scale.yaml TODO blockers drifted from the audited Platinum blocker set: "
            + ", ".join(sorted(blockers))
        )

    for blocker in sorted(EXPECTED_PLATINUM_BLOCKERS):
        if f"`{blocker}`" not in docs:
            failures.append(f"docs/quality-scale.md does not document blocker `{blocker}`")
    return failures


def validate_documentation(docs: str) -> list[str]:
    failures: list[str] = []
    required_phrases = (
        "Target: Platinum",
        "Current status: Not Platinum yet",
        "Platinum Blockers",
    )
    for phrase in required_phrases:
        if phrase not in docs:
            failures.append(f"docs/quality-scale.md missing phrase: {phrase}")

    stale_phrases = (
        "No entities are exposed yet",
        "no entities are exposed yet",
        "No noisy entities are exposed yet",
    )
    for phrase in stale_phrases:
        if phrase in docs:
            failures.append(f"docs/quality-scale.md contains stale entity-free claim: {phrase}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
