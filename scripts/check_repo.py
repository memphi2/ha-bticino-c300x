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
MIN_HOME_ASSISTANT_VERSION = "2026.5.0"
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
    ".github/dependabot.yml",
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
    "docs/device-ui-feasibility.md",
    "docs/legal.md",
    "docs/native-agent.md",
    "docs/quality-scale.md",
    "docs/user-guide.md",
    "scripts/check_quality_scale.py",
    "scripts/check_coverage.py",
    "scripts/check_typing.py",
    "scripts/smoke_ha.py",
    "requirements-dev.txt",
    "hacs.json",
    "native_agent/Makefile",
    "native_agent/config.example.json",
    "native_agent/scripts/bootstrap_firewall.sh",
    "native_agent/scripts/qml_patch.sh",
    "native_agent/src/main.c",
    "native_agent/test/smoke.py",
    "device_qml/Alarm.qml",
    "device_qml/HomeAssistant.qml",
    "device_qml/js/c300x_ha.js",
    "device_qml/js/c300x_i18n.js",
    "device_qml/js/c300x_memos.js",
    ".github/release-notes/v0.5.1.md",
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
    failures.extend(check_release_metadata())
    failures.extend(check_installer_dependency_pins())
    failures.extend(check_hacs_metadata())
    failures.extend(check_github_automation())
    failures.extend(check_python_runtime())
    failures.extend(check_quality_scale())
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
    if version != "0.5.1":
        failures.append(f"release metadata must stay on 0.5.1, got {version}")
    release_tag = f"v{version}"
    release_note = ROOT / ".github" / "release-notes" / f"{release_tag}.md"
    required_mentions = {
        "README.md": version,
        "CHANGELOG.md": release_tag,
        str(release_note.relative_to(ROOT)): release_tag,
        "SECURITY.md": "Token Handling",
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
    return failures


def check_installer_dependency_pins() -> list[str]:
    """Keep the C300X first-install SSH path on its validated Paramiko pin."""

    failures: list[str] = []
    required_pin = f"paramiko=={REQUIRED_PARAMIKO_VERSION}"
    manifest = json.loads(
        (ROOT / "custom_components" / "bticino_c300x" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if required_pin not in manifest.get("requirements", []):
        failures.append(
            f"manifest.json must pin {required_pin} for legacy C300X SSH install"
        )

    requirements_dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    if required_pin not in requirements_dev.splitlines():
        failures.append(f"requirements-dev.txt must pin {required_pin}")

    installer = (
        ROOT / "custom_components" / "bticino_c300x" / "device_installer.py"
    ).read_text(encoding="utf-8")
    if f'_REQUIRED_PARAMIKO_VERSION = "{REQUIRED_PARAMIKO_VERSION}"' not in installer:
        failures.append("device_installer.py must hard-code the validated Paramiko pin")
    if "_validate_paramiko_version(paramiko)" not in installer:
        failures.append("device_installer.py must reject unvalidated Paramiko versions")

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    if 'dependency-name: "paramiko"' not in dependabot or '">=4"' not in dependabot:
        failures.append("Dependabot must ignore Paramiko >=4 for C300X SSH compatibility")
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

    validate_workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    if "hacs/action@main" not in validate_workflow or "category: integration" not in validate_workflow:
        failures.append("validate workflow must run HACS integration validation")
    if "ignore: hacsjson integration_manifest" not in validate_workflow:
        failures.append(
            "HACS PR validation must document the zip_release checks that need a release asset"
        )
    if "home-assistant/actions/hassfest@master" not in validate_workflow:
        failures.append("validate workflow must run Hassfest")

    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    if ".release/ha-bticino-c300x.zip" not in release_workflow:
        failures.append("release workflow must build and upload the HACS zip asset")
    return failures


def check_github_automation() -> list[str]:
    """Keep GitHub automation current enough for the runner baseline."""

    failures: list[str] = []
    deprecated_actions = {
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
    }
    for path in (ROOT / ".github").rglob("*.yml"):
        text = path.read_text(encoding="utf-8")
        for action in deprecated_actions:
            if action in text:
                failures.append(f"{relative(path)} must not use deprecated {action}")

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    if "package-ecosystem: \"github-actions\"" not in dependabot:
        failures.append("Dependabot must monitor GitHub Actions")
    if "package-ecosystem: \"pip\"" not in dependabot:
        failures.append("Dependabot must monitor Python dependencies")
    return failures


def check_python_runtime() -> list[str]:
    failures: list[str] = []
    runtime = f"{sys.version_info.major}.{sys.version_info.minor}"
    if runtime != "3.14":
        failures.append(
            "Python 3.14 is required for the current Home Assistant 2026.5 gate"
        )
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    if 'target-version = "py314"' not in text:
        failures.append("pyproject.toml must keep Ruff target-version at py314")
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
