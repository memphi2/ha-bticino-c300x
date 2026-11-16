from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402


def test_repository_has_no_private_hosts_or_token_literals() -> None:
    assert check_repo.check_forbidden_text_patterns() == []


def test_only_local_browser_dependency_tree_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)
    browser_modules = tmp_path / "tests/browser/node_modules/example/dist"
    browser_modules.mkdir(parents=True)
    assert check_repo.check_forbidden_generated_paths() == []
    runtime_modules = tmp_path / "custom_components/bticino_c300x/node_modules"
    runtime_modules.mkdir(parents=True)
    assert check_repo.check_forbidden_generated_paths() == [
        "forbidden foreign/runtime directory present: custom_components/bticino_c300x/node_modules"
    ]


def test_marketplace_link_exception_does_not_allow_other_owner_text(
    tmp_path, monkeypatch,
) -> None:  # noqa: ANN001
    readme = tmp_path / "README.md"
    readme.write_text(check_repo.PUBLIC_REPOSITORY_URLS[-1], encoding="utf-8")
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)
    assert check_repo.check_forbidden_text_patterns() == []

    with readme.open("a", encoding="utf-8") as stream:
        stream.write("\nowner: " + "mem" + "phi2\n")
    assert check_repo.check_forbidden_text_patterns() == [
        "possible secret/internal value (personal_owner) in README.md"
    ]


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


def test_manifest_identifies_public_maintainer_without_private_metadata() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/bticino_c300x/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["codeowners"] == ["@mem" + "phi2"]
    assert "bticino-c300x" in manifest["documentation"]
    assert "bticino-c300x" in manifest["issue_tracker"]


def test_public_maintainer_handle_does_not_allow_private_owner_values(tmp_path, monkeypatch):
    path = tmp_path / "README.md"
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)
    handle = "@mem" + "phi2"
    path.write_text(handle, encoding="utf-8")
    assert check_repo.check_forbidden_text_patterns() == []
    for value in (handle[1:], handle + "-private", "@" + handle):
        path.write_text(value, encoding="utf-8")
        assert check_repo.check_forbidden_text_patterns() == [
            "possible secret/internal value (personal_owner) in README.md"
        ]


def test_config_entry_typing_checks_import_symbols_not_name_prefixes(tmp_path, monkeypatch):
    component = tmp_path / "custom_components/bticino_c300x"
    component.mkdir(parents=True)
    (component / "entry_types.py").write_text(
        "# type BticinoC300XConfigEntry = ConfigEntry[BticinoC300XRuntimeData]\n"
        "# BticinoC300XConfigEntry = Any\n", encoding="utf-8"
    )
    module = component / "example.py"
    monkeypatch.setattr(check_repo, "ROOT", tmp_path)
    module.write_text(
        "from homeassistant.config_entries import ConfigEntryState\n"
        "state = config_entries.ConfigEntryState.LOADED\n"
        "example_text = 'config_entries.ConfigEntry'\n"
        "def example(state: 'config_entries.ConfigEntryState'): pass\n", encoding="utf-8"
    )
    assert check_repo.check_config_entry_typing() == []
    for source in (
        "from homeassistant.config_entries import (ConfigEntryState, ConfigEntry as Entry)\n",
        "entry = config_entries.ConfigEntry\n",
        "def example(entry: 'config_entries.ConfigEntry'): pass\n",
        "def example() -> 'config_entries.ConfigEntry': pass\n",
        "entries: list['config_entries.ConfigEntry']\n",
        "type Entry = 'config_entries.ConfigEntry'\n",
        '''def example(entry: "list['config_entries.ConfigEntry']"): pass\n''',
    ):
        module.write_text(source, encoding="utf-8")
        assert len(check_repo.check_config_entry_typing()) == 1


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
