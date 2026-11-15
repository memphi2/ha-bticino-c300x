"""Runtime inventory recognizes distribution names behind snapshot imports."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path


def test_snapshot_sources_inventory_pillow(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "snapshot_sbom_runtime", root / "scripts/sbom_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    archive_path = tmp_path / "snapshots.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in ("snapshot_capture.py", "snapshot_store.py"):
            archive.write(root / "custom_components/bticino_c300x" / name, name)
    with zipfile.ZipFile(archive_path) as archive:
        packages, relationships = inventory.runtime_inventory(archive)
    pillow = next(package for package in packages if package["name"] == "pillow")
    assert pillow["externalRefs"][0]["referenceLocator"] == "pkg:pypi/pillow"
    assert "versionInfo" not in pillow
    assert not any(package["name"] == "PIL" for package in packages)
    assert {
        "spdxElementId": "SPDXRef-Package-ha-bticino-c300x",
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": pillow["SPDXID"],
    } in relationships
