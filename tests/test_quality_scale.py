"""Offline contract checks for the local quality-scale self-assessment."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_quality_scale.py"


@pytest.fixture
def checker(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("quality_scale_checker", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_docs(checker, statuses):
    rows = "\n".join(
        f"| `{rule}` | {checker.RULE_TIERS[rule]} | {status} | Specific evidence or remaining work. |"
        for rule, status in statuses.items()
    )
    return (
        "# Local self-assessment\n\nReviewed: 2026-11-16\n\n"
        f"[Official source]({checker.OFFICIAL_SOURCE})\n\n"
        "## Rule Audit\n\n"
        "| Rule | Tier | Status | Evidence / Remaining Work |\n"
        "| --- | --- | --- | --- |\n"
        f"{rows}\n\n## Other Notes\n"
    )


def install_tracking(checker, monkeypatch, tmp_path, yaml_text, docs):
    quality = tmp_path / "quality_scale.yaml"
    document = tmp_path / "quality-scale.md"
    quality.write_text(yaml_text, encoding="utf-8")
    document.write_text(docs, encoding="utf-8")
    monkeypatch.setattr(checker, "QUALITY_SCALE", quality)
    monkeypatch.setattr(checker, "QUALITY_DOC", document)


def test_official_rule_snapshot_and_tiers(checker):
    assert len(checker.OFFICIAL_RULES) == len(set(checker.OFFICIAL_RULES)) == 54
    assert Counter(checker.RULE_TIERS.values()) == {
        "Bronze": 20, "Silver": 10, "Gold": 21, "Platinum": 3,
    }
    assert checker.RULE_TIERS["docs-conditions"] == "Bronze"
    assert checker.RULE_TIERS["docs-triggers"] == "Bronze"
    assert checker.RULE_TIERS["config-flow-test-coverage"] == "Bronze"
    assert checker.RULE_TIERS["test-coverage"] == "Silver"
    assert checker.RULE_TIERS["discovery-update-info"] == "Gold"
    assert checker.RULE_TIERS["async-dependency"] == "Platinum"


def test_current_repository_tracking_is_consistent(checker):
    assert checker.validate_quality_scale() == []


@pytest.mark.parametrize("text", [
    'rules: {action-setup: "done"}\n',
    'rules:\n    action-setup: done # inline comment\n',
    "rules:\n  action-setup:\n    comment: >-\n      Evidence can span\n      several lines.\n    status: done\n",
    "rules:\n  action-setup: {status: done, comment: 'Evidence: source and tests'}\n",
])
def test_yaml_accepts_official_forms_and_real_yaml_formatting(checker, text):
    assert checker.parse_quality_scale(text) == {"action-setup": "done"}


def test_yaml_accepts_anchored_status_without_losing_rule_identity(checker):
    assert checker.parse_quality_scale("rules: {action-setup: &state todo, brands: *state}") == {
        "action-setup": "todo", "brands": "todo",
    }


@pytest.mark.parametrize("text, message", [
    ("", "only the rules mapping"),
    ("[]", "only the rules mapping"),
    ("not_rules: {action-setup: done}", "only the rules mapping"),
    ("rules: {}\nextra: true", "only the rules mapping"),
    ("rules:", "nonempty mapping"),
    ("rules: []", "nonempty mapping"),
    ("rules: {}", "nonempty mapping"),
    ("rules: [", "Invalid quality_scale.yaml"),
    ("rules: {action-setup: done}\n---\nrules: {brands: todo}", "Invalid quality_scale.yaml"),
    ("rules: {action-setup: yes}", "status must be a string"),
    ("rules: {action-setup: null}", "status must be a string"),
    ("rules: {action-setup: []}", "status must be a string"),
    ("rules: {action-setup: {comment: evidence}}", "expected status"),
    ("rules: {action-setup: {status: done, typo: evidence}}", "expected status"),
    ("rules: {action-setup: {status: done, comment: false}}", "nonempty string"),
    ("rules: {action-setup: {status: done, comment: ' '}}", "nonempty string"),
    ("rules: {action-setup: exempt}", "exempt requires a comment"),
    ("rules: {action-setup: {status: exempt}}", "exempt requires a comment"),
    ("rules: {action-setup: {status: exempt, comment: null}}", "nonempty string"),
    ("rules: {123: done}", "keys must be strings"),
    ("rules: {? [action, setup]: done}", "keys must be strings"),
    ("rules: {action-setup: done, action-setup: todo}", "duplicate key: action-setup"),
    ("rules: {action-setup: {status: done, status: todo}}", "duplicate key: status"),
    ("rules: {action-setup: done}\nrules: {brands: todo}", "duplicate key: rules"),
    ("rules: {action-setup: {status: exempt, comment: one, comment: two}}", "duplicate key: comment"),
    ("rules: {action-setup: !!python/object:builtins.object {}}", "Invalid quality_scale.yaml"),
    ("rules: {action-setup: &self {status: *self}}", "Invalid quality_scale.yaml"),
])
def test_yaml_rejects_ambiguous_or_malformed_tracking(checker, text, message):
    with pytest.raises(ValueError, match=message):
        checker.parse_quality_scale(text)


def test_exemption_requires_reason_but_todo_does_not_require_fixed_blocker_set(checker):
    text = "rules: {action-setup: {status: exempt, comment: No actions provided.}, brands: todo}"
    assert checker.parse_quality_scale(text) == {"action-setup": "exempt", "brands": "todo"}


@pytest.mark.parametrize("status", ["done", "todo"])
def test_any_documented_todo_or_completed_rule_is_allowed(checker, monkeypatch, tmp_path, status):
    statuses = dict.fromkeys(checker.OFFICIAL_RULES, status)
    install_tracking(checker, monkeypatch, tmp_path,
                     yaml.safe_dump({"rules": statuses}), audit_docs(checker, statuses))
    assert checker.validate_quality_scale() == []


def test_rule_validation_reports_missing_unknown_and_invalid_status(checker):
    statuses = dict.fromkeys(checker.OFFICIAL_RULES, "done")
    statuses.pop("docs-triggers")
    statuses["not-official"] = "done"
    statuses["brands"] = "finished"
    failures = checker.validate_rules(statuses)
    assert any("missing official rule(s): docs-triggers" in failure for failure in failures)
    assert any("unknown rule(s): not-official" in failure for failure in failures)
    assert any("brands=finished" in failure for failure in failures)


@pytest.mark.parametrize("old,new,message", [
    ("| `brands` | Bronze | todo | Specific evidence or remaining work. |\n", "", "missing audit rule: brands"),
    ("| `brands` | Bronze | todo", "| `brands` | Bronze | done", "Audit status mismatch for brands"),
    ("| `brands` | Bronze", "| `brands` | Platinum", "Audit tier mismatch for brands"),
    ("| `brands` | Bronze | todo | Specific evidence or remaining work. |",
     "| `brands` | Bronze | todo | |", "Audit evidence or remaining work missing for brands"),
    ("| `brands` |", "| `unknown` |", "Unknown quality-scale audit rule: unknown"),
    ("| `brands` | Bronze | todo | Specific evidence or remaining work. |",
     "| `brands` | Bronze | todo |", "Malformed quality-scale audit row"),
    ("## Rule Audit", "## Former Audit", "must have one Rule Audit section"),
])
def test_audit_table_cannot_hide_drift(checker, old, new, message):
    statuses = dict.fromkeys(checker.OFFICIAL_RULES, "todo")
    docs = audit_docs(checker, statuses)
    assert old in docs
    assert any(message in failure for failure in checker.validate_audit(statuses, docs.replace(old, new)))


def test_duplicate_audit_sections_and_rows_are_rejected(checker):
    statuses = {"brands": "todo"}
    docs = audit_docs(checker, statuses)
    assert any("one Rule Audit" in failure for failure in checker.validate_audit(statuses, docs + "\n## Rule Audit\n"))
    row = "| `brands` | Bronze | todo | Specific evidence or remaining work. |"
    assert any("Duplicate quality-scale audit rule: brands" in failure
               for failure in checker.validate_audit(statuses, docs.replace(row, row + "\n" + row)))


@pytest.mark.parametrize("old,new", [
    ("Reviewed: 2026-11-16", "Reviewed: yesterday"),
    ("Reviewed: 2026-11-16", "Reviewed: 2026-02-30"),
    ("Reviewed: 2026-11-16", "Reviewed: 2026-11-16\nReviewed: 2026-11-16"),
    ("https://contributors.home-assistant.io/core/quality-scale/", "https://example.invalid/"),
])
def test_source_and_review_date_are_required(checker, old, new):
    docs = audit_docs(checker, {"brands": "todo"})
    assert checker.validate_documentation(docs) == []
    assert checker.validate_documentation(docs.replace(old, new))


def test_missing_and_invalid_files_are_validation_failures(checker, monkeypatch, tmp_path):
    install_tracking(checker, monkeypatch, tmp_path, "rules: [", "")
    assert checker.validate_quality_scale()[0].startswith("Invalid quality_scale.yaml")
    checker.QUALITY_SCALE.write_bytes(b"\xff")
    assert checker.validate_quality_scale()
    checker.QUALITY_SCALE.unlink()
    assert checker.validate_quality_scale()


@pytest.mark.parametrize("valid", [True, False])
def test_cli_reports_success_or_structural_failure_without_traceback(checker, tmp_path, valid):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
    (scripts / "check_reporting.py").write_bytes((SCRIPT.parent / "check_reporting.py").read_bytes())
    quality = tmp_path / "custom_components/bticino_c300x/quality_scale.yaml"
    quality.parent.mkdir(parents=True)
    quality.write_text(checker.QUALITY_SCALE.read_text() if valid else "rules: [", encoding="utf-8")
    docs = tmp_path / "docs/quality-scale.md"
    docs.parent.mkdir()
    docs.write_text(checker.QUALITY_DOC.read_text(), encoding="utf-8")
    result = subprocess.run([sys.executable, str(scripts / SCRIPT.name)], capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if valid else 1), result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert ("Quality scale validation passed" if valid else "Invalid quality_scale.yaml") in result.stdout + result.stderr
