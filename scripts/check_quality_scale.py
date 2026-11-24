#!/usr/bin/env python3
"""Validate local Home Assistant quality-scale tracking.

This checks the tracking contract, not compliance or an official HA tier.
PyYAML is already a repository validation dependency. No network is used.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from check_reporting import report_failures

ROOT = Path(__file__).resolve().parents[1]
QUALITY_SCALE = ROOT / "custom_components" / "bticino_c300x" / "quality_scale.yaml"
QUALITY_DOC = ROOT / "docs" / "dev" / "quality-scale.md"

OFFICIAL_RULES = (
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
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

RULE_TIERS = dict(zip(OFFICIAL_RULES, ["Bronze"] * 20 + ["Silver"] * 10 + ["Gold"] * 21 + ["Platinum"] * 3, strict=True))
VALID_STATUSES = {"done", "todo", "exempt"}
OFFICIAL_SOURCE = "https://contributors.home-assistant.io/core/quality-scale/"


def _unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
    """Reject duplicate keys instead of silently discarding audit evidence."""
    loader.flatten_mapping(node)
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise ValueError("quality_scale.yaml mapping keys must be strings")
        if key in result:
            raise ValueError(f"quality_scale.yaml duplicate key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


def main() -> int:
    failures = validate_quality_scale()
    return report_failures(failures, "Quality scale validation passed")


def validate_quality_scale() -> list[str]:
    try:
        statuses = parse_quality_scale(QUALITY_SCALE.read_text(encoding="utf-8"))
        docs = QUALITY_DOC.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        return [str(error)]
    return validate_rules(statuses) + validate_audit(statuses, docs) + validate_documentation(docs)


def parse_quality_scale(text: str) -> dict[str, str]:
    """Read the HA scalar/mapping forms and enforce their structure."""
    try:
        loader = yaml.SafeLoader(text)
        try:
            # Keep the duplicate-key policy local; never change PyYAML globally.
            loader.yaml_constructors = dict(loader.yaml_constructors)
            loader.yaml_constructors[yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG] = _unique_mapping
            document = loader.get_single_data()
        finally:
            loader.dispose()
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid quality_scale.yaml: {error}") from error
    if not isinstance(document, dict) or set(document) != {"rules"}:
        raise ValueError("quality_scale.yaml must contain only the rules mapping")
    rules = document["rules"]
    if not isinstance(rules, dict) or not rules:
        raise ValueError("quality_scale.yaml rules must be a nonempty mapping")
    statuses: dict[str, str] = {}
    for rule, value in rules.items():
        comment = None
        if isinstance(value, dict):
            if "status" not in value or set(value) - {"status", "comment"}:
                raise ValueError(f"{rule}: expected status and optional comment only")
            if "comment" in value:
                comment = value["comment"]
                if not isinstance(comment, str) or not comment.strip():
                    raise ValueError(f"{rule}: comment must be a nonempty string")
            value = value["status"]
        if not isinstance(value, str):
            raise ValueError(f"{rule}: status must be a string")
        if value == "exempt" and comment is None:
            raise ValueError(f"{rule}: exempt requires a comment explaining why")
        statuses[rule] = value
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

    return failures


def validate_audit(statuses: dict[str, str], docs: str) -> list[str]:
    """Check the explicit audit table, allowing any honestly documented TODO."""
    failures: list[str] = []
    sections = re.split(r"(?m)^## Rule Audit\s*$", docs)
    if len(sections) != 2:
        return ["docs/dev/quality-scale.md must have one Rule Audit section"]
    table = re.split(r"(?m)^## ", sections[1], maxsplit=1)[0]
    seen: set[str] = set()
    for line in table.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        columns = [column.strip() for column in line.strip().split("|")[1:-1]]
        if columns == ["Rule", "Tier", "Status", "Evidence / Remaining Work"]:
            continue
        if columns and all(re.fullmatch(r":?-+:?", column) for column in columns):
            continue
        if len(columns) != 4 or not line.rstrip().endswith("|"):
            failures.append(f"Malformed quality-scale audit row: {line}")
            continue
        rule, tier, status, evidence = columns
        rule, status = rule.strip("`"), status.strip("`")
        if rule in seen:
            failures.append(f"Duplicate quality-scale audit rule: {rule}")
        seen.add(rule)
        if rule not in statuses:
            failures.append(f"Unknown quality-scale audit rule: {rule}")
        elif status != statuses[rule]:
            failures.append(f"Audit status mismatch for {rule}: {status} != {statuses[rule]}")
        if tier != RULE_TIERS.get(rule):
            failures.append(f"Audit tier mismatch for {rule}: {tier}")
        if not evidence:
            failures.append(f"Audit evidence or remaining work missing for {rule}")
    for rule in sorted(set(statuses) - seen):
        failures.append(f"docs/dev/quality-scale.md missing audit rule: {rule}")
    return failures


def validate_documentation(docs: str) -> list[str]:
    failures: list[str] = []
    reviewed = re.findall(r"(?m)^Reviewed: (\d{4}-\d{2}-\d{2})$", docs)
    try:
        if len(reviewed) != 1:
            raise ValueError
        date.fromisoformat(reviewed[0])
    except ValueError:
        failures.append("docs/dev/quality-scale.md needs one valid Reviewed: YYYY-MM-DD date")
    if OFFICIAL_SOURCE not in docs:
        failures.append("docs/dev/quality-scale.md must link the official quality-scale source")
    return failures


if __name__ == "__main__":
    sys.exit(main())
