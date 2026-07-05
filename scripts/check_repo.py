#!/usr/bin/env python3
"""Local repository validation for ha-bticino-c300x."""

from __future__ import annotations

import compileall
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_CONFIG_PATH = ROOT / "project-versions.json"


def _load_version_config() -> dict[str, str]:
    data = json.loads(VERSION_CONFIG_PATH.read_text(encoding="utf-8"))
    required_keys = {
        "min_homeassistant",
        "current_homeassistant",
        "python",
        "c300x_firmware",
        "integration_version",
    }
    missing = sorted(required_keys.difference(data))
    if missing:
        raise RuntimeError(f"project-versions.json is missing keys: {', '.join(missing)}")
    return {key: str(data[key]) for key in required_keys}


VERSION_CONFIG = _load_version_config()
MIN_HOME_ASSISTANT_VERSION = VERSION_CONFIG["min_homeassistant"]
CURRENT_HOME_ASSISTANT_VERSION = VERSION_CONFIG["current_homeassistant"]
PYTHON_VERSION = VERSION_CONFIG["python"]
CURRENT_RELEASE_VERSION = VERSION_CONFIG["integration_version"]
REQUIRED_PARAMIKO_VERSION = "3.5.1"
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


def _version_minor_prefix(version: str) -> str:
    return version.rsplit(".", maxsplit=1)[0] + "."
CODE_SUFFIXES = {
    ".c",
    ".h",
    ".js",
    ".py",
    ".qml",
    ".sh",
}
JWT_PREFIX = "eyJ0" + "eXAiOiJKV1Qi"
PUBLIC_REPOSITORY_URL = "https://github.com/" + "mem" + "phi2/ha-bticino-c300x"
PUBLIC_REPOSITORY_URLS = (
    PUBLIC_REPOSITORY_URL,
    f"{PUBLIC_REPOSITORY_URL}/issues",
)

DENY_PATTERNS = {
    "bearer_token": re.compile(r"Authorization:\s*Bearer\s+", re.IGNORECASE),
    "home_assistant_token": re.compile(
        rf"{JWT_PREFIX}|\b" + "LL" + r"AT\b",
        re.IGNORECASE,
    ),
    "local_user_path": re.compile(
        r"/home/" + r"olli\b|/Users" + r"/[^/\s]+"
    ),
    "personal_owner": re.compile(r"\bmem" + r"phi2\b", re.IGNORECASE),
    "private_ipv4": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"
    ),
    "password_assignment": re.compile(r"\b(password|passwd|pwd)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
}
REQUIRED_PATHS = [
    "CHANGELOG.md",
    "LICENSE",
    "NOTICE",
    "PRIVACY.md",
    "SECURITY.md",
    "SUPPORT.md",
    ".github/dependabot.yml",
    ".github/codeql/codeql-config.yml",
    ".github/workflows/codeql.yml",
    "project-versions.json",
    "custom_components/bticino_c300x/manifest.json",
    "custom_components/bticino_c300x/brand/icon.png",
    "custom_components/bticino_c300x/brand/logo.png",
    "custom_components/bticino_c300x/quality_scale.yaml",
    "custom_components/bticino_c300x/config_flow.py",
    "custom_components/bticino_c300x/discovery.py",
    "custom_components/bticino_c300x/webhook.py",
    "custom_components/bticino_c300x/diagnostics.py",
    "custom_components/bticino_c300x/repair_issues.py",
    "docs/architecture.md",
    "docs/audits/current-legal-provenance.md",
    "docs/legal.md",
    "docs/native-agent.md",
    "docs/quality-scale.md",
    "docs/user-guide.md",
    "scripts/check_quality_scale.py",
    "scripts/check_coverage.py",
    "scripts/check_legal_audit.py",
    "scripts/check_release_tag.py",
    "scripts/check_typing.py",
    "scripts/check_validate.py",
    "scripts/update_frontend_hashes.py",
    "scripts/verify_media_reference_flow.py",
    "scripts/write_release_assets.py",
    "scripts/smoke_ha.py",
    "requirements-dev.in",
    "requirements-dev.txt",
    "requirements-dev-min-ha.txt",
    "hacs.json",
    "native_agent/Makefile",
    "native_agent/API.md",
    "native_agent/README.md",
    "native_agent/config.example.json",
    "native_agent/scripts/bootstrap_firewall.sh",
    "native_agent/scripts/qml_patch.sh",
    "native_agent/src/main.c",
    "native_agent/test/smoke.py",
    "device_qml/Alarm.qml",
    "device_qml/README.md",
    "device_qml/HomeAssistant.qml",
    "device_qml/js/c300x_ha.js",
    "device_qml/js/c300x_i18n.js",
    "device_qml/js/c300x_memos.js",
    f".github/release-notes/v{CURRENT_RELEASE_VERSION}.md",
    ".github/workflows/release.yml",
    ".github/workflows/validate.yml",
]
FORBIDDEN_GENERATED_PATHS = [
    "device_qml/HomePage.qml",
    "device_qml/MainApp.qml",
    "device_qml/MemoPage.qml",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "node_modules",
]
FORBIDDEN_REPO_DIRS = {
    "dist",
    "external",
    "extracted",
    "firmware",
    "node_modules",
    "original_firmware",
    "third_party",
    "vendor",
}
FORBIDDEN_PAYLOAD_SUFFIXES = {
    ".7z",
    ".a",
    ".apk",
    ".bin",
    ".deb",
    ".ext4",
    ".fwz",
    ".gz",
    ".img",
    ".ipk",
    ".o",
    ".rpm",
    ".so",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}


def main() -> int:
    failures: list[str] = []
    failures.extend(check_required_paths())
    failures.extend(check_forbidden_generated_paths())
    failures.extend(check_forbidden_payloads())
    failures.extend(check_tracked_runtime_artifacts())
    failures.extend(check_json_files())
    failures.extend(check_native_agent_example_config())
    failures.extend(check_secret_patterns())
    failures.extend(check_legal_hygiene())
    failures.extend(check_current_audit_snapshot())
    failures.extend(check_release_metadata())
    failures.extend(check_smoke_ha_versions())
    failures.extend(check_installer_dependency_pins())
    failures.extend(check_hacs_metadata())
    failures.extend(check_frontend_bundle_hash())
    failures.extend(check_github_automation())
    failures.extend(check_python_runtime())
    failures.extend(check_quality_scale())
    failures.extend(check_media_reference_flow())
    failures.extend(check_python_compile())
    failures.extend(check_native_agent())
    if failures:
        for failure in failures:
            sys.stderr.write(f"FAIL: {failure}\n")
        return 1
    sys.stdout.write("Repository validation passed\n")
    return 0


def check_required_paths() -> list[str]:
    return [f"missing required path: {path}" for path in REQUIRED_PATHS if not (ROOT / path).exists()]


def check_forbidden_generated_paths() -> list[str]:
    failures = [
        f"forbidden generated/runtime artifact present: {path}"
        for path in FORBIDDEN_GENERATED_PATHS
        if (ROOT / path).exists()
    ]
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if _is_tooling_path(parts):
            continue
        if path.is_dir() and path.name in FORBIDDEN_REPO_DIRS:
            failures.append(
                f"forbidden foreign/runtime directory present: {relative(path)}"
            )
    return failures


def check_forbidden_payloads() -> list[str]:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if is_ignored(path):
            continue
        relative_parts = path.relative_to(ROOT).parts
        if path.is_dir() and path.name in FORBIDDEN_REPO_DIRS:
            failures.append(f"forbidden foreign/runtime directory present: {relative(path)}")
            continue
        if path.is_file() and path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
            failures.append(f"forbidden binary/firmware payload present: {relative(path)}")
        if (
            path.is_file()
            and len(relative_parts) > 1
            and any(part in FORBIDDEN_REPO_DIRS for part in relative_parts[:-1])
        ):
            failures.append(f"file inside forbidden foreign/runtime directory: {relative(path)}")
    return failures


def check_tracked_runtime_artifacts() -> list[str]:
    """Reject generated/runtime artifacts even if a future git add forces them in."""

    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return ["unable to inspect tracked files for runtime artifacts"]
    failures: list[str] = []
    for line in result.stdout.splitlines():
        path = Path(line)
        parts = path.parts
        suffix = path.suffix.lower()
        if parts[:2] == ("native_agent", "build"):
            failures.append(f"tracked native build artifact: {line}")
        elif suffix in FORBIDDEN_PAYLOAD_SUFFIXES:
            failures.append(f"tracked binary/firmware payload: {line}")
        elif any(part in FORBIDDEN_REPO_DIRS for part in parts):
            failures.append(f"tracked file inside forbidden runtime directory: {line}")
    return failures


def check_json_files() -> list[str]:
    failures: list[str] = []
    for path in ROOT.rglob("*.json"):
        if is_ignored(path):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            failures.append(f"invalid JSON in {relative(path)}: {err}")
    return failures


def check_native_agent_example_config() -> list[str]:
    """Keep the shipped native-agent sample in bootstrap-safe setup mode."""

    path = ROOT / "native_agent" / "config.example.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    api = config.get("api") if isinstance(config.get("api"), dict) else {}
    maintenance = (
        config.get("maintenance") if isinstance(config.get("maintenance"), dict) else {}
    )
    if api.get("token") != "":
        failures.append("native_agent/config.example.json must not ship an API token")
    if api.get("noAuth") is not True:
        failures.append("native_agent/config.example.json must bootstrap with api.noAuth=true")
    if maintenance.get("adminToken") != "":
        failures.append(
            "native_agent/config.example.json must not ship a maintenance token"
        )
    if maintenance.get("enabled") is not True:
        failures.append(
            "native_agent/config.example.json must enable maintenance for first setup"
        )
    if maintenance.get("allowNoAuth") is not True:
        failures.append(
            "native_agent/config.example.json must allow noAuth maintenance for first setup"
        )
    return failures


def check_secret_patterns() -> list[str]:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if is_ignored(path) or not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        text_for_secret_scan = text
        for public_url in PUBLIC_REPOSITORY_URLS:
            text_for_secret_scan = text_for_secret_scan.replace(public_url, "")
        for name, pattern in DENY_PATTERNS.items():
            if pattern.search(text_for_secret_scan):
                failures.append(f"possible secret/internal value ({name}) in {relative(path)}")
    return failures


def check_legal_hygiene() -> list[str]:
    """Reject foreign code/firmware payloads and require legal hygiene docs."""

    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return ["unable to inspect tracked files for legal hygiene"]

    failures: list[str] = []
    stock_qml_names = {"HomePage.qml", "MainApp.qml", "MemoPage.qml"}
    source_reference_markers = (
        "slyoldfox",
        "c300x-controller",
        "fquinto/bticinoClasse300x",
        "bticinoClasse300x",
    )
    documentation_paths = {
        "README.md",
        "CHANGELOG.md",
        "PRIVACY.md",
        "SECURITY.md",
        "scripts/check_repo.py",
        "scripts/check_validate.py",
    }

    for line in result.stdout.splitlines():
        rel = Path(line)
        path = ROOT / rel
        parts = rel.parts
        if rel.name in stock_qml_names and parts[:1] in {
            ("device_qml",),
            ("custom_components",),
        }:
            failures.append(f"stock/vendor QML page must not be tracked: {line}")
        if any(part in FORBIDDEN_REPO_DIRS for part in parts):
            failures.append(f"foreign/runtime directory must not be tracked: {line}")
        if not path.is_file() or path.suffix not in CODE_SUFFIXES:
            continue
        if parts and (parts[0] == "docs" or str(rel) in documentation_paths):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in source_reference_markers:
            if marker.lower() in text:
                failures.append(
                    f"third-party/reference marker {marker!r} belongs in docs, not code: {line}"
                )

    legal = ROOT / "docs" / "legal.md"
    if not legal.exists():
        return failures + ["missing legal hygiene document: docs/legal.md"]
    legal_text = legal.read_text(encoding="utf-8")
    required_legal_phrases = (
        "No firmware or APK payloads",
        "No vendored third-party controller code",
        "Media codecs and patents",
        "Trademark notice",
        "Apache License, Version 2.0",
    )
    for phrase in required_legal_phrases:
        if phrase not in legal_text:
            failures.append(f"docs/legal.md must mention {phrase!r}")
    return failures


def check_current_audit_snapshot() -> list[str]:
    """Require one current audit snapshot instead of accumulating old reports."""

    audit_dir = ROOT / "docs" / "audits"
    current = audit_dir / "current-legal-provenance.md"
    failures: list[str] = []
    if not current.is_file():
        failures.append("missing current legal/provenance audit snapshot")
    audit_files = sorted(path.name for path in audit_dir.glob("*.md"))
    if audit_files != ["current-legal-provenance.md"]:
        failures.append(
            "docs/audits must contain only current-legal-provenance.md, got "
            + ", ".join(audit_files)
        )
    return failures


def check_release_metadata() -> list[str]:
    failures: list[str] = []
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    version = str(manifest.get("version", ""))
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        failures.append("manifest version must be a stable semver release")
        return failures
    if version != CURRENT_RELEASE_VERSION:
        failures.append(
            f"release metadata must stay on {CURRENT_RELEASE_VERSION}, got {version}"
        )
    active_release_line = ".".join(version.split(".")[:2]) + ".x"
    release_tag = f"v{version}"
    release_note = ROOT / ".github" / "release-notes" / f"{release_tag}.md"
    required_mentions = {
        "README.md": version,
        "CHANGELOG.md": release_tag,
        str(release_note.relative_to(ROOT)): release_tag,
        "SECURITY.md": "Token Handling",
        "SUPPORT.md": active_release_line,
        "PRIVACY.md": "Local Data Flow",
        "LICENSE": "Apache License",
        "NOTICE": "BTicino C300X Home Assistant Integration",
    }
    for relative_path, expected in required_mentions.items():
        path = ROOT / relative_path
        if not path.exists():
            failures.append(f"missing release metadata file: {relative_path}")
            continue
        if expected not in path.read_text(encoding="utf-8"):
            failures.append(f"{relative_path} must mention {expected!r}")
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    if hacs.get("homeassistant") != MIN_HOME_ASSISTANT_VERSION:
        failures.append(
            f"hacs.json must advertise Home Assistant {MIN_HOME_ASSISTANT_VERSION}"
        )
    support = (ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    for expected in (
        f"Minimum Home Assistant: `{MIN_HOME_ASSISTANT_VERSION}`",
        "Validated Home Assistant: `2026.5.x` and `2026.7.x`",
        f"Python: `{PYTHON_VERSION}`",
        f"C300X firmware: `{VERSION_CONFIG['c300x_firmware']}`",
        "`native_agent/src`",
        "`scripts/stage_device_agent_bundle.py`",
    ):
        if expected not in support:
            failures.append(f"SUPPORT.md must mention {expected!r}")
    return failures


def check_smoke_ha_versions() -> list[str]:
    failures: list[str] = []
    smoke = (ROOT / "scripts" / "smoke_ha.py").read_text(encoding="utf-8")
    required_tokens = (
        "PROJECT_VERSIONS_PATH",
        'PROJECT_VERSIONS["min_homeassistant"]',
        'PROJECT_VERSIONS["current_homeassistant"]',
        'PROJECT_VERSIONS["python"]',
        "HA_EXPECTED_VERSION_PREFIXES",
        "HA_EXPECTED_PYTHON_PREFIXES",
    )
    for token in required_tokens:
        if token not in smoke:
            failures.append(f"scripts/smoke_ha.py must derive runtime defaults from project-versions.json: {token}")

    stale_ha_literals = sorted(
        {
            match.group(0)
            for match in re.finditer(r"\b20\d{2}\.\d+\.", smoke)
            if match.group(0)
            not in {
                _version_minor_prefix(MIN_HOME_ASSISTANT_VERSION),
                _version_minor_prefix(CURRENT_HOME_ASSISTANT_VERSION),
            }
        }
    )
    if stale_ha_literals:
        failures.append(
            "scripts/smoke_ha.py must not hardcode stale HA version prefix defaults: "
            + ", ".join(stale_ha_literals)
        )
    if 'PROJECT_VERSIONS_PATH.read_text(encoding="utf-8")' not in smoke:
        failures.append("scripts/smoke_ha.py must read project-versions.json with UTF-8")
    return failures


def check_installer_dependency_pins() -> list[str]:
    """Keep optional installer SSH support pinned without blocking HA setup."""

    failures: list[str] = []
    required_pin = f"paramiko=={REQUIRED_PARAMIKO_VERSION}"
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if any(str(requirement).startswith("paramiko") for requirement in manifest.get("requirements", [])):
        failures.append(
            "manifest.json must not require Paramiko; SSH install processes it on demand"
        )
    if any(str(requirement).startswith("aiortc") for requirement in manifest.get("requirements", [])):
        failures.append(
            "manifest.json must not require aiortc; media uses Home Assistant's WebRTC provider"
        )

    requirements_in = (ROOT / "requirements-dev.in").read_text(encoding="utf-8")
    current_lock = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    min_lock = (ROOT / "requirements-dev-min-ha.txt").read_text(encoding="utf-8")
    if required_pin not in requirements_in.splitlines():
        failures.append(f"requirements-dev.in must pin {required_pin}")
    if "homeassistant==" in requirements_in:
        failures.append("requirements-dev.in must leave Home Assistant to the CI lock matrix")
    expected_current_ha = f"homeassistant=={CURRENT_HOME_ASSISTANT_VERSION}"
    expected_min_ha = f"homeassistant=={MIN_HOME_ASSISTANT_VERSION}"
    if expected_current_ha not in current_lock.splitlines():
        failures.append(f"requirements-dev.txt must pin {expected_current_ha}")
    if expected_min_ha not in min_lock.splitlines():
        failures.append(f"requirements-dev-min-ha.txt must pin {expected_min_ha}")
    for path, text in {
        "requirements-dev.txt": current_lock,
        "requirements-dev-min-ha.txt": min_lock,
    }.items():
        if required_pin not in text.splitlines():
            failures.append(f"{path} must pin {required_pin}")
        if "aiortc==" in text:
            failures.append(f"{path} must not install aiortc")

    installer = (
        ROOT / "custom_components" / "bticino_c300x" / "device_installer.py"
    ).read_text(encoding="utf-8")
    if f'_REQUIRED_PARAMIKO_VERSION = "{REQUIRED_PARAMIKO_VERSION}"' not in installer:
        failures.append("device_installer.py must hard-code the validated Paramiko pin")
    if 'INSTALLER_REQUIREMENTS = (f"paramiko=={_REQUIRED_PARAMIKO_VERSION}",)' not in installer:
        failures.append("device_installer.py must request the pinned Paramiko requirement lazily")
    if "async_process_requirements(" not in installer or "is_built_in=False" not in installer:
        failures.append("device_installer.py must install optional SSH dependencies on demand")
    if "_validate_paramiko_version(paramiko)" not in installer:
        failures.append("device_installer.py must reject unvalidated Paramiko versions")

    sensor = (ROOT / "custom_components" / "bticino_c300x" / "sensor.py").read_text(
        encoding="utf-8"
    )
    if "PERCENTAGE" in sensor:
        failures.append(
            "sensor.py must not import Home Assistant PERCENTAGE; HA 2026.7 deprecates it as a unit"
        )

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    if (
        "python-patch-minor:" not in dependabot
        or 'update-types:\n          - "minor"\n          - "patch"' not in dependabot
    ):
        failures.append("Dependabot must group only Python minor/patch updates")
    if 'interval: "monthly"' not in dependabot:
        failures.append("Dependabot must check Python dependencies monthly for LTS stability")
    if (
        'dependency-name: "*"' not in dependabot
        or "version-update:semver-major" not in dependabot
    ):
        failures.append("Dependabot must leave Python major updates to manual compatibility work")
    if "Home Assistant compatibility is bumped manually" not in dependabot:
        failures.append("Dependabot must document manual Home Assistant compatibility bumps")
    if "requirements-dev.txt" not in dependabot:
        failures.append("Dependabot must document the current validation lock it updates")
    if (
        'exclude-paths:\n      - "requirements-dev-min-ha.txt"' not in dependabot
        or "minimum-HA lock" not in dependabot
    ):
        failures.append(
            "Dependabot must exclude the minimum-HA validation lock from automatic updates"
        )
    if 'dependency-name: "paramiko"' not in dependabot or '">=4"' not in dependabot:
        failures.append("Dependabot must ignore Paramiko >=4 for C300X SSH compatibility")
    if (
        'dependency-name: "homeassistant"' not in dependabot
        or '">=0"' not in dependabot
    ):
        failures.append(
            "Dependabot must leave Home Assistant dev pins to manual matrix bumps"
        )
    return failures


def check_hacs_metadata() -> list[str]:
    """Validate HACS packaging metadata and release automation."""

    failures: list[str] = []
    hacs_path = ROOT / "hacs.json"
    hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
    expected_hacs = {
        "name": "BTicino C300X",
        "homeassistant": MIN_HOME_ASSISTANT_VERSION,
        "zip_release": True,
        "filename": "ha-bticino-c300x.zip",
        "render_readme": True,
    }
    for key, expected in expected_hacs.items():
        if hacs.get(key) != expected:
            failures.append(f"hacs.json must set {key} to {expected!r}")

    custom_components = ROOT / "custom_components"
    domains = [
        path.name
        for path in custom_components.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    ]
    if domains != ["bticino_c300x"]:
        failures.append("HACS integration repos must contain exactly custom_components/bticino_c300x")

    build_script = (ROOT / "scripts" / "build_hacs_release.py").read_text(
        encoding="utf-8"
    )
    if 'RELEASE_ROOT / "ha-bticino-c300x.zip"' not in build_script:
        failures.append("HACS build script must emit the filename declared in hacs.json")
    if 'PACKAGE_ROOT / "custom_components"' in build_script:
        failures.append(
            "HACS zip_release package must contain the integration files at zip root"
        )
    if "--reuse-agent-from-release-zip" not in build_script:
        failures.append(
            "HACS build script must support verified release-agent reuse when the agent did not change"
        )

    validate_workflow_path = ROOT / ".github" / "workflows" / "validate.yml"
    release_workflow_path = ROOT / ".github" / "workflows" / "release.yml"
    codeql_config_path = ROOT / ".github" / "codeql" / "codeql-config.yml"
    validate_workflow = validate_workflow_path.read_text(encoding="utf-8")
    release_workflow = release_workflow_path.read_text(encoding="utf-8")
    codeql_config = codeql_config_path.read_text(encoding="utf-8")
    for workflow_path, workflow in {
        validate_workflow_path: validate_workflow,
        release_workflow_path: release_workflow,
    }.items():
        workflow_name = workflow_path.name
        if MIN_HOME_ASSISTANT_VERSION not in workflow:
            failures.append(
                f"{workflow_name} must test minimum Home Assistant {MIN_HOME_ASSISTANT_VERSION}"
            )
        if CURRENT_HOME_ASSISTANT_VERSION not in workflow:
            failures.append(
                f"{workflow_name} must test current Home Assistant {CURRENT_HOME_ASSISTANT_VERSION}"
            )
        if workflow.count(f'python-version: "{PYTHON_VERSION}"') < 2:
            failures.append(
                f"{workflow_name} must test minimum and current Home Assistant on Python {PYTHON_VERSION}"
            )
        if "requirements-dev.txt" not in workflow or "requirements-dev-min-ha.txt" not in workflow:
            failures.append(f"{workflow_name} must install validation dependencies from lock files")
        if "pip install --upgrade -r" in workflow:
            failures.append(f"{workflow_name} must not use moving validation requirements")
    if "hacs/action@" not in validate_workflow or "category: integration" not in validate_workflow:
        failures.append("validate workflow must run HACS integration validation")
    if "ignore: hacsjson integration_manifest" not in validate_workflow:
        failures.append(
            "HACS PR validation must document the zip_release checks that need a release asset"
        )
    if "home-assistant/actions/hassfest@" not in validate_workflow:
        failures.append("validate workflow must run Hassfest")
    for path in (
        '"device_qml/**"',
        '"custom_components/bticino_c300x/device_agent/qml/**"',
    ):
        if path not in codeql_config:
            failures.append(f"CodeQL config must ignore Qt/QML runtime path {path}")
    for path in (
        '"device_qml/js/**"',
        '"custom_components/bticino_c300x/device_agent/qml/js/**"',
    ):
        if path in codeql_config:
            failures.append(
                f"CodeQL config must ignore the complete Qt/QML tree, not only {path}"
            )

    required_release_tokens = {
        "push:\n    tags:": "release workflow must run from immutable release tags",
        "scripts/check_release_tag.py": "release workflow must validate tag metadata",
        "scripts/build_hacs_release.py": "release workflow must build the HACS zip asset",
        "Resolve reusable native agent": "release workflow must resolve reusable native-agent assets",
        "Native agent/bundle inputs changed": "release workflow must block agent reuse when bundle inputs changed",
        "gh release download": "release workflow must download the previous release asset for agent reuse",
        "--reuse-agent-from-release-zip": "release workflow must pass reusable agent assets to the HACS builder",
        "scripts/write_release_assets.py": "release workflow must write release metadata assets",
        "reused_from": "release workflow must expose native-agent reuse evidence",
        ".release/ha-bticino-c300x.zip": "release workflow must produce the HACS zip asset",
        ".release/SHA256SUMS": "release workflow must attach SHA256SUMS",
        ".release/build-metadata.json": "release workflow must attach build metadata",
        ".release/sbom.spdx.json": "release workflow must attach an SPDX SBOM",
        "sha256sum -c SHA256SUMS": "release workflow must verify release checksums",
        "actions/attest@": "release workflow must generate GitHub artifact attestations",
        "gh release create": "release workflow must publish GitHub Release assets",
        "gh release upload": "release workflow must update existing GitHub Release assets",
    }
    for token, message in required_release_tokens.items():
        if token not in release_workflow:
            failures.append(message)
    release_assets_script = (ROOT / "scripts" / "write_release_assets.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"lts_evidence"',
        '"native_agent_rebuilt"',
        '"native_agent_reused_from"',
        '"validated_jobs"',
    ):
        if token not in release_assets_script:
            failures.append(f"write_release_assets.py must write {token} release evidence")
    release_validation = (ROOT / "docs" / "release-validation.md").read_text(
        encoding="utf-8"
    )
    native_agent_docs = (ROOT / "docs" / "native-agent.md").read_text(
        encoding="utf-8"
    )
    reuse_paths = (
        "native_agent/src",
        "native_agent/scripts",
        "native_agent/VERSION",
        "native_agent/Makefile",
        "native_agent/config.example.json",
        "device_qml",
        "custom_components/bticino_c300x/device_agent/init",
        "scripts/stage_device_agent_bundle.py",
    )
    for path in reuse_paths:
        if path not in release_workflow:
            failures.append(f"release workflow must gate agent reuse on {path}")
        if path not in release_validation:
            failures.append(f"docs/release-validation.md must document agent reuse path {path}")
        if path not in native_agent_docs:
            failures.append(f"docs/native-agent.md must document agent reuse path {path}")
    return failures


def check_frontend_bundle_hash() -> list[str]:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "update_frontend_hashes.py"),
            "--check",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return [
        f"frontend bundle hash gate failed: {line.removeprefix('FAIL: ')}"
        for line in output.splitlines()
        if line
    ]


def check_github_automation() -> list[str]:
    """Keep GitHub automation pinned to immutable, least-privilege targets."""

    failures: list[str] = []
    deprecated_actions = {
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
    }
    workflow_use = re.compile(r"^\s*uses:\s*([^#\s]+)", re.MULTILINE)
    pinned_sha = re.compile(r"[0-9a-f]{40}")
    for path in (ROOT / ".github" / "workflows").rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if "runs-on: ubuntu-latest" in text:
            failures.append(f"{relative(path)} must pin the runner image instead of ubuntu-latest")
        if "permissions:" not in text or "contents: read" not in text:
            failures.append(f"{relative(path)} must declare least-privilege contents: read permissions")
        if path.name != "release.yml" and "contents: write" in text:
            failures.append(f"{relative(path)} must not grant contents: write")
        if path.name == "release.yml":
            for permission in (
                "contents: write",
                "attestations: write",
                "id-token: write",
            ):
                if permission not in text:
                    failures.append(
                        f"{relative(path)} publish job must grant {permission}"
                    )
        for action in deprecated_actions:
            if action in text:
                failures.append(f"{relative(path)} must not use deprecated {action}")
        for match in workflow_use.finditer(text):
            spec = match.group(1)
            if "@" not in spec:
                failures.append(f"{relative(path)} action use must include an immutable ref: {spec}")
                continue
            ref = spec.rsplit("@", 1)[1]
            if not pinned_sha.fullmatch(ref):
                failures.append(
                    f"{relative(path)} action use must pin a full commit SHA instead of {spec}"
                )

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    if "package-ecosystem: \"github-actions\"" not in dependabot:
        failures.append("Dependabot must monitor GitHub Actions")
    if "package-ecosystem: \"pip\"" not in dependabot:
        failures.append("Dependabot must monitor Python dependencies")
    return failures


def check_python_runtime() -> list[str]:
    failures: list[str] = []
    runtime = f"{sys.version_info.major}.{sys.version_info.minor}"
    if runtime != PYTHON_VERSION:
        failures.append(f"Python {PYTHON_VERSION} is required for the supported Home Assistant CI gates")
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    ruff_target = f"py{PYTHON_VERSION.replace('.', '')}"
    if f'target-version = "{ruff_target}"' not in text:
        failures.append(f"pyproject.toml must keep Ruff target-version at {ruff_target}")
    return failures


def check_python_compile() -> list[str]:
    failures: list[str] = []
    for path in (
        ROOT / "custom_components" / "bticino_c300x",
        ROOT / "scripts",
        ROOT / "tests",
    ):
        ok = compileall.compile_dir(str(path), quiet=1, force=True)
        if not ok:
            failures.append(f"Python compilation failed under {relative(path)}")
    return failures


def check_native_agent() -> list[str]:
    result = subprocess.run(
        ["make", "-C", str(ROOT / "native_agent"), "check"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return [f"native agent check failed: {output.strip()}"]


def check_quality_scale() -> list[str]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_quality_scale.py")],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return [line.removeprefix("FAIL: ") for line in output.splitlines() if line]


def check_media_reference_flow() -> list[str]:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_media_reference_flow.py"),
            "--fixtures",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return []
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return [
        f"media reference flow gate failed: {line}"
        for line in output.splitlines()
        if line
    ]


def is_ignored(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    if _is_tooling_path(parts):
        return True
    return any(part in {"__pycache__", "node_modules"} for part in parts)


def _is_tooling_path(parts: tuple[str, ...]) -> bool:
    ignored_paths = {
        ("native_agent", "build"),
        ("custom_components", "bticino_c300x", "device_agent", "armhf"),
        ("custom_components", "bticino_c300x", "device_agent", "qml"),
        ("custom_components", "bticino_c300x", "device_agent", "scripts"),
    }
    if any(parts[: len(prefix)] == prefix for prefix in ignored_paths):
        return True
    if parts == ("custom_components", "bticino_c300x", "device_agent", "bundle.json"):
        return True
    return any(
        part
        in {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".release",
            ".ruff_cache",
            ".venv",
            "__pycache__",
        }
        for part in parts
    )


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())
