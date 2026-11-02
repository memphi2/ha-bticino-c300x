"""Direct runtime dependency inventory derived from the packaged sources.

Installed HA/device dependency versions are deliberately not inferred from the
build environment. External packages are not part of the release archive.
"""

from __future__ import annotations

import ast
import json
import sys
import zipfile
from typing import Any

_PYTHON_PACKAGES = {
    "aiohttp": False,
    "av": True,
    "homeassistant": False,
    "paramiko": True,
    "probatio": True,
    "propcache": False,
    "voluptuous": True,
}
_ROOT_ID = "SPDXRef-Package-ha-bticino-c300x"


def runtime_inventory(
    archive: zipfile.ZipFile,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    imports: set[str] = set()
    paramiko_version: str | None = None
    for name in sorted(archive.namelist()):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(archive.read(name), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imports.add(node.module.split(".")[0])
            if (
                name == "device_installer.py"
                and isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "_REQUIRED_PARAMIKO_VERSION"
                    for target in node.targets
                )
            ):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    paramiko_version = value
    external = imports - sys.stdlib_module_names
    unknown = external - _PYTHON_PACKAGES.keys()
    if unknown:
        raise ValueError(
            f"unmapped runtime imports in release: {', '.join(sorted(unknown))}"
        )
    if "paramiko" in external and not paramiko_version:
        raise ValueError("packaged SSH installer does not declare its Paramiko version")

    packages: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    for name in sorted(external):
        package_id = f"SPDXRef-Runtime-Python-{name}"
        version = paramiko_version if name == "paramiko" else None
        comment = (
            "Optional SSH install/repair dependency, installed through Home Assistant on demand; not bundled."
            if name == "paramiko"
            else "External Home Assistant runtime dependency; installed version not observed; not bundled."
        )
        package = _external_package(package_id, name, comment)
        if version:
            package["versionInfo"] = version
        package["externalRefs"] = [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:pypi/{name}"
                + (f"@{version}" if version else ""),
            }
        ]
        packages.append(package)
        relationships.append(_dependency(_ROOT_ID, package_id, _PYTHON_PACKAGES[name]))

    native_file = "device_agent/armhf/c300x-agent-native"
    if native_file in archive.namelist():
        native_id = "SPDXRef-Native-Agent"
        native = _external_package(
            native_id,
            "c300x-agent-native",
            "Project native agent included in the archive; external device libraries are not bundled.",
        )
        native["licenseDeclared"] = "Apache-2.0"
        native["packageFileName"] = native_file
        if "device_agent/bundle.json" in archive.namelist():
            version = json.loads(archive.read("device_agent/bundle.json")).get(
                "agent_version"
            )
            if isinstance(version, str):
                native["versionInfo"] = version
        packages.append(native)
        relationships.append(
            {
                "spdxElementId": _ROOT_ID,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": native_id,
            }
        )
        for name, sonames, optional in (
            (
                "glibc",
                "libc.so.6, libpthread.so.0, libdl.so.2, ld-linux-armhf.so.3",
                False,
            ),
            ("libsrtp", "libsrtp.so.1", True),
            ("speex", "libspeex.so.1", True),
            ("curl", "libcurl.so.4", True),
        ):
            package_id = f"SPDXRef-Runtime-Native-{name}"
            packages.append(
                _external_package(
                    package_id,
                    name,
                    f"Device-provided runtime library ({sonames}); installed version not observed; not bundled.",
                )
            )
            relationships.append(_dependency(native_id, package_id, optional))
    return packages, relationships


def _external_package(package_id: str, name: str, comment: str) -> dict[str, Any]:
    return {
        "SPDXID": package_id,
        "name": name,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "comment": comment,
    }


def _dependency(parent: str, dependency: str, optional: bool) -> dict[str, str]:
    if optional:
        return {
            "spdxElementId": dependency,
            "relationshipType": "OPTIONAL_DEPENDENCY_OF",
            "relatedSpdxElement": parent,
        }
    return {
        "spdxElementId": parent,
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": dependency,
    }
