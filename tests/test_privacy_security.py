from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402


def test_repository_has_no_private_hosts_or_token_literals() -> None:
    assert check_repo.check_forbidden_text_patterns() == []


def test_forbidden_text_findings_do_not_echo_matched_value(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    matched_value = "do-not-log-this-value"
    test_file = tmp_path / "config.yaml"
    test_file.write_text("pass" + f"word: '{matched_value}'\n", encoding="utf-8")
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)

    findings = check_repo.check_forbidden_text_patterns()

    assert findings == [
        "possible secret/internal value (password_assignment) in config.yaml"
    ]
    assert matched_value not in findings[0]


def test_repository_security_and_privacy_docs_cover_required_topics() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    legal = (ROOT / "docs" / "legal.md").read_text(encoding="utf-8")

    assert "Token Handling" in security
    assert "Maintenance Surface" in security
    assert "private hosts" in security
    assert "Local Data Flow" in privacy
    assert "Diagnostics" in privacy
    assert "callback URLs" in privacy
    assert "No firmware or APK payloads" in legal
    assert "No vendored third-party controller code" in legal
    assert "Trademark notice" in legal
    assert "Apache License, Version 2.0" in legal
    assert (ROOT / "NOTICE").exists()


def test_manifest_does_not_publish_personal_owner_metadata() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/bticino_c300x/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["codeowners"] == []
    assert "bticino-c300x" in manifest["documentation"]
    assert "bticino-c300x" in manifest["issue_tracker"]


def test_manifest_loads_required_webhook_dependency() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/bticino_c300x/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert "webhook" in manifest["dependencies"]
    assert "webhook" not in manifest.get("after_dependencies", [])


def test_manifest_loads_required_go2rtc_dependency() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/bticino_c300x/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert "go2rtc" in manifest["dependencies"]
    assert "go2rtc" not in manifest.get("after_dependencies", [])
